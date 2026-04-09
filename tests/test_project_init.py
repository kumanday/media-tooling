from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_tooling.project_init import (
    MANAGED_BLOCK_END,
    MANAGED_BLOCK_START,
    PROJECT_SUBDIRECTORIES,
    ensure_project_directories,
    render_project_agents_block,
    upsert_project_agents,
)


class ProjectInitTests(unittest.TestCase):
    def test_ensure_project_directories_creates_standard_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"

            created = ensure_project_directories(
                project_dir=project_dir,
                create_directories=True,
            )

            self.assertEqual(len(created), len(PROJECT_SUBDIRECTORIES))
            for relative_path in PROJECT_SUBDIRECTORIES:
                self.assertTrue((project_dir / relative_path).is_dir())

    def test_upsert_project_agents_creates_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            skills_dir = Path("/tmp/media-tooling-skills")

            agents_path, action = upsert_project_agents(
                project_dir=project_dir,
                skills_dir=skills_dir,
            )

            self.assertEqual(action, "created")
            contents = agents_path.read_text(encoding="utf-8")
            self.assertIn(MANAGED_BLOCK_START, contents)
            self.assertIn(MANAGED_BLOCK_END, contents)
            self.assertIn(
                "/tmp/media-tooling-skills/media-corpus-ingest/SKILL.md",
                contents,
            )

    def test_upsert_project_agents_appends_without_clobbering_existing_content(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            agents_path = project_dir / "AGENTS.md"
            agents_path.write_text("# Existing Project Instructions\n", encoding="utf-8")

            _, action = upsert_project_agents(
                project_dir=project_dir,
                skills_dir=Path("/tmp/media-tooling-skills"),
            )

            self.assertEqual(action, "appended")
            contents = agents_path.read_text(encoding="utf-8")
            self.assertIn("# Existing Project Instructions", contents)
            self.assertEqual(contents.count(MANAGED_BLOCK_START), 1)

    def test_upsert_project_agents_replaces_existing_managed_block(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            agents_path = project_dir / "AGENTS.md"
            original = "\n".join(
                [
                    "# Existing Project Instructions",
                    "",
                    MANAGED_BLOCK_START,
                    "old block",
                    MANAGED_BLOCK_END,
                    "",
                ]
            )
            agents_path.write_text(original, encoding="utf-8")

            _, action = upsert_project_agents(
                project_dir=project_dir,
                skills_dir=Path("/tmp/new-skills"),
            )

            self.assertEqual(action, "updated")
            contents = agents_path.read_text(encoding="utf-8")
            self.assertIn("# Existing Project Instructions", contents)
            self.assertIn("/tmp/new-skills/media-subtitle-pipeline/SKILL.md", contents)
            self.assertNotIn("old block", contents)
            self.assertEqual(contents.count(MANAGED_BLOCK_START), 1)

    def test_render_project_agents_block_lists_all_skill_paths(self) -> None:
        block = render_project_agents_block(Path("/tmp/toolkit-skills"))

        self.assertIn(
            "/tmp/toolkit-skills/media-corpus-ingest/SKILL.md",
            block,
        )
        self.assertIn(
            "/tmp/toolkit-skills/media-subtitle-pipeline/SKILL.md",
            block,
        )
        self.assertIn(
            "/tmp/toolkit-skills/media-rough-cut-assembly/SKILL.md",
            block,
        )


if __name__ == "__main__":
    unittest.main()
