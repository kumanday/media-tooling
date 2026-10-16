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

    def test_main_skips_claude_when_it_is_not_installed_and_reports_skips(self) -> None:
        home = self.root / "bare"
        agents = home / ".agents" / "skills"
        (agents / "media-a").mkdir(parents=True)
        with patch("media_tooling.link_skills.resolve_toolkit_skills_dir", return_value=self.skills), \
                patch("media_tooling.link_skills.SKILL_NAMES", NAMES), \
                patch("sys.stdout", new_callable=io.StringIO) as out, patch("sys.stderr", new_callable=io.StringIO):
            code = main(["--agents-dir", str(agents), "--claude-dir", str(home / ".claude" / "skills")])
        self.assertEqual(code, 2)
        self.assertIn("Claude Code not found", out.getvalue())
        self.assertTrue((agents / "media-b").is_symlink())
        self.assertFalse((home / ".claude").exists())


if __name__ == "__main__":
    unittest.main()
