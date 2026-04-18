"""Pack verbose transcript JSON into compact phrase-level markdown.

Converts the JSON metadata produced by ``media-subtitle`` into a compact
``takes_packed.md`` file that is LLM-consumable.  Words are grouped into
phrases on silence gaps ≥ 0.5 s or on speaker changes.  Each phrase line
is prefixed with ``[start-end]`` timestamps (seconds, 3 decimal places).

Usage::

    media-pack-transcript transcript.json -o takes_packed.md
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

SILENCE_THRESHOLD_DEFAULT = 0.5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pack verbose transcript JSON into compact phrase-level markdown.",
    )
    parser.add_argument("input", help="Path to a .json transcript metadata file.")
    parser.add_argument("-o", "--output", default=None, help="Output markdown path.")
    parser.add_argument(
        "--silence-threshold",
        type=float,
        default=SILENCE_THRESHOLD_DEFAULT,
        help=f"Break phrases on silences >= this many seconds. Default: {SILENCE_THRESHOLD_DEFAULT}.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = _resolve_output_path(input_path, args.output)

    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"Failed to read {input_path}: {exc}", file=sys.stderr)
        return 1

    segments = payload.get("segments", [])
    words = extract_words(segments)
    phrases = group_into_phrases(words, silence_threshold=args.silence_threshold)
    markdown = render_markdown(phrases, silence_threshold=args.silence_threshold)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    print(f"Packed {len(phrases)} phrases → {output_path}")
    return 0


def _resolve_output_path(input_path: Path, output: str | None) -> Path:
    if output:
        return Path(output).expanduser().resolve()
    return input_path.with_name("takes_packed.md")


def extract_words(segments: list[Any]) -> list[dict[str, Any]]:
    """Flatten word-level entries from all segments.

    Handles both dict-based segments (faster-whisper) and object-based
    segments (MLX).  Words are normalised to ``{word, start, end,
    speaker}`` dicts; the ``speaker`` field defaults to ``None`` when
    absent.
    """
    words: list[dict[str, Any]] = []
    for segment in segments:
        raw_words: list[Any]
        if isinstance(segment, dict):
            raw_words = segment.get("words", [])
        else:
            raw_words = getattr(segment, "words", None) or []

        for w in raw_words:
            if isinstance(w, dict):
                text = str(w.get("word", ""))
                start = w.get("start")
                end = w.get("end")
                speaker = w.get("speaker")
            else:
                text = str(getattr(w, "word", ""))
                start = getattr(w, "start", None)
                end = getattr(w, "end", None)
                speaker = getattr(w, "speaker", None)

            if start is None or end is None:
                continue

            words.append(
                {
                    "word": text,
                    "start": float(start),
                    "end": float(end),
                    "speaker": speaker,
                },
            )
    return words


def group_into_phrases(
    words: list[dict[str, Any]],
    silence_threshold: float = SILENCE_THRESHOLD_DEFAULT,
) -> list[dict[str, Any]]:
    """Group words into phrases on silence ≥ *silence_threshold* or speaker change.

    Returns a list of ``{start, end, text, speaker}`` dicts.
    """
    if not words:
        return []

    phrases: list[dict[str, Any]] = []
    current_words: list[dict[str, Any]] = []
    current_speaker: Any = None
    prev_end: float | None = None

    def flush() -> None:
        nonlocal current_words, current_speaker, prev_end
        if not current_words:
            return
        text = _join_phrase_words(current_words)
        if not text:
            current_words = []
            current_speaker = None
            prev_end = None
            return
        phrases.append(
            {
                "start": current_words[0]["start"],
                "end": current_words[-1]["end"],
                "text": text,
                "speaker": current_speaker,
            },
        )
        current_words = []
        current_speaker = None
        prev_end = None

    for w in words:
        start = w["start"]
        end = w["end"]
        speaker = w.get("speaker")

        # Flush on speaker change
        if current_words and current_speaker is not None and speaker is not None and speaker != current_speaker:
            flush()

        # Flush on silence gap
        if prev_end is not None and start - prev_end >= silence_threshold:
            flush()

        if not current_words:
            current_speaker = speaker
        elif current_speaker is None and speaker is not None:
            current_speaker = speaker
        current_words.append(w)
        prev_end = end

    flush()
    return phrases


def _join_phrase_words(words: list[dict[str, Any]]) -> str:
    """Join word entries into a single phrase string."""
    parts: list[str] = []
    for w in words:
        token = w["word"]
        # Words may already include leading spaces (faster-whisper style)
        # or may not (MLX style).  Strip and re-join for consistency.
        stripped = token.strip()
        if stripped:
            parts.append(stripped)
    text = " ".join(parts)
    # Clean up punctuation spacing
    for ch in ",.?!;:":
        text = text.replace(f" {ch}", ch)
    return text


def render_markdown(
    phrases: list[dict[str, Any]],
    silence_threshold: float = SILENCE_THRESHOLD_DEFAULT,
) -> str:
    """Render *phrases* into a compact markdown string."""
    lines: list[str] = [
        "# Packed transcript",
        "",
        f"Phrase-level, grouped on silences ≥ {silence_threshold:.1f}s or speaker change.",
        "Use `[start-end]` ranges to address cuts in the EDL.",
        "",
    ]

    if not phrases:
        lines.append("_no speech detected_")
        lines.append("")
        return "\n".join(lines)

    for p in phrases:
        start_ts = f"{p['start']:.3f}"
        end_ts = f"{p['end']:.3f}"
        speaker = p.get("speaker")
        spk_tag = ""
        if speaker is not None:
            spk_str = str(speaker)
            if spk_str.startswith("speaker_"):
                spk_str = spk_str[len("speaker_"):]
            spk_tag = f" S{spk_str}"
        lines.append(f"[{start_ts}-{end_ts}]{spk_tag} {p['text']}")

    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
