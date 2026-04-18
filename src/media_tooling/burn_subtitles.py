from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from media_tooling.subtitle import SUBTITLE_LONG_GAP_SECONDS, build_srt
from media_tooling.subtitle_translate import (
    HARD_SENTENCE_PUNCTUATION,
    SOFT_SENTENCE_PUNCTUATION,
    parse_srt_file,
)

# Guardrail keywords for Hard Rule 1 enforcement

SUBTITLE_FILTER_KEYWORDS = ("subtitles=", "ass=")
OVERLAY_FILTER_KEYWORDS = ("overlay=", "setpts=")

# Compiled patterns for filter-boundary matching (avoids false positives
# like "class=" or "bass=" matching the "ass=" keyword)
_SUBTITLE_FILTER_PATTERNS = tuple(
    re.compile(rf"(?:^|,){re.escape(kw)}") for kw in SUBTITLE_FILTER_KEYWORDS
)
_OVERLAY_FILTER_PATTERNS = tuple(
    re.compile(rf"(?:^|,){re.escape(kw)}") for kw in OVERLAY_FILTER_KEYWORDS
)

# ASS/SSA style constants

BOLD_OVERLAY_FORCE_STYLE = (
    "FontName=Helvetica,FontSize=18,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginV=35"
)

NATURAL_SENTENCE_FORCE_STYLE = (
    "FontName=Helvetica,FontSize=22,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H00000000,"
    "BorderStyle=1,Outline=2,Shadow=0,"
    "Alignment=2,MarginV=35"
)

# Combined punctuation set: hard + soft (includes CJK characters)
_PUNCT_BREAK = HARD_SENTENCE_PUNCTUATION + SOFT_SENTENCE_PUNCTUATION

# Chunking constants for bold-overlay style
BOLD_OVERLAY_WORDS_PER_CHUNK = 2

