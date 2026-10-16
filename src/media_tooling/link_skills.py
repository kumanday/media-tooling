"""Make the installed media-tooling skills visible to coding agents.

Agents discover skills in per-user directories rather than through a project's
AGENTS.md. This command links each toolkit skill into the shared store
(``~/.agents/skills``, read by Codex and other agents) and links the Claude Code
store (``~/.claude/skills``) to those entries with relative symlinks, so every
agent reads the same files and an upgrade reaches all of them.

Run it after installing or upgrading media-tooling. The link targets live inside
the installed package, whose path can change when uv rebuilds the tool
environment, so re-running is how stale links get repaired.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from media_tooling.project_init import SKILL_NAMES, resolve_toolkit_skills_dir


@dataclass
class Action:
    path: Path
    status: str  # linked, relinked, current, skipped, backed-up
    detail: str = ""


def default_claude_dir() -> Path:
    base = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return (Path(base).expanduser() if base else Path.home() / ".claude") / "skills"


def _same_target(link: Path, target: str) -> bool:
    return link.is_symlink() and os.readlink(link) == target


def place_link(link: Path, target: str, *, force: bool, dry_run: bool) -> Action:
    """Point ``link`` at ``target``; never deletes a real file or directory."""
    if _same_target(link, target):
        return Action(link, "current")
    existed = link.is_symlink() or link.exists()
    if existed and not link.is_symlink():
        if not force:
            return Action(link, "skipped", "exists and is not a symlink; pass --force to move it aside")
        backup = link.with_name(f"{link.name}.bak-{time.strftime('%Y%m%d%H%M%S')}")
        if not dry_run:
            link.rename(backup)
        status, detail = "backed-up", f"moved the existing entry to {backup.name}"
    else:
        status, detail = ("relinked" if existed else "linked"), ""
    if not dry_run:
        link.parent.mkdir(parents=True, exist_ok=True)
        if link.is_symlink():
            link.unlink()
        link.symlink_to(target)
    return Action(link, status, detail)


def link_skills(*, skills_dir: Path, agents_dir: Path, claude_dir: Path | None, names: tuple[str, ...],
                force: bool = False, dry_run: bool = False) -> list[Action]:
    actions: list[Action] = []
    for name in names:
        source = skills_dir / name
        if not (source / "SKILL.md").is_file():
            raise FileNotFoundError(f"{source / 'SKILL.md'} not found")
        shared = agents_dir / name
        actions.append(place_link(shared, str(source.resolve()), force=force, dry_run=dry_run))
        if claude_dir is not None:
            # realpath on the directories (not the link) so the relative path is the same on every run
            relative = os.path.relpath(os.path.join(os.path.realpath(agents_dir), name), os.path.realpath(claude_dir))
            actions.append(place_link(claude_dir / name, relative, force=force, dry_run=dry_run))
    return actions


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Link the installed media-tooling skills into the agents' skill directories.")
    p.add_argument("--agents-dir", default=str(Path.home() / ".agents" / "skills"),
                   help="shared skill store (default ~/.agents/skills)")
    p.add_argument("--claude-dir", default=None,
                   help="Claude Code skill store (default $CLAUDE_CONFIG_DIR/skills or ~/.claude/skills)")
    p.add_argument("--no-claude", action="store_true", help="do not link into the Claude Code store")
    p.add_argument("--force", action="store_true",
                   help="move an existing non-symlink entry aside (renamed *.bak-<time>) instead of skipping it")
    p.add_argument("--dry-run", action="store_true", help="report what would change without touching the filesystem")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    claude_dir = None if a.no_claude else (Path(a.claude_dir).expanduser() if a.claude_dir else default_claude_dir())
    if claude_dir is not None and not claude_dir.parent.exists():
        print(f"Claude Code not found ({claude_dir.parent} is missing); linking the shared store only.")
        claude_dir = None
    try:
        skills_dir = resolve_toolkit_skills_dir()
        actions = link_skills(skills_dir=skills_dir, agents_dir=Path(a.agents_dir).expanduser(), claude_dir=claude_dir,
                              names=SKILL_NAMES, force=a.force, dry_run=a.dry_run)
    except (OSError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Toolkit skills: {skills_dir}{' (dry run)' if a.dry_run else ''}")
    for act in actions:
        print(f"- {act.status:9} {act.path}{f'  ({act.detail})' if act.detail else ''}")
    skipped = [act for act in actions if act.status == "skipped"]
    if skipped:
        print(f"{len(skipped)} entr{'y' if len(skipped) == 1 else 'ies'} skipped; re-run with --force to move them aside.",
              file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
