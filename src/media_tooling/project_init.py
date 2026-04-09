from __future__ import annotations

import argparse
import re
from pathlib import Path

PROJECT_SUBDIRECTORIES = (
    "assets/audio",
    "assets/reference",
    "inventory",
    "analysis",
    "transcripts",
    "subtitles",
    "storyboards",
    "rough-cuts/assemblies",
    "rough-cuts/generated-clips",
    "rough-cuts/manifests",
    "rough-cuts/specs",
)
SKILL_NAMES = (
    "media-corpus-ingest",
    "media-subtitle-pipeline",
    "media-rough-cut-assembly",
)
MANAGED_BLOCK_START = "<!-- media-tooling:init:start -->"
MANAGED_BLOCK_END = "<!-- media-tooling:init:end -->"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize a project-local media-tooling workspace."
    )
    parser.add_argument("project_dir", help="Path to the project workspace.")
    parser.add_argument(
        "--agents-only",
        action="store_true",
        help="Only update the managed block in AGENTS.md.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    skills_dir = resolve_toolkit_skills_dir()
    created_dirs = ensure_project_directories(
        project_dir=project_dir,
        create_directories=not args.agents_only,
    )
    agents_path, agents_action = upsert_project_agents(
        project_dir=project_dir,
        skills_dir=skills_dir,
    )

    print(f"Project workspace: {project_dir}")
    if args.agents_only:
        print("Skipped standard directory scaffolding.")
    elif created_dirs:
        print("Created directories:")
        for path in created_dirs:
            print(f"- {path}")
    else:
        print("Standard project directories already existed.")
    print(f"AGENTS.md: {agents_action} {agents_path}")
    print(f"Toolkit skills: {skills_dir}")


def ensure_project_directories(
    *, project_dir: Path, create_directories: bool
) -> list[Path]:
    project_dir.mkdir(parents=True, exist_ok=True)
    if not create_directories:
        return []

    created: list[Path] = []
    for relative_path in PROJECT_SUBDIRECTORIES:
        output_path = project_dir / relative_path
        if not output_path.exists():
            created.append(output_path)
        output_path.mkdir(parents=True, exist_ok=True)
    return created


def upsert_project_agents(*, project_dir: Path, skills_dir: Path) -> tuple[Path, str]:
    agents_path = project_dir / "AGENTS.md"
    managed_block = render_project_agents_block(skills_dir)

    if not agents_path.exists():
        agents_path.write_text(f"{managed_block}\n", encoding="utf-8")
        return agents_path, "created"

    existing = agents_path.read_text(encoding="utf-8")
    pattern = re.compile(
        rf"{re.escape(MANAGED_BLOCK_START)}.*?{re.escape(MANAGED_BLOCK_END)}",
        re.DOTALL,
    )

    if pattern.search(existing):
        updated = pattern.sub(managed_block, existing, count=1)
        if not updated.endswith("\n"):
            updated = f"{updated}\n"
        agents_path.write_text(updated, encoding="utf-8")
        return agents_path, "updated"

    prefix = existing.rstrip()
    if prefix:
        new_contents = f"{prefix}\n\n{managed_block}\n"
        action = "appended"
    else:
        new_contents = f"{managed_block}\n"
        action = "updated"

    agents_path.write_text(new_contents, encoding="utf-8")
    return agents_path, action


def render_project_agents_block(skills_dir: Path) -> str:
    skill_paths = [skills_dir / skill_name / "SKILL.md" for skill_name in SKILL_NAMES]
    skill_lines = "\n".join(f"- {path}" for path in skill_paths)
    return "\n".join(
        [
            MANAGED_BLOCK_START,
            "# Media Tooling Project Context",
            "",
            "This block is managed by `media-tooling-init`.",
            "Treat this directory as `$PROJECT_DIR` and keep project artifacts inside it.",
            "",
            "Read these central media-tooling skills before routing media-processing work:",
            skill_lines,
            "",
            "Use installed toolkit commands from this project directory:",
            "- spoken media: `media-subtitle` or `media-batch-subtitle`",
            "- silent or visual-first video: `media-contact-sheet` or `media-batch-contact-sheet`",
            "- rough-cut assembly: `media-rough-cut`",
            "",
            "Operational defaults:",
            "- prefer sequential processing for long media jobs",
            "- use `--skip-existing` for resumable batches",
            "- keep reusable toolkit code and installs outside this project workspace",
            "- re-run `media-tooling-init` after reinstalling or relocating the toolkit so these skill paths stay current",
            MANAGED_BLOCK_END,
        ]
    )


def resolve_toolkit_skills_dir() -> Path:
    package_dir = Path(__file__).resolve().parent
    candidates = (
        package_dir / ".agents" / "skills",
        package_dir.parent.parent / ".agents" / "skills",
    )

    for candidate in candidates:
        if all((candidate / skill_name / "SKILL.md").is_file() for skill_name in SKILL_NAMES):
            return candidate

    searched = "\n".join(f"- {candidate}" for candidate in candidates)
    raise FileNotFoundError(
        "Could not locate the packaged media-tooling skills. Checked:\n"
        f"{searched}"
    )