# Chunking constants for natural-sentence style
NATURAL_SENTENCE_MIN_WORDS = 4
NATURAL_SENTENCE_MAX_WORDS = 7


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Burn SRT subtitles into video with customizable styles."
    )
    parser.add_argument("input", help="Path to an input video file.")
    parser.add_argument(
        "--srt",
        required=True,
        help="Path to the SRT subtitle file to burn into the video.",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Path for the output video file with burned subtitles.",
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
        help="Path to ffmpeg. Default: ffmpeg.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output file.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip work if the output file already exists.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.overwrite and args.skip_existing:
        print(
            "Error: --overwrite and --skip-existing are mutually exclusive.",
            file=sys.stderr,
        )
        return 1

    input_path = Path(args.input).expanduser().resolve()
    srt_path = Path(args.srt).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()

    if not input_path.exists():
        print(f"Input video not found: {input_path}", file=sys.stderr)
        return 1

    if not srt_path.exists():
        print(f"Subtitle file not found: {srt_path}", file=sys.stderr)
        return 1

    if output_path.exists():
        if args.skip_existing:
            print(f"Skipping existing output: {output_path}")
            return 0
        if not args.overwrite:
            print(
                f"Output already exists: {output_path}. Use --overwrite or --skip-existing.",
                file=sys.stderr,
            )
            return 1

    try:
        burn_subtitles(
            input_path=input_path,
            srt_path=srt_path,
            output_path=output_path,
            style=args.style,
            style_args=args.style_args,
            pre_filters=args.pre_filters,
            ffmpeg_bin=args.ffmpeg_bin,
            overwrite=args.overwrite,
        )
    except (ValueError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Burned subtitles: {output_path}")
    return 0


def validate_subtitles_last(filter_string: str, context: str = "filter") -> None:
    """Validate that no subtitle or overlay filter appears before the end of chain.

    Hard Rule 1 requires subtitles to be applied last. This guardrail inspects
    a filter string and raises ValueError if it contains a subtitle/overlay
    filter anywhere in it (since any such filter in user-supplied extras would
    necessarily come before the subtitles filter we append).

    Uses filter-boundary matching (start-of-string or comma prefix) to avoid
    false positives like "class=" or "bass=" matching "ass=".

    Raises ValueError with a descriptive message referencing Hard Rule 1.
    """
    found_subtitle = None
    found_overlay = None

    for pattern, keyword in zip(_SUBTITLE_FILTER_PATTERNS, SUBTITLE_FILTER_KEYWORDS):
        if pattern.search(filter_string):
            found_subtitle = keyword
            break

    for pattern, keyword in zip(_OVERLAY_FILTER_PATTERNS, OVERLAY_FILTER_KEYWORDS):
        if pattern.search(filter_string):
            found_overlay = keyword
            break

    if found_subtitle:
        raise ValueError(
            f"Hard Rule 1 violation: subtitles filter '{found_subtitle}' found in "
            f"{context}. Subtitles must always be the LAST filter in the chain. "
            "Remove the subtitle filter from pre-filters; it is applied "
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
    srt_path: Path,
    output_path: Path,
    style: str = "bold-overlay",
    style_args: str | None = None,
    pre_filters: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
    overwrite: bool = False,
) -> None:
    """Burn SRT subtitles into video with customizable styles.

    Rechunks subtitles according to the chosen style, builds a filter chain
    with subtitles always LAST (Hard Rule 1), and runs ffmpeg.
    """
    cues = parse_srt_file(srt_path)
    if not cues:
        raise ValueError(f"No subtitle cues found in {srt_path}")

    if style == "bold-overlay":
        rechunked = rechunk_bold_overlay(cues)
        force_style = style_args or BOLD_OVERLAY_FORCE_STYLE
    elif style == "natural-sentence":
        rechunked = rechunk_natural_sentence(cues)
        force_style = style_args or NATURAL_SENTENCE_FORCE_STYLE
    else:
        raise ValueError(f"Unknown style: {style}")

    rechunked_srt = build_srt(rechunked)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".srt", delete=False, encoding="utf-8"
    ) as tmp_srt:
        tmp_srt.write(rechunked_srt)
        tmp_srt_path = Path(tmp_srt.name)

    try:
        video_filter = build_video_filter(
            srt_path=tmp_srt_path,
            force_style=force_style,
            pre_filters=pre_filters,
        )
        run_ffmpeg(
            input_path=input_path,
            output_path=output_path,
            video_filter=video_filter,
            ffmpeg_bin=ffmpeg_bin,
            overwrite=overwrite,
        )
    finally:
        tmp_srt_path.unlink(missing_ok=True)


def build_video_filter(
    *,
    srt_path: Path,
    force_style: str,
    pre_filters: str | None = None,
) -> str:
    """Build ffmpeg video filter string with subtitles always LAST.

    Hard Rule 1: Subtitles filter is always the last filter in the chain.
    If pre-filters are supplied, they are validated (must not contain subtitle
    or overlay filters) and prepended before the subtitles filter.
    """
    if pre_filters:
        validate_subtitles_last(pre_filters, context="pre-filters")

    # Escape path for ffmpeg subtitles filter
    subs_escaped = (
        str(srt_path.resolve())
        .replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("'", "\\'")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("%", "\\%")
        .replace(";", "\\;")
    )

    force_style_escaped = force_style.replace("'", "\\'")
    subtitles_filter = f"subtitles='{subs_escaped}':force_style='{force_style_escaped}'"

    if pre_filters:
        return f"{pre_filters},{subtitles_filter}"

    return subtitles_filter


def rechunk_bold_overlay(cues: list[Any]) -> list[dict[str, Any]]:
    """Re-chunk SRT cues into 2-word UPPERCASE chunks.

    Breaks on punctuation. Each original cue's timing is distributed
    evenly across its child chunks.
    """
    result: list[dict[str, Any]] = []
    for cue in cues:
        words = cue.text.split()
        if not words:
            continue

        chunks = _group_words_with_punctuation_breaks(
            words, BOLD_OVERLAY_WORDS_PER_CHUNK
        )

        timing = _distribute_timing(
            start=cue.start, end=cue.end, count=len(chunks)
        )

        for i, chunk_words in enumerate(chunks):
            text = " ".join(chunk_words).rstrip(SOFT_SENTENCE_PUNCTUATION)
            text = text.upper()
            result.append({"start": timing[i][0], "end": timing[i][1], "text": text})

    return result


def rechunk_natural_sentence(cues: list[Any]) -> list[dict[str, Any]]:
    """Re-chunk SRT cues into 4-7 word sentence-case chunks.

    Breaks on natural pauses (punctuation, long gaps between cues).
    """
    # Merge cues that are close together (no long gap) into continuous text
    merged_segments = _merge_cues_by_gap(cues)

    result: list[dict[str, Any]] = []
    for segment in merged_segments:
        words = segment["text"].split()
        if not words:
            continue

        chunks = _group_words_natural_sentence(words)
        timing = _distribute_timing(
            start=segment["start"], end=segment["end"], count=len(chunks)
        )

        for i, chunk_words in enumerate(chunks):
            text = " ".join(chunk_words)
            text = _sentence_case(text)
            result.append({"start": timing[i][0], "end": timing[i][1], "text": text})

    return result


def _merge_cues_by_gap(cues: list[Any]) -> list[dict[str, Any]]:
    """Merge adjacent cues that have no long gap between them."""
    if not cues:
        return []

    merged: list[dict[str, Any]] = []
    current_start = cues[0].start
    current_end = cues[0].end
    current_words: list[str] = []

    for i, cue in enumerate(cues):
        if i > 0:
            gap = cue.start - cues[i - 1].end
            if gap >= SUBTITLE_LONG_GAP_SECONDS:
                merged.append(
                    {
                        "start": current_start,
                        "end": current_end,
                        "text": " ".join(current_words),
                    }
                )
                current_start = cue.start
                current_words = []

        current_end = cue.end
        current_words.extend(cue.text.split())

    if current_words:
        merged.append(
            {
                "start": current_start,
                "end": current_end,
                "text": " ".join(current_words),
            }
        )

    return merged


def _group_words_with_punctuation_breaks(
    words: list[str], max_words: int
) -> list[list[str]]:
    """Group words into chunks of up to max_words, breaking on punctuation."""
    chunks: list[list[str]] = []
    current: list[str] = []

    for word in words:
        current.append(word)
        ends_with_punct = bool(word) and word[-1] in _PUNCT_BREAK
        if len(current) >= max_words or ends_with_punct:
            chunks.append(current)
            current = []

    if current:
        chunks.append(current)

    return chunks if chunks else [words]


def _group_words_natural_sentence(words: list[str]) -> list[list[str]]:
    """Group words into 4-7 word chunks, breaking on natural pauses.

    Hard sentence punctuation (.!?) always causes a break regardless of
    word count. Soft punctuation (;:,) causes a break only when we have
    at least NATURAL_SENTENCE_MIN_WORDS words accumulated.
    """
    chunks: list[list[str]] = []
    current: list[str] = []

    for word in words:
        current.append(word)
        word_count = len(current)
        ends_with_hard_punct = bool(word) and word[-1] in HARD_SENTENCE_PUNCTUATION
        ends_with_soft_punct = bool(word) and word[-1] in SOFT_SENTENCE_PUNCTUATION

        if word_count >= NATURAL_SENTENCE_MAX_WORDS:
            chunks.append(current)
            current = []
        elif ends_with_hard_punct:
            chunks.append(current)
            current = []
        elif word_count >= NATURAL_SENTENCE_MIN_WORDS and ends_with_soft_punct:
            chunks.append(current)
            current = []

    if current:
        # If remaining words are fewer than min, try to append to last chunk
        # only if the merged chunk would not exceed max words
        if (
            chunks
            and len(current) < NATURAL_SENTENCE_MIN_WORDS
            and len(chunks[-1]) + len(current) <= NATURAL_SENTENCE_MAX_WORDS
        ):
            chunks[-1].extend(current)
        else:
            chunks.append(current)

    return chunks if chunks else [words]


def _distribute_timing(
    *, start: float, end: float, count: int
) -> list[tuple[float, float]]:
    """Distribute a time range evenly across count segments."""
    if count <= 0:
        return []
    if count == 1:
        return [(start, end)]

    duration = max(end - start, 0.0)
    step = duration / count
    return [
        (round(start + i * step, 3), round(start + (i + 1) * step, 3))
        for i in range(count)
    ]


def _sentence_case(text: str) -> str:
    """Capitalize first letter, preserve rest."""
    if not text:
        return text
    return text[0].upper() + text[1:]


def run_ffmpeg(
    *,
    input_path: Path,
    output_path: Path,
    video_filter: str,
    ffmpeg_bin: str = "ffmpeg",
    overwrite: bool = False,
) -> None:
    """Run ffmpeg to burn subtitles into video."""
    command = [
        ffmpeg_bin,
    ]
    if overwrite:
        command.append("-y")
    command.extend([
        "-i",
        str(input_path),
        "-vf",
        video_filter,
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
    ])

    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed:\n{' '.join(command)}\n\n{completed.stderr.strip()}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
