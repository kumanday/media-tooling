from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path


def iter_manifest_inputs(path: Path) -> Iterator[Path]:
    """Yield media paths from a manifest, resolving relatives beside the manifest."""
    manifest_path = path.expanduser().resolve()
    base_dir = manifest_path.parent
    with manifest_path.open(encoding="utf-8") as manifest:
        for raw_line in manifest:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            item = Path(line).expanduser()
            if not item.is_absolute():
                item = base_dir / item
            yield item.resolve()


def load_manifest_inputs(path: Path) -> list[Path]:
    return list(iter_manifest_inputs(path))


def record_failure(failures: list[str], item: Path, message: str) -> None:
    failures.append(f"{item}: {message}")
    print(f"FAILED: {item}\n{message}")


def guard_existing_output(
    *,
    item: Path,
    output_path: Path,
    overwrite: bool,
    skip_existing: bool,
    failures: list[str],
    label: str,
) -> bool:
    """Return True when a batch item should be processed."""
    if not output_path.exists():
        return True

    if skip_existing:
        print(f"Skipping existing {label} for {item}")
        return False

    if overwrite:
        return True

    record_failure(
        failures,
        item,
        f"output exists at {output_path} (use --overwrite or --skip-existing)",
    )
    return False


def finish_batch(failures: list[str]) -> int:
    if failures:
        print("\nBatch completed with failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nBatch completed successfully.")
    return 0
