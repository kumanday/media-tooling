from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a lightweight contact sheet from a video file."
    )
    parser.add_argument("input", help="Path to a video file.")
    parser.add_argument(
        "--output",
        default=None,
        help="Explicit output PNG path. Defaults to <stem>-contact-sheet.png beside the input.",
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
        help="Overwrite an existing output PNG.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip work if the output PNG already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_name(f"{input_path.stem}-contact-sheet.png")
    )

    if output_path.exists():
        if args.skip_existing:
            print(f"Skipping existing contact sheet for {input_path}")
            return 0
        if not args.overwrite:
            print(
                f"Output already exists: {output_path}. Use --overwrite or --skip-existing.",
                file=sys.stderr,
            )
            return 1

    try:
        generate_contact_sheet(
            input_path=input_path,
            output_path=output_path,
            columns=args.columns,
            rows=args.rows,
            width=args.width,
            ffmpeg_bin=args.ffmpeg_bin,
            ffprobe_bin=args.ffprobe_bin,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Contact sheet: {output_path}")
    return 0


def generate_contact_sheet(
    *,
    input_path: Path,
    output_path: Path,
    columns: int,
    rows: int,
    width: int,
    ffmpeg_bin: str,
    ffprobe_bin: str,
) -> None:
    if columns <= 0 or rows <= 0:
        raise ValueError("columns and rows must both be positive integers")
    if width <= 0:
        raise ValueError("width must be a positive integer")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration = probe_duration(input_path, ffprobe_bin)
    frame_count = columns * rows
    fps_value = frame_count / duration if duration > 0 else 1
    video_filter = f"fps={fps_value:.8f},scale={width}:-1,tile={columns}x{rows}"

    command = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        video_filter,
        "-frames:v",
        "1",
        str(output_path),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed for {input_path}:\n{completed.stderr.strip()}"
        )


def probe_duration(input_path: Path, ffprobe_bin: str) -> float:
    command = [
        ffprobe_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(input_path),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed for {input_path}:\n{completed.stderr.strip()}"
        )
    payload = json.loads(completed.stdout)
    duration_value = payload.get("format", {}).get("duration")
    if duration_value is None:
        raise RuntimeError(f"Could not determine duration for {input_path}")
    return float(duration_value)


if __name__ == "__main__":
    raise SystemExit(main())
