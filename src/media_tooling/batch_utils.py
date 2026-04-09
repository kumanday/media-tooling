from __future__ import annotations

from pathlib import Path


def load_manifest_inputs(path: Path) -> list[Path]:
    items: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(Path(line).expanduser().resolve())
    return items


def finish_batch(failures: list[str]) -> int:
    if failures:
        print("\nBatch completed with failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nBatch completed successfully.")
    return 0
