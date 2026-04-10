from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from media_tooling.subtitle import build_srt, collapse_whitespace, write_text

TRANSLATION_WINDOW_TARGET_DURATION_SECONDS = 12.0
TRANSLATION_WINDOW_MAX_DURATION_SECONDS = 18.0
TRANSLATION_WINDOW_MAX_CUES = 6
TRANSLATION_WINDOW_MIN_SENTENCE_DURATION_SECONDS = 6.0
TRANSLATION_MIN_CUE_DURATION_SECONDS = 1.0
TRANSLATION_MAX_CHARACTERS_SPACED = 84
TRANSLATION_MAX_CHARACTERS_UNSPACED = 24
HARD_SENTENCE_PUNCTUATION = ".!?。！？"
SOFT_SENTENCE_PUNCTUATION = ";:;,，、"
TRAILING_CLOSERS = "\"')]}”’"


@dataclass(frozen=True)
class SubtitleCue:
    index: int
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class TranslationWindow:
    id: int
    start: float
    end: float
    source_text: str
    source_cue_indices: list[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create translation templates for subtitles and apply translated windows back "
            "into re-segmented target-language SRT output."
        )
    )
    parser.add_argument("input_srt", help="Path to the source .srt file.")
    parser.add_argument(
        "--source-language",
        default="English",
        help="Human-readable source language label. Default: English.",
    )
    parser.add_argument(
        "--target-language",
        required=True,
        help="Human-readable target language label such as Spanish or pt-BR.",
    )
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--template-out",
        help="Write a translation template JSON file and exit.",
    )
    mode_group.add_argument(
        "--translations-in",
        help="Read a filled translation template JSON file and render translated subtitles.",
    )
    parser.add_argument(
        "--srt-out",
        help="Output path for translated subtitle .srt. Required with --translations-in.",
    )
    parser.add_argument(
        "--json-out",
        help="Optional output path for translated subtitle metadata JSON.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input_srt).expanduser().resolve()
    if not input_path.exists():
        print(f"Input subtitle file not found: {input_path}")
        return 1

    if args.translations_in and not args.srt_out:
        print("--srt-out is required when --translations-in is used.")
        return 1

    try:
        source_cues = parse_srt_file(input_path)
        windows = build_translation_windows(source_cues)

        if args.template_out:
            template_path = Path(args.template_out).expanduser().resolve()
            payload = build_translation_template_payload(
                source_srt=input_path,
                source_language=args.source_language,
                target_language=args.target_language,
                windows=windows,
            )
            write_text(template_path, json.dumps(payload, indent=2), args.overwrite)
            print(f"Translation template: {template_path}")
            return 0

        translations_path = Path(args.translations_in).expanduser().resolve()
        payload = json.loads(translations_path.read_text(encoding="utf-8"))
        translated_segments = build_translated_segments(
            source_srt=input_path,
            source_language=args.source_language,
            target_language=args.target_language,
            expected_windows=windows,
            payload=payload,
        )

        srt_path = Path(args.srt_out).expanduser().resolve()
        write_text(srt_path, build_srt(translated_segments), args.overwrite)
        print(f"Translated subtitles: {srt_path}")

        if args.json_out:
            json_path = Path(args.json_out).expanduser().resolve()
            metadata = {
                "source_srt": str(input_path),
                "source_language": args.source_language,
                "target_language": args.target_language,
                "window_count": len(windows),
                "segment_count": len(translated_segments),
                "segments": translated_segments,
            }
            write_text(json_path, json.dumps(metadata, indent=2), args.overwrite)
            print(f"Translated metadata: {json_path}")
    except (ValueError, FileExistsError, json.JSONDecodeError) as exc:
        print(str(exc))
        return 1

    return 0


def parse_srt_file(path: Path) -> list[SubtitleCue]:
    blocks = re.split(r"\n\s*\n", path.read_text(encoding="utf-8").strip())
    cues: list[SubtitleCue] = []
    for block in blocks:
        lines = [line.rstrip() for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            raise ValueError(f"Invalid SRT block in {path}: {block!r}")

        try:
            index = int(lines[0].strip())
        except ValueError as exc:
            raise ValueError(f"Invalid SRT cue index in {path}: {lines[0]!r}") from exc

        timing_parts = re.split(r"\s*-->\s*", lines[1])
        if len(timing_parts) != 2:
            raise ValueError(f"Invalid SRT timing line in {path}: {lines[1]!r}")

        text = collapse_whitespace(" ".join(lines[2:]))
        cues.append(
            SubtitleCue(
                index=index,
                start=parse_srt_timestamp(timing_parts[0]),
                end=parse_srt_timestamp(timing_parts[1]),
                text=text,
            )
        )
    return cues


def parse_srt_timestamp(value: str) -> float:
    match = re.fullmatch(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", value.strip())
    if match is None:
        raise ValueError(f"Invalid SRT timestamp: {value!r}")

    hours, minutes, seconds, milliseconds = (int(group) for group in match.groups())
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def build_translation_windows(cues: list[SubtitleCue]) -> list[TranslationWindow]:
    windows: list[TranslationWindow] = []
    current: list[SubtitleCue] = []

    for cue in cues:
        current.append(cue)
        current_text = collapse_whitespace(" ".join(item.text for item in current))
        current_duration = current[-1].end - current[0].start

        if should_close_translation_window(current, current_text, current_duration):
            windows.append(make_translation_window(len(windows) + 1, current))
            current = []

    if current:
        windows.append(make_translation_window(len(windows) + 1, current))

    return windows


def should_close_translation_window(
    cues: list[SubtitleCue], combined_text: str, duration: float
) -> bool:
    if duration >= TRANSLATION_WINDOW_MAX_DURATION_SECONDS:
        return True
    if len(cues) >= TRANSLATION_WINDOW_MAX_CUES:
        return True
    if duration < TRANSLATION_WINDOW_MIN_SENTENCE_DURATION_SECONDS:
        return False
    if ends_with_sentence_boundary(combined_text):
        return True
    return duration >= TRANSLATION_WINDOW_TARGET_DURATION_SECONDS


def ends_with_sentence_boundary(text: str) -> bool:
    stripped = text.rstrip().rstrip(TRAILING_CLOSERS)
    return bool(stripped) and stripped[-1] in HARD_SENTENCE_PUNCTUATION


def make_translation_window(window_id: int, cues: list[SubtitleCue]) -> TranslationWindow:
    return TranslationWindow(
        id=window_id,
        start=round(cues[0].start, 3),
        end=round(cues[-1].end, 3),
        source_text=collapse_whitespace(" ".join(cue.text for cue in cues)),
        source_cue_indices=[cue.index for cue in cues],
    )


def build_translation_template_payload(
    *,
    source_srt: Path,
    source_language: str,
    target_language: str,
    windows: list[TranslationWindow],
) -> dict[str, Any]:
    return {
        "source_srt": str(source_srt),
        "source_language": source_language,
        "target_language": target_language,
        "strategy": {
            "window_target_duration_seconds": TRANSLATION_WINDOW_TARGET_DURATION_SECONDS,
            "window_max_duration_seconds": TRANSLATION_WINDOW_MAX_DURATION_SECONDS,
            "window_max_cues": TRANSLATION_WINDOW_MAX_CUES,
            "notes": [
                "Translate each window semantically rather than cue-by-cue.",
                "Keep translated_text natural in the target language.",
                "Do not preserve the source cue boundaries inside translated_text.",
            ],
        },
        "window_count": len(windows),
        "windows": [
            {
                **asdict(window),
                "translated_text": "",
            }
            for window in windows
        ],
    }


def build_translated_segments(
    *,
    source_srt: Path,
    source_language: str,
    target_language: str,
    expected_windows: list[TranslationWindow],
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    validate_translation_payload(
        source_srt=source_srt,
        source_language=source_language,
        target_language=target_language,
        expected_windows=expected_windows,
        payload=payload,
    )

    translated_segments: list[dict[str, Any]] = []
    windows = payload["windows"]
    for window_payload in windows:
        translated_text = collapse_whitespace(str(window_payload.get("translated_text", "")))
        if not translated_text:
            raise ValueError(
                f"Window {window_payload['id']} is missing translated_text in {payload.get('source_srt', 'translation payload')}."
            )

        translated_segments.extend(
            resegment_translated_window(
                start=float(window_payload["start"]),
                end=float(window_payload["end"]),
                translated_text=translated_text,
            )
        )

    return translated_segments


def validate_translation_payload(
    *,
    source_srt: Path,
    source_language: str,
    target_language: str,
    expected_windows: list[TranslationWindow],
    payload: dict[str, Any],
) -> None:
    if payload.get("source_language") != source_language:
        raise ValueError(
            f"Translation payload source_language {payload.get('source_language')!r} does not match {source_language!r}."
        )
    if payload.get("target_language") != target_language:
        raise ValueError(
            f"Translation payload target_language {payload.get('target_language')!r} does not match {target_language!r}."
        )

    windows = payload.get("windows")
    if not isinstance(windows, list):
        raise ValueError("Translation payload is missing a valid windows list.")
    if len(windows) != len(expected_windows):
        raise ValueError(
            f"Translation payload window count {len(windows)} does not match expected {len(expected_windows)} for {source_srt}."
        )

    for expected, actual in zip(expected_windows, windows, strict=True):
        actual_source_text = collapse_whitespace(str(actual.get("source_text", "")))
        if actual.get("id") != expected.id:
            raise ValueError(f"Translation window id mismatch: expected {expected.id}, got {actual.get('id')}.")
        if round(float(actual.get("start", -1.0)), 3) != expected.start:
            raise ValueError(f"Translation window {expected.id} start mismatch.")
        if round(float(actual.get("end", -1.0)), 3) != expected.end:
            raise ValueError(f"Translation window {expected.id} end mismatch.")
        if actual_source_text != expected.source_text:
            raise ValueError(
                f"Translation window {expected.id} source_text does not match the current source subtitles."
            )


def resegment_translated_window(
    *, start: float, end: float, translated_text: str
) -> list[dict[str, Any]]:
    normalized_text = collapse_whitespace(translated_text)
    if not normalized_text:
        return []

    blocks = split_translated_text_into_blocks(normalized_text)
    blocks = merge_blocks_for_minimum_duration(blocks, end - start)
    return allocate_window_timings(start=start, end=end, blocks=blocks)


def split_translated_text_into_blocks(text: str) -> list[str]:
    clauses = split_text_into_clauses(text)
    blocks: list[str] = []
    for clause in clauses:
        blocks.extend(wrap_translation_clause(clause))
    return [block for block in blocks if block]


def split_text_into_clauses(text: str) -> list[str]:
    clauses: list[str] = []
    buffer = []
    for character in text:
        buffer.append(character)
        current = "".join(buffer)
        if character in HARD_SENTENCE_PUNCTUATION:
            clauses.append(collapse_whitespace(current))
            buffer = []
        elif character in SOFT_SENTENCE_PUNCTUATION and len(collapse_whitespace(current)) >= 24:
            clauses.append(collapse_whitespace(current))
            buffer = []

    tail = collapse_whitespace("".join(buffer))
    if tail:
        clauses.append(tail)
    return clauses or [text]


def wrap_translation_clause(clause: str) -> list[str]:
    max_characters = (
        TRANSLATION_MAX_CHARACTERS_SPACED
        if text_uses_spaces(clause)
        else TRANSLATION_MAX_CHARACTERS_UNSPACED
    )

    if len(clause) <= max_characters:
        return [clause]
    if not text_uses_spaces(clause):
        return [
            clause[index : index + max_characters]
            for index in range(0, len(clause), max_characters)
        ]

    words = clause.split()
    blocks: list[str] = []
    current_words: list[str] = []
    for word in words:
        candidate = " ".join([*current_words, word])
        if current_words and len(candidate) > max_characters:
            blocks.append(" ".join(current_words))
            current_words = [word]
        else:
            current_words.append(word)

    if current_words:
        blocks.append(" ".join(current_words))
    return blocks


def text_uses_spaces(text: str) -> bool:
    return bool(re.search(r"\s", text))


def merge_blocks_for_minimum_duration(blocks: list[str], duration: float) -> list[str]:
    merged = list(blocks)
    while len(merged) > 1:
        weights = [block_weight(block) for block in merged]
        total_weight = sum(weights)
        predicted = [duration * weight / total_weight for weight in weights]
        shortest_duration = min(predicted)
        if shortest_duration >= TRANSLATION_MIN_CUE_DURATION_SECONDS:
            break

        shortest_index = predicted.index(shortest_duration)
        if shortest_index == 0:
            merge_index = 0
        elif shortest_index == len(merged) - 1:
            merge_index = shortest_index - 1
        else:
            left_weight = weights[shortest_index - 1]
            right_weight = weights[shortest_index + 1]
            merge_index = shortest_index - 1 if left_weight <= right_weight else shortest_index

        merged[merge_index] = collapse_whitespace(
            f"{merged[merge_index]} {merged[merge_index + 1]}"
        )
        del merged[merge_index + 1]

    return merged


def block_weight(block: str) -> int:
    compact = re.sub(r"\s+", "", block)
    return max(len(compact), 1)


def allocate_window_timings(*, start: float, end: float, blocks: list[str]) -> list[dict[str, Any]]:
    if len(blocks) == 1:
        return [{"start": round(start, 3), "end": round(end, 3), "text": blocks[0]}]

    total_duration = max(end - start, 0.0)
    weights = [block_weight(block) for block in blocks]
    total_weight = sum(weights)

    segments: list[dict[str, Any]] = []
    cursor = start
    for index, (block, weight) in enumerate(zip(blocks, weights, strict=True)):
        if index == len(blocks) - 1:
            segment_end = end
        else:
            segment_duration = total_duration * weight / total_weight
            segment_end = cursor + segment_duration
        segments.append(
            {
                "start": round(cursor, 3),
                "end": round(segment_end, 3),
                "text": block,
            }
        )
        cursor = segment_end

    return segments


if __name__ == "__main__":
    raise SystemExit(main())
