from __future__ import annotations

import argparse
import re
from importlib import resources
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
    "edit",
)

PROJECT_MEMORY_PATH = "edit/project.md"

PROJECT_MEMORY_INITIAL_CONTENT = """\
# Project Memory

## Strategy

_(Current approach and goals for this project)_

## Decisions

_(Key choices made and their rationale)_

## Reasoning log

_(Significant inference chains or trade-off evaluations)_

## Outstanding items

_(Unfinished work, open questions, or next actions)_
"""
SKILL_NAMES = (
    "media-corpus-ingest",
    "media-subtitle-pipeline",
    "media-rough-cut-assembly",
)
MANAGED_BLOCK_START = "<!-- media-tooling:init:start -->"
MANAGED_BLOCK_END = "<!-- media-tooling:init:end -->"
TEMPLATE_PATH = "templates/project_AGENTS.md"
TEMPLATE_MANAGED_BLOCK_START = "{{MANAGED_BLOCK_START}}"
TEMPLATE_MANAGED_BLOCK_END = "{{MANAGED_BLOCK_END}}"
TEMPLATE_SKILL_PATHS = "{{SKILL_PATHS}}"


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


def ensure_project_memory(*, project_dir: Path, create_memory: bool) -> tuple[Path, str]:
    memory_path = project_dir / PROJECT_MEMORY_PATH
    if not create_memory or memory_path.exists():
        return memory_path, "exists"
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    memory_path.write_text(PROJECT_MEMORY_INITIAL_CONTENT, encoding="utf-8")
    return memory_path, "created"


def main() -> None:
    args = parse_args()
    project_dir = Path(args.project_dir).expanduser().resolve()
    skills_dir = resolve_toolkit_skills_dir()
    create_directories = not args.agents_only
    created_dirs = ensure_project_directories(
        project_dir=project_dir,
        create_directories=create_directories,
    )
    memory_path, memory_action = ensure_project_memory(
        project_dir=project_dir,
        create_memory=create_directories,
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
    print(f"project.md: {memory_action} {memory_path}")
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
    template = load_project_agents_template()
    return (
        template.replace(TEMPLATE_MANAGED_BLOCK_START, MANAGED_BLOCK_START)
        .replace(TEMPLATE_MANAGED_BLOCK_END, MANAGED_BLOCK_END)
        .replace(TEMPLATE_SKILL_PATHS, skill_lines)
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


def load_project_agents_template() -> str:
    template = resources.files("media_tooling").joinpath(TEMPLATE_PATH).read_text(
        encoding="utf-8"
    )
    if TEMPLATE_SKILL_PATHS not in template:
        raise ValueError(
            f"Project AGENTS template is missing the required placeholder: {TEMPLATE_SKILL_PATHS}"
        )
    return template.rstrip()
