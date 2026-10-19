from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from media_tooling import local_config as lc
from media_tooling.link_skills import link_private_skills, main, toolkit_skill_names
from media_tooling.project_init import (
    LOCAL_BLOCK_END,
    LOCAL_BLOCK_START,
    MANAGED_BLOCK_END,
    MANAGED_BLOCK_START,
    render_local_block,
    resolve_toolkit_skills_dir,
    upsert_local_block,
)

PROFILES = """
[profiles.work]
[profiles.notes]
rules = "embed"

[[rules]]
path = "~/dev/work/**"
profile = "work"

[[rules]]
path = "~/dev/notes/**"
profile = "notes"
"""


class LocalOverlayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.home = root / "home"
        self.cfg = root / "cfg"
        (self.cfg / "profiles" / "work").mkdir(parents=True)
        (self.cfg / "profiles" / "notes").mkdir(parents=True)
        (self.cfg / "profiles.toml").write_text(PROFILES)
        (self.cfg / "profiles" / "work" / "AGENTS.md").write_text("Private: use the house style.\n")
        (self.cfg / "profiles" / "notes" / "AGENTS.md").write_text("Private: notes rules.\n")
        for d in ("dev/work/slot", "dev/notes/slot", "dev/other/slot"):
            (self.home / d).mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "MEDIA_TOOLING_CONFIG_DIR": str(self.cfg)})
        self.env.start()

    def tearDown(self) -> None:
        self.env.stop()
        self.tmp.cleanup()

    def test_no_config_folder_is_fine(self) -> None:
        with mock.patch.dict(os.environ, {"MEDIA_TOOLING_CONFIG_DIR": str(self.home / "absent")}):
            self.assertEqual(lc.load_config(required=False), {"profiles": {}})
            block, note = render_local_block(self.home / "dev" / "work" / "slot")
        self.assertIsNone(block)
        self.assertIn("no local profile", note)

    def test_reference_mode_points_at_the_private_file(self) -> None:
        block, note = render_local_block(self.home / "dev" / "work" / "slot")
        assert block is not None
        self.assertIn("work profile", block)
        self.assertNotIn("house style", block)  # content stays out of the project
        self.assertIn("AGENTS.md", block)
        self.assertIn("reference", note)

    def test_embed_mode_copies_the_rules(self) -> None:
        block, _ = render_local_block(self.home / "dev" / "notes" / "slot")
        assert block is not None
        self.assertIn("Private: notes rules.", block)

    def test_upsert_places_after_managed_block_then_removes(self) -> None:
        agents = self.home / "dev" / "work" / "slot" / "AGENTS.md"
        agents.write_text(f"{MANAGED_BLOCK_START}\ntoolkit\n{MANAGED_BLOCK_END}\n\nMy own notes.\n")
        block, _ = render_local_block(agents.parent)
        self.assertEqual(upsert_local_block(agents, block), "added")
        text = agents.read_text()
        self.assertLess(text.index(MANAGED_BLOCK_END), text.index(LOCAL_BLOCK_START))
        self.assertLess(text.index(LOCAL_BLOCK_END), text.index("My own notes."))
        self.assertEqual(upsert_local_block(agents, block), "updated")
        self.assertEqual(agents.read_text().count(LOCAL_BLOCK_START), 1)
        self.assertEqual(upsert_local_block(agents, None), "removed")
        self.assertNotIn(LOCAL_BLOCK_START, agents.read_text())
        self.assertIn("My own notes.", agents.read_text())

    def test_unmatched_project_gets_no_block(self) -> None:
        block, note = render_local_block(self.home / "dev" / "other" / "slot")
        self.assertIsNone(block)
        self.assertIn("no local profile", note)


class PrivateSkillTests(unittest.TestCase):
    def test_private_skills_link_and_toolkit_names_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            private = root / "cfg" / "skills"
            for name in ("blog-explainer", "media-tts", "commit"):
                (private / name).mkdir(parents=True)
                (private / name / "SKILL.md").write_text(f"---\nname: {name}\n---\n")
            agents, claude = root / "agents", root / "claude"
            reserved = toolkit_skill_names(resolve_toolkit_skills_dir())
            self.assertIn("commit", reserved)  # packaged but not one of the linked routing skills
            actions = link_private_skills(private_dir=private, agents_dir=agents, claude_dir=claude, reserved=reserved)
            self.assertTrue((agents / "blog-explainer").is_symlink())
            self.assertTrue((claude / "blog-explainer" / "SKILL.md").is_file())
            self.assertFalse((agents / "media-tts").exists())
            self.assertFalse((agents / "commit").exists())
            self.assertEqual(sum(a.status == "skipped" for a in actions), 2)

    def test_private_skill_never_takes_over_another_link_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            private = root / "cfg" / "skills"
            (private / "notes").mkdir(parents=True)
            (private / "notes" / "SKILL.md").write_text("---\nname: notes\n---\n")
            elsewhere = root / "other-source" / "notes"
            elsewhere.mkdir(parents=True)
            agents = root / "agents"
            agents.mkdir()
            (agents / "notes").symlink_to(elsewhere)
            actions = link_private_skills(private_dir=private, agents_dir=agents, claude_dir=None, reserved=set())
            self.assertEqual(actions[0].status, "skipped")
            self.assertEqual(os.readlink(agents / "notes"), str(elsewhere))
            actions = link_private_skills(private_dir=private, agents_dir=agents, claude_dir=None, reserved=set(),
                                          force=True)
            self.assertEqual(Path(os.readlink(agents / "notes")).resolve(), (private / "notes").resolve())

    def test_main_reports_private_skills(self) -> None:
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            cfg = root / "cfg"
            (cfg / "skills" / "blog-explainer").mkdir(parents=True)
            (cfg / "skills" / "blog-explainer" / "SKILL.md").write_text("---\nname: blog-explainer\n---\n")
            out = io.StringIO()
            with mock.patch.dict(os.environ, {"MEDIA_TOOLING_CONFIG_DIR": str(cfg)}), redirect_stdout(out):
                code = main(["--agents-dir", str(root / "agents"), "--no-claude"])
            self.assertEqual(code, 0)
            self.assertIn("Private skills:", out.getvalue())
            self.assertTrue((root / "agents" / "blog-explainer").is_symlink())


if __name__ == "__main__":
    unittest.main()
