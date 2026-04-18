from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_tooling.project_init import (
    MANAGED_BLOCK_END,
    MANAGED_BLOCK_START,
    PROJECT_MEMORY_INITIAL_CONTENT,
    PROJECT_MEMORY_PATH,
    PROJECT_SUBDIRECTORIES,
    ensure_project_directories,
    ensure_project_memory,
    load_project_agents_template,
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

    def test_project_agents_template_contains_required_placeholder(self) -> None:
        template = load_project_agents_template()

        self.assertIn("{{SKILL_PATHS}}", template)
        self.assertIn("{{MANAGED_BLOCK_START}}", template)
        self.assertIn("{{MANAGED_BLOCK_END}}", template)

    def test_project_agents_template_contains_memory_protocol(self) -> None:
        template = load_project_agents_template()

        self.assertIn("Session Memory Protocol", template)
        self.assertIn("Strategy", template)
        self.assertIn("Decisions", template)
        self.assertIn("Reasoning log", template)
        self.assertIn("Outstanding items", template)
        self.assertIn("project.md", template)
        self.assertIn("summarize the last session", template)

    def test_ensure_project_memory_creates_file_in_new_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)

            memory_path, action = ensure_project_memory(
                project_dir=project_dir,
                create_memory=True,
            )

            self.assertEqual(action, "created")
            self.assertTrue(memory_path.exists())
            contents = memory_path.read_text(encoding="utf-8")
            self.assertIn("# Project Memory", contents)

    def test_ensure_project_memory_does_not_overwrite_existing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            memory_path = project_dir / PROJECT_MEMORY_PATH
            memory_path.parent.mkdir(parents=True, exist_ok=True)
            memory_path.write_text("existing content", encoding="utf-8")

            _, action = ensure_project_memory(
                project_dir=project_dir,
                create_memory=True,
            )

            self.assertEqual(action, "exists")
            contents = memory_path.read_text(encoding="utf-8")
            self.assertEqual(contents, "existing content")

    def test_ensure_project_memory_skipped_when_create_memory_false(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)

            _, action = ensure_project_memory(
                project_dir=project_dir,
                create_memory=False,
            )

            self.assertEqual(action, "skipped")
            self.assertFalse((project_dir / PROJECT_MEMORY_PATH).exists())

    def test_ensure_project_directories_includes_edit_dir(self) -> None:
        self.assertIn("edit", PROJECT_SUBDIRECTORIES)

    def test_project_memory_initial_content_has_title(self) -> None:
        self.assertIn("# Project Memory", PROJECT_MEMORY_INITIAL_CONTENT)

    def test_project_agents_template_contains_hard_rules_section(self) -> None:
        template = load_project_agents_template()

        self.assertIn("Hard Rules", template)
        self.assertIn("Subtitles applied last in filter chain", template)

    def test_project_agents_template_contains_anti_patterns_section(self) -> None:
        template = load_project_agents_template()

        self.assertIn("Anti-patterns", template)
        self.assertIn("Hierarchical pre-computed codec formats", template)


if __name__ == "__main__":
    unittest.main()
