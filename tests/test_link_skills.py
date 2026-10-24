from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_tooling.link_skills import link_skills, main

NAMES = ("media-a", "media-b")


def make_skills(root: Path) -> Path:
    skills = root / "pkg" / ".agents" / "skills"
    for name in NAMES:
        (skills / name).mkdir(parents=True)
        (skills / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n", encoding="utf-8")
    return skills


class LinkSkillsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.skills = make_skills(self.root)
        self.agents = self.root / "home" / ".agents" / "skills"
        self.claude = self.root / "home" / ".claude" / "skills"
        (self.root / "home" / ".claude").mkdir(parents=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_link(self, **kw: object) -> list[tuple[str, str]]:
        actions = link_skills(skills_dir=self.skills, agents_dir=self.agents, claude_dir=self.claude, names=NAMES,
                              **kw)  # type: ignore[arg-type]
        return [(a.path.name if a.path.parent == self.agents else "claude/" + a.path.name, a.status) for a in actions]

    def test_links_shared_store_and_claude_store_relatively(self) -> None:
        self.assertEqual(self.run_link(), [("media-a", "linked"), ("claude/media-a", "linked"),
                                           ("media-b", "linked"), ("claude/media-b", "linked")])
        self.assertEqual(os.readlink(self.agents / "media-a"), str((self.skills / "media-a").resolve()))
        self.assertEqual(os.readlink(self.claude / "media-a"), "../../.agents/skills/media-a")
        self.assertTrue((self.claude / "media-b" / "SKILL.md").is_file())

    def test_rerun_is_a_no_op_and_stale_links_are_repaired(self) -> None:
        self.run_link()
        self.assertEqual({s for _, s in self.run_link()}, {"current"})
        (self.agents / "media-a").unlink()
        (self.agents / "media-a").symlink_to(self.root / "old-python" / "media-a")  # dangling, as after a rebuild
        statuses = dict(self.run_link())
        self.assertEqual(statuses["media-a"], "relinked")
        self.assertTrue((self.claude / "media-a" / "SKILL.md").is_file())

    def test_real_directory_is_skipped_unless_forced_and_then_kept_as_backup(self) -> None:
        (self.agents / "media-a").mkdir(parents=True)
        (self.agents / "media-a" / "SKILL.md").write_text("old pointer", encoding="utf-8")
        self.assertEqual(dict(self.run_link())["media-a"], "skipped")
        self.assertFalse((self.agents / "media-a").is_symlink())
        self.assertEqual(dict(self.run_link(force=True))["media-a"], "backed-up")
        self.assertTrue((self.agents / "media-a").is_symlink())
        backups = [p for p in self.agents.iterdir() if p.name.startswith("media-a.bak-")]
        self.assertEqual(len(backups), 1)
        self.assertEqual((backups[0] / "SKILL.md").read_text(encoding="utf-8"), "old pointer")

    def test_dry_run_changes_nothing(self) -> None:
        self.assertEqual({s for _, s in self.run_link(dry_run=True)}, {"linked"})
        self.assertFalse(self.agents.exists())

    def test_antigravity_folders_link_relative_to_the_claude_store(self) -> None:
        gemini = self.root / "home" / ".gemini"
        dirs = (gemini / "skills", gemini / "antigravity" / "skills")
        actions = link_skills(skills_dir=self.skills, agents_dir=self.agents, claude_dir=self.claude, names=NAMES,
                              antigravity_dirs=dirs)
        self.assertEqual({a.status for a in actions}, {"linked"})
        self.assertEqual(os.readlink(dirs[0] / "media-a"), "../../.claude/skills/media-a")
        self.assertEqual(os.readlink(dirs[1] / "media-a"), "../../../.claude/skills/media-a")
        self.assertTrue((dirs[1] / "media-b" / "SKILL.md").is_file())

    def test_hand_made_antigravity_links_of_the_same_form_count_as_current(self) -> None:
        link_dir = self.root / "home" / ".gemini" / "antigravity-cli" / "skills"
        link_dir.mkdir(parents=True)
        for name in NAMES:
            (link_dir / name).symlink_to(f"../../../.claude/skills/{name}")
        actions = link_skills(skills_dir=self.skills, agents_dir=self.agents, claude_dir=self.claude, names=NAMES,
                              antigravity_dirs=(link_dir,))
        self.assertEqual({a.status for a in actions if a.path.parent == link_dir}, {"current"})

    def test_antigravity_links_fall_back_to_the_shared_store_without_claude(self) -> None:
        link_dir = self.root / "home" / ".gemini" / "skills"
        link_skills(skills_dir=self.skills, agents_dir=self.agents, claude_dir=None, names=NAMES,
                    antigravity_dirs=(link_dir,))
        self.assertEqual(os.readlink(link_dir / "media-a"), "../../.agents/skills/media-a")
        self.assertTrue((link_dir / "media-a" / "SKILL.md").is_file())

    def test_foreign_antigravity_entries_are_never_clobbered(self) -> None:
        link_dir = self.root / "home" / ".gemini" / "skills"
        (link_dir / "media-a").mkdir(parents=True)
        actions = link_skills(skills_dir=self.skills, agents_dir=self.agents, claude_dir=self.claude, names=NAMES,
                              antigravity_dirs=(link_dir,))
        self.assertEqual({a.path.name: a.status for a in actions if a.path.parent == link_dir},
                         {"media-a": "skipped", "media-b": "linked"})
        self.assertFalse((link_dir / "media-a").is_symlink())

    def run_main(self, home: Path, *args: str) -> tuple[int, str]:
        with patch("media_tooling.link_skills.resolve_toolkit_skills_dir", return_value=self.skills), \
                patch("media_tooling.link_skills.SKILL_NAMES", NAMES), \
                patch("media_tooling.link_skills.Path.home", return_value=home), \
                patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": ""}), \
                patch("sys.stdout", new_callable=io.StringIO) as out, patch("sys.stderr", new_callable=io.StringIO):
            code = main(["--no-private", *args])
        return code, out.getvalue()

    def test_main_links_only_antigravity_folders_whose_parent_exists(self) -> None:
        home = self.root / "home"
        (home / ".gemini" / "antigravity").mkdir(parents=True)
        code, _ = self.run_main(home)
        self.assertEqual(code, 0)
        self.assertEqual(os.readlink(home / ".gemini" / "skills" / "media-a"), "../../.claude/skills/media-a")
        self.assertTrue((home / ".gemini" / "antigravity" / "skills" / "media-b" / "SKILL.md").is_file())
        self.assertFalse((home / ".gemini" / "antigravity-cli").exists())

    def test_main_antigravity_flags_override_or_skip_the_defaults(self) -> None:
        home = self.root / "home"
        (home / ".gemini").mkdir()
        custom = self.root / "elsewhere" / "skills"
        custom.parent.mkdir()
        self.run_main(home, "--antigravity-dir", str(custom))
        self.assertTrue((custom / "media-a" / "SKILL.md").is_file())
        self.assertFalse((home / ".gemini" / "skills").exists())
        self.run_main(home, "--no-antigravity")
        self.assertFalse((home / ".gemini" / "skills").exists())

    def test_main_dry_run_reports_antigravity_links_without_writing(self) -> None:
        home = self.root / "home"
        (home / ".gemini").mkdir()
        code, out = self.run_main(home, "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn(str(home / ".gemini" / "skills" / "media-a"), out)
        self.assertFalse((home / ".gemini" / "skills").exists())

    def test_main_skips_claude_when_it_is_not_installed_and_reports_skips(self) -> None:
        home = self.root / "bare"
        agents = home / ".agents" / "skills"
        (agents / "media-a").mkdir(parents=True)
        with patch("media_tooling.link_skills.resolve_toolkit_skills_dir", return_value=self.skills), \
                patch("media_tooling.link_skills.SKILL_NAMES", NAMES), \
                patch("sys.stdout", new_callable=io.StringIO) as out, patch("sys.stderr", new_callable=io.StringIO):
            code = main(["--agents-dir", str(agents), "--claude-dir", str(home / ".claude" / "skills"),
                         "--no-antigravity"])
        self.assertEqual(code, 2)
        self.assertIn("Claude Code not found", out.getvalue())
        self.assertTrue((agents / "media-b").is_symlink())
        self.assertFalse((home / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
