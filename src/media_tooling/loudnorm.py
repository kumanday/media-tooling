from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

# Social-media standard: -14 LUFS integrated, -1 dBTP peak, LRA 11 LU.
# Matches YouTube / Instagram / TikTok / X / LinkedIn normalization targets.
LOUDNORM_I = -14.0
LOUDNORM_TP = -1.0
LOUDNORM_LRA = 11.0

# Output extension -> (audio encoder args, container holds video).
# The encoder must match the container: ffmpeg will happily mux AAC into a
# .wav file, which produces a stream most decoders reject.
OUTPUT_FORMATS: dict[str, tuple[list[str], bool]] = {
    ".wav": (["-c:a", "pcm_s24le"], False),
    ".flac": (["-c:a", "flac"], False),
    ".mp3": (["-c:a", "libmp3lame", "-b:a", "192k"], False),
    ".m4a": (["-c:a", "aac", "-b:a", "192k"], False),
    ".mp4": (["-c:a", "aac", "-b:a", "192k"], True),
    ".mov": (["-c:a", "aac", "-b:a", "192k"], True),
    ".mkv": (["-c:a", "aac", "-b:a", "192k"], True),
}


def has_video_stream(
    input_path: Path,
    ffprobe_bin: str = "ffprobe",
) -> bool:
    """Return True if input_path contains at least one video stream.

    Raises RuntimeError if ffprobe itself fails (bad binary path, corrupt
    input, permission error), so the caller does not silently treat a probe
    failure as "no video".
    """
    cmd = [
        ffprobe_bin, "-v", "error",
        "-select_streams", "v",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(input_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffprobe failed (exit {proc.returncode}): {proc.stderr.strip()}"
        )
    return bool(proc.stdout.strip())


def validate_output_path(output_path: Path) -> None:
    """Raise ValueError if output_path has an extension loudnorm cannot write."""
    if output_path.suffix.lower() not in OUTPUT_FORMATS:
        supported = ", ".join(OUTPUT_FORMATS)
        raise ValueError(
            f"unsupported output extension {output_path.suffix or '(none)'!r} "
            f"for {output_path.name}; supported: {supported}"
        )


def build_encode_args(
    input_path: Path,
    output_path: Path,
    filter_str: str,
    ffprobe_bin: str = "ffprobe",
) -> list[str]:
    """Return the stream mapping, filter, and codec args for the encode pass.

    The audio codec follows the output extension. Video is stream-copied only
    when the input has video and the output container can hold it.
    """
    validate_output_path(output_path)
    audio_args, holds_video = OUTPUT_FORMATS[output_path.suffix.lower()]
    args: list[str] = []
    if holds_video and has_video_stream(input_path, ffprobe_bin=ffprobe_bin):
        args.extend(["-c:v", "copy"])
    else:
        args.append("-vn")
    args.extend(["-af", filter_str, *audio_args, "-ar", "48000"])
    if output_path.suffix.lower() == ".mp4":
        args.extend(["-movflags", "+faststart"])
    return args


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply two-pass ffmpeg loudnorm targeting -14 LUFS / -1 dBTP / LRA 11.",
    )
    parser.add_argument(
        "input",
        help="Path to the input audio or video file.",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Path for the normalized output file.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Use single-pass approximation (faster, less precise).",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg binary. Default: ffmpeg.",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default="ffprobe",
        help="Path to ffprobe binary. Default: ffprobe.",
    )
    return parser.parse_args()


def measure_loudness(
    input_path: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> dict[str, str] | None:
    """Run ffmpeg loudnorm first pass and parse the JSON measurement.

    Returns a dict with input_i, input_tp, input_lra, input_thresh,
    target_offset, or None if measurement failed.
    """
    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        ":print_format=json"
    )
    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
        "-af", filter_str,
        "-vn", "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(f"ffmpeg loudnorm measurement failed: {proc.stderr.strip()}", file=sys.stderr)
        return None
    stderr = proc.stderr

    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        data = json.loads(stderr[start : end + 1])
    except json.JSONDecodeError:
        return None

    needed = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    if not needed.issubset(data.keys()):
        return None
    return data


def apply_loudnorm_two_pass(
    input_path: Path,
    output_path: Path,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> bool:
    """Run two-pass loudnorm on input_path, write normalized copy to output_path.

    Returns True on success, False if measurement failed (caller should fall
    back to preview mode). Raises ValueError for unsupported output extensions.
    """
    validate_output_path(output_path)
    measurement = measure_loudness(input_path, ffmpeg_bin=ffmpeg_bin)
    if measurement is None:
        return False

    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        f":measured_I={measurement['input_i']}"
        f":measured_TP={measurement['input_tp']}"
        f":measured_LRA={measurement['input_lra']}"
        f":measured_thresh={measurement['input_thresh']}"
        f":offset={measurement['target_offset']}"
        ":linear=true"
    )
    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
    ]
    cmd.extend(build_encode_args(
        input_path, output_path, filter_str, ffprobe_bin=ffprobe_bin,
    ))
    cmd.append(str(output_path))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return True


def apply_loudnorm_preview(
    input_path: Path,
    output_path: Path,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> None:
    """Run single-pass loudnorm approximation (faster, less precise)."""
    filter_str = (
        f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
    )
    cmd = [
        ffmpeg_bin, "-y", "-hide_banner", "-nostats",
        "-i", str(input_path),
    ]
    cmd.extend(build_encode_args(
        input_path, output_path, filter_str, ffprobe_bin=ffprobe_bin,
    ))
    cmd.append(str(output_path))
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = Path(args.output).expanduser().resolve()
    try:
        validate_output_path(output_path)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg_bin = args.ffmpeg_bin
    ffprobe_bin = args.ffprobe_bin

    try:
        if args.preview:
            print(f"loudnorm (1-pass preview): {input_path.name} → {output_path.name}")
            apply_loudnorm_preview(
                input_path, output_path,
                ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
            )
        else:
            print(f"loudnorm pass 1 (measuring): {input_path.name}")
            success = apply_loudnorm_two_pass(
                input_path, output_path,
                ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
            )
            if not success:
                print("Measurement failed — falling back to 1-pass preview", file=sys.stderr)
                apply_loudnorm_preview(
                    input_path, output_path,
                    ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
                )
            else:
                print(f"loudnorm pass 2 (normalizing): → {output_path.name}")
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed: {exc.stderr}", file=sys.stderr)
        return 1
    except RuntimeError as exc:
        print(f"probe error: {exc}", file=sys.stderr)
        return 1

    print(f"Output: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
