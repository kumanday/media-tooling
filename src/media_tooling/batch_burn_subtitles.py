from __future__ import annotations

import argparse
from pathlib import Path

from media_tooling.batch_utils import finish_batch, load_manifest_inputs
from media_tooling.burn_subtitles import burn_subtitles


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch burn SRT subtitles into video files from a manifest."
    )
    parser.add_argument(
        "--inputs-file",
        required=True,
        help="Text file with one video path per line.",
    )
    parser.add_argument(
        "--srt-dir",
        required=True,
        help="Directory containing SRT subtitle files (must match video stems).",
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Directory for output video files with burned subtitles.",
    )
    parser.add_argument(
        "--style",
        choices=["bold-overlay", "natural-sentence"],
        default="bold-overlay",
        help="Subtitle style preset. Default: bold-overlay.",
    )
    parser.add_argument(
        "--style-args",
        default=None,
        help=(
            "Custom ASS/SSA force_style string to override the preset style. "
            "Example: 'FontName=Arial,FontSize=24,PrimaryColour=&H00FFFF00'"
        ),
    )
    parser.add_argument(
        "--pre-filters",
        default=None,
        help=(
            "Additional ffmpeg video filters to apply BEFORE subtitles. "
            "Subtitles are always applied last (Hard Rule 1)."
        ),
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg.",
    )
    mutex = parser.add_mutually_exclusive_group()
    mutex.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    mutex.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files when the output video already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs_file = Path(args.inputs_file).expanduser().resolve()
    srt_dir = Path(args.srt_dir).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    items = load_manifest_inputs(inputs_file)
    print(f"Loaded {len(items)} input files from {inputs_file}")
    failures: list[str] = []

    for item in items:
        stem = item.stem
        srt_path = srt_dir / f"{stem}.srt"
        output_path = output_dir / f"{stem}-burned.mp4"

        if not srt_path.exists():
            failures.append(f"{item}: SRT not found at {srt_path}")
            print(f"FAILED: {item}\nSRT not found at {srt_path}")
            continue

        if output_path.exists():
            if args.skip_existing:
                print(f"Skipping existing burned subtitles for {item}")
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
            burn_subtitles(
                input_path=item,
                srt_path=srt_path,
                output_path=output_path,
                style=args.style,
                style_args=args.style_args,
                pre_filters=args.pre_filters,
                ffmpeg_bin=args.ffmpeg_bin,
                overwrite=args.overwrite,
            )
            print(f"Burned subtitles: {output_path}")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{item}: {exc}")
            print(f"FAILED: {item}\n{exc}")

    return finish_batch(failures)


if __name__ == "__main__":
    raise SystemExit(main())
