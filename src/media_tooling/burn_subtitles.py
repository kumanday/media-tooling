from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SUBTITLE_FILTER_KEYWORDS = ("subtitles=", "ass=")
OVERLAY_FILTER_KEYWORDS = ("overlay=", "setpts=")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Burn SRT subtitles into video with customizable styles."
    )
    parser.add_argument(
        "--input",
        required=True,
        help="Path to the input video file.",
    )
    parser.add_argument(
        "--srt",
        required=True,
        help="Path to the SRT subtitle file to burn.",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path for the output video file with burned subtitles.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Override ffmpeg binary path.",
    )
    parser.add_argument(
        "--style",
        default="bold-overlay",
        choices=["bold-overlay", "natural-sentence"],
        help="Subtitle style preset. Default: bold-overlay.",
    )
    parser.add_argument(
        "--extra-filters",
        default=None,
        help=(
            "Additional ffmpeg filter(s) to apply BEFORE subtitles. "
            "Never place filters after subtitles in the chain (Hard Rule 1)."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    srt_path = Path(args.srt).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        print(f"Input video not found: {input_path}", file=sys.stderr)
        return 1
    if not srt_path.exists():
        print(f"SRT file not found: {srt_path}", file=sys.stderr)
        return 1

    try:
        filter_chain = build_filter_chain(
            srt_path=srt_path,
            style=args.style,
            extra_filters=args.extra_filters,
        )
        burn_subtitles(
            input_path=input_path,
            output_path=output_path,
            filter_chain=filter_chain,
            ffmpeg_bin=args.ffmpeg_bin,
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Burned subtitles: {output_path}")
    return 0


def build_filter_chain(
    *,
    srt_path: Path,
    style: str,
    extra_filters: str | None,
) -> str:
    """Build the ffmpeg -vf filter chain with the subtitles filter LAST.

    Hard Rule 1: Subtitles must be the last filter in the chain.
    If a user supplies extra filters, they are prepended before subtitles.

    Raises ValueError if the filter chain would place subtitles before
    another filter (violating Hard Rule 1).
    """
    subtitle_filter = _build_subtitle_filter(srt_path=srt_path, style=style)

    parts: list[str] = []
    if extra_filters:
        validate_subtitles_last(extra_filters, context="extra-filters")
        parts.append(extra_filters)

    parts.append(subtitle_filter)
    return ",".join(parts)


def _build_subtitle_filter(*, srt_path: Path, style: str) -> str:
    """Return the ffmpeg subtitles filter string for the given style."""
    escaped_path = str(srt_path).replace("'", "'\\''").replace(":", "\\:")
    if style == "natural-sentence":
        return (
            f"subtitles='{escaped_path}'"
            ":force_style='FontSize=22,PrimaryColour=&H00FFFFFF,"
            "OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=45'"
        )
    # bold-overlay (default): 2-word UPPERCASE chunks, white-on-black-outline
    return (
        f"subtitles='{escaped_path}'"
        ":force_style='FontWeight=900,FontSize=28,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BorderStyle=1,Outline=2,MarginV=35'"
    )


def validate_subtitles_last(filter_string: str, context: str = "filter") -> None:
    """Validate that no subtitle or overlay filter appears before the end of chain.

    Hard Rule 1 requires subtitles to be applied last. This guardrail inspects
    a filter string and raises ValueError if it contains a subtitle/overlay
    filter anywhere in it (since any such filter in user-supplied extras would
    necessarily come before the subtitles filter we append).

    Raises ValueError with a descriptive message referencing Hard Rule 1.
    """
    found_subtitle = None
    found_overlay = None

    for keyword in SUBTITLE_FILTER_KEYWORDS:
        if keyword in filter_string:
            found_subtitle = keyword
            break

    for keyword in OVERLAY_FILTER_KEYWORDS:
        if keyword in filter_string:
            found_overlay = keyword
            break

    if found_subtitle:
        raise ValueError(
            f"Hard Rule 1 violation: subtitles filter '{found_subtitle}' found in "
            f"{context}. Subtitles must always be the LAST filter in the chain. "
            "Remove the subtitle filter from extra-filters; it is applied "
            "automatically at the end."
        )

    if found_overlay:
        raise ValueError(
            f"Hard Rule 1 violation: overlay filter '{found_overlay}' found in "
            f"{context}. Overlays must be composited BEFORE subtitles, but "
            "burn_subtitles does not support overlay compositing. Use the EDL "
            "renderer for overlay + subtitle workflows, or apply overlays in a "
            "separate pass before running burn-subtitles."
        )


def burn_subtitles(
    *,
    input_path: Path,
    output_path: Path,
    filter_chain: str,
    ffmpeg_bin: str,
) -> None:
    """Execute ffmpeg to burn subtitles into video."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = [
        ffmpeg_bin,
        "-y",
        "-i",
        str(input_path),
        "-vf",
        filter_chain,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
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
            f"ffmpeg burn-subtitles failed:\n{' '.join(command)}\n\n"
            f"{completed.stderr.strip()}"
        )


if __name__ == "__main__":
    raise SystemExit(main())