"""Your private media-tooling configuration: profiles, private rules and private skills, kept outside this repository.

The toolkit is public; how you use it is not. Everything personal lives in one local folder,
``~/.config/media-tooling/`` (or ``$MEDIA_TOOLING_CONFIG_DIR``; point it at a private git repository to version or
sync it)::

    profiles.toml                 which profile applies to which project folder, and per-profile settings
    profiles/<name>/AGENTS.md     private rules for projects of that profile (house style, sources, where things live)
    skills/<skill>/SKILL.md       private skills, linked next to the toolkit's by media-tooling-link-skills
    adc/<name>.json               per-profile Google credentials (media-cloud-render setup --save-adc)
    cloudrun/<name>/              per-profile cloud render stack (media-cloud-render deploy)

``profiles.toml``::

    default_profile = "personal"

    [profiles.work]
    rules = "reference"               # how media-tooling-init adds profiles/work/AGENTS.md: reference | embed
    # cloud rendering (media-cloud-render), optional:
    gcloud_configuration = "work-cfg"
    account = "me@work.example"
    project = "work-gcp-project"
    region = "us-central1"

    [profiles.personal]

    [[rules]]                         # first match wins
    path = "~/dev/work/**"
    profile = "work"

Which profile applies to a project, highest first: an explicit ``--profile``; ``render_profile`` (or ``profile``) in
the nearest ``media-tooling.toml`` at or above the project folder; the first ``[[rules]]`` path that contains the
project folder; ``default_profile``. Nothing here is required: without the folder, every command behaves as before.
"""

from __future__ import annotations

import fnmatch
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_FILE = "profiles.toml"


class LocalConfigError(RuntimeError):
    pass


def config_dir() -> Path:
    return Path(os.environ.get("MEDIA_TOOLING_CONFIG_DIR", "~/.config/media-tooling")).expanduser()


def cache_dir() -> Path:
    return Path(os.environ.get("MEDIA_TOOLING_CACHE_DIR", "~/.cache/media-tooling")).expanduser()


def load_config(path: Path | None = None, *, required: bool = True) -> dict[str, Any]:
    """Read profiles.toml. With required=False a missing file means "no local configuration" (an empty config)."""
    path = path or config_dir() / CONFIG_FILE
    if not path.exists():
        if required:
            raise LocalConfigError(f"no local profiles at {path}; see `python -m media_tooling.local_config`")
        return {"profiles": {}}
    with path.open("rb") as fh:
        cfg = tomllib.load(fh)
    profiles = cfg.setdefault("profiles", {})
    for rule in cfg.get("rules") or []:
        if rule.get("profile") not in profiles:
            raise LocalConfigError(f"rule {rule!r} in {path} names an unknown profile")
    if cfg.get("default_profile") and cfg["default_profile"] not in profiles:
        raise LocalConfigError(f"default_profile {cfg['default_profile']!r} in {path} is not a profile")
    for name, prof in profiles.items():
        if prof.get("rules", "reference") not in ("reference", "embed"):
            raise LocalConfigError(f"profile {name!r}: rules must be 'reference' or 'embed'")
    return cfg


def _resolve_pattern(pattern: str) -> str:
    """Expand ~ and resolve symlinks in the pattern's fixed prefix (the part before any glob character)."""
    pat = str(Path(pattern).expanduser())
    cut = min((i for i, ch in enumerate(pat) if ch in "*?["), default=len(pat))
    prefix, rest = pat[:cut], pat[cut:]
    head, _, partial = prefix.rpartition("/")
    resolved = str(Path(head or "/").resolve())
    return f"{resolved.rstrip('/')}/{partial}{rest}" if head or partial else resolved


def match_path(path: Path, pattern: str) -> bool:
    pat = _resolve_pattern(pattern)
    target = str(path.resolve())
    if pat.endswith("/**"):
        base = pat[:-3]
        return target == base or target.startswith(base.rstrip("/") + "/")
    return fnmatch.fnmatch(target, pat)


def project_profile_pin(project_dir: Path) -> tuple[str, Path] | None:
    """`render_profile` / `profile` from the nearest media-tooling.toml at or above the project folder."""
    for folder in (project_dir, *project_dir.parents):
        cand = folder / "media-tooling.toml"
        if cand.exists():
            with cand.open("rb") as fh:
                data = tomllib.load(fh)
            pin = data.get("render_profile") or data.get("profile")
            if pin:
                return str(pin), cand
    return None


@dataclass
class Resolved:
    name: str
    profile: dict[str, Any]
    reason: str


def resolve_profile(project_dir: Path | None, cfg: dict[str, Any], cli_profile: str | None = None,
                    *, required: bool = True) -> Resolved | None:
    profiles = cfg.get("profiles") or {}

    def pick(name: str, reason: str) -> Resolved:
        if name not in profiles:
            raise LocalConfigError(f"unknown profile {name!r} ({reason}); known: {', '.join(sorted(profiles)) or 'none'}")
        return Resolved(name, profiles[name], reason)

    if cli_profile:
        return pick(cli_profile, "--profile")
    if project_dir is not None:
        project_dir = project_dir.resolve()
        pinned = project_profile_pin(project_dir)
        if pinned:
            return pick(pinned[0], f"profile pinned in {pinned[1]}")
        for rule in cfg.get("rules") or []:
            if match_path(project_dir, rule["path"]):
                return pick(rule["profile"], f"rule {rule['path']}")
    if cfg.get("default_profile"):
        return pick(cfg["default_profile"], "default_profile")
    if required:
        raise LocalConfigError("no profile applies; pass --profile, pin one in media-tooling.toml, or add a rule")
    return None


def profile_rules_file(name: str, profile: dict[str, Any]) -> Path:
    custom = profile.get("rules_file")
    return Path(custom).expanduser() if custom else config_dir() / "profiles" / name / "AGENTS.md"


def private_skills_dir(cfg: dict[str, Any] | None = None) -> Path:
    custom = (cfg or {}).get("skills_dir")
    return Path(custom).expanduser() if custom else config_dir() / "skills"


def private_skill_names(skills_dir: Path) -> list[str]:
    if not skills_dir.is_dir():
        return []
    return sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file())


if __name__ == "__main__":
    print(__doc__)
