from __future__ import annotations

import argparse
from pathlib import Path

from media_tooling.contact_sheet import generate_contact_sheet


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate contact sheets sequentially for a manifest of video files."
    )
    parser.add_argument(
        "--inputs-file",
        required=True,
        help="Text file with one video path per line.",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for generated PNG contact sheets.",
    )
    parser.add_argument(
        "--columns",
        type=int,
        default=3,
        help="Number of columns in the tile grid. Default: 3.",
    )
    parser.add_argument(
        "--rows",
        type=int,
        default=2,
        help="Number of rows in the tile grid. Default: 2.",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=480,
        help="Per-frame output width before tiling. Default: 480.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg.",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default="ffprobe",
        help="Path to ffprobe.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files when the target PNG already exists.",
    )
    return parser.parse_args()


def iter_inputs(path: Path) -> list[Path]:
    items: list[Path] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(Path(line).expanduser().resolve())
    return items


def main() -> int:
    args = parse_args()
    inputs_file = Path(args.inputs_file).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    items = iter_inputs(inputs_file)
    print(f"Loaded {len(items)} input files from {inputs_file}")
    failures: list[str] = []

    for item in items:
        output_path = output_dir / f"{item.stem}-contact-sheet.png"
        if output_path.exists():
            if args.skip_existing:
                print(f"Skipping existing contact sheet for {item}")
                continue
            if not args.overwrite:
                failures.append(
                    f"{item}: output exists at {output_path} (use --overwrite or --skip-existing)"
                )
                print(
                    f"FAILED: {item}\noutput exists at {output_path} (use --overwrite or --skip-existing)"
                )
                continue

        print(f"\n=== {item.name} ===")
        try:
            generate_contact_sheet(
                input_path=item,
                output_path=output_path,
                columns=args.columns,
                rows=args.rows,
                width=args.width,
                ffmpeg_bin=args.ffmpeg_bin,
                ffprobe_bin=args.ffprobe_bin,
            )
            print(f"Contact sheet: {output_path}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{item}: {exc}")
            print(f"FAILED: {item}\n{exc}")

    if failures:
        print("\nBatch completed with failures:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("\nBatch completed successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
