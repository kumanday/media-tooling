from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

SINGLE_PASS_FILTERGRAPH_INDICATORS = (
    "-filter_complex",
    "-lavfi",
    "xfade",
    "acrossfade",
)
CONCAT_DEMUXER_FLAGS = ("-f", "concat")


class AssemblyMethodError(ValueError):
    """Raised when a single-pass filtergraph is detected instead of concat demuxer."""


def validate_concat_demuxer_usage(command: list[str]) -> None:
    """Validate that the ffmpeg command uses concat demuxer, not a single-pass filtergraph.

    Hard Rule 2: Per-segment extract + lossless concat (never single-pass filtergraph).
    A single-pass filtergraph processes all segments in one ffmpeg invocation,
    which is fragile, non-debuggable, and prevents per-segment processing.

    This guardrail inspects the command for indicators of single-pass filtergraph
    usage and raises AssemblyMethodError if detected.

    Only validates concat assembly commands (those containing -f concat).
    Does not validate segment extraction commands (which use -ss/-to per segment).
    """
    is_concat_command = False
    for i, arg in enumerate(command):
        if arg in CONCAT_DEMUXER_FLAGS and i + 1 < len(command):
            next_arg = command[i + 1]
            if next_arg == "concat" or (i > 0 and command[i - 1] == "-f" and next_arg == "concat"):
                is_concat_command = True
                break

    if not is_concat_command:
        return

    for indicator in SINGLE_PASS_FILTERGRAPH_INDICATORS:
        if indicator in command:
            raise AssemblyMethodError(
                f"Hard Rule 2 violation: single-pass filtergraph indicator "
                f"'{indicator}' detected in concat assembly command. "
                "Use per-segment extraction followed by lossless concat with the "
                "concat demuxer (-f concat -safe 0 -i <manifest>) instead of a "
                "single-pass filtergraph. See docs/hard-rules.md Rule 2."
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a rough cut from a JSON spec of cards, image holds, and clips."
    )
    parser.add_argument(
        "--spec",
        required=True,
        help="Path to a JSON rough-cut spec.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default=None,
        help="Override ffmpeg binary path.",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default=None,
        help="Override ffprobe binary path.",
    )
    parser.add_argument(
        "--font-file",
        default=None,
        help="Override font file used for placeholder cards.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    spec_path = Path(args.spec).expanduser().resolve()
    if not spec_path.exists():
        print(f"Spec file not found: {spec_path}", file=sys.stderr)
        return 1

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        build_rough_cut(
            spec=spec,
            ffmpeg_bin=args.ffmpeg_bin,
            ffprobe_bin=args.ffprobe_bin,
            font_file=args.font_file,
        )
    except (RuntimeError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    assembly_path = resolve_path(spec["assembly_path"])
    print(f"Assembly: {assembly_path}")
    return 0


def build_rough_cut(
    *,
    spec: dict[str, Any],
    ffmpeg_bin: str | None,
    ffprobe_bin: str | None,
    font_file: str | None,
) -> None:
    generated_clips_dir = resolve_path(spec["generated_clips_dir"])
    text_dir = resolve_path(spec["text_dir"])
    manifest_path = resolve_path(spec["manifest_path"])
    assembly_path = resolve_path(spec["assembly_path"])

    generated_clips_dir.mkdir(parents=True, exist_ok=True)
    text_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    assembly_path.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = ffmpeg_bin or spec.get("ffmpeg_bin", "ffmpeg")
    ffprobe = ffprobe_bin or spec.get("ffprobe_bin", "ffprobe")
    font = resolve_font_file(font_file or spec.get("font_file"))

    manifest_lines: list[str] = []
    for segment in spec.get("segments", []):
        name = segment["name"]
        output_path = generated_clips_dir / f"{name}.mp4"
        segment_type = segment["type"]
        if segment_type == "card":
            build_card_segment(
                segment=segment,
                output_path=output_path,
                text_dir=text_dir,
                ffmpeg_bin=ffmpeg,
                font_file=font,
            )
        elif segment_type == "image":
            build_image_segment(
                segment=segment,
                output_path=output_path,
                ffmpeg_bin=ffmpeg,
            )
        elif segment_type == "clip":
            build_clip_segment(
                segment=segment,
                output_path=output_path,
                ffmpeg_bin=ffmpeg,
                ffprobe_bin=ffprobe,
            )
        else:
            raise ValueError(f"Unsupported segment type: {segment_type}")

        manifest_lines.append(f"file {quote_concat_path(output_path)}")

    manifest_path.write_text("\n".join(manifest_lines) + "\n", encoding="utf-8")
    concat_manifest(
        manifest_path=manifest_path,
        output_path=assembly_path,
        ffmpeg_bin=ffmpeg,
    )


def build_card_segment(
    *,
    segment: dict[str, Any],
    output_path: Path,
    text_dir: Path,
    ffmpeg_bin: str,
    font_file: str,
) -> None:
    name = segment["name"]
    duration = str(segment["duration"])
    header = segment["header"]
    meta = segment.get("meta", "")
    body = segment.get("body", "")

    text_path = text_dir / f"{name}.txt"
    image_path = text_dir / f"{name}.png"
    text_path.write_text(
        compose_card_text(header=header, meta=meta, body=body),
        encoding="utf-8",
    )
    render_card_image(
        output_path=image_path,
        text=text_path.read_text(encoding="utf-8"),
        font_file=font_file,
    )

    run_command(
        [
            ffmpeg_bin,
            "-y",
            "-loop",
            "1",
            "-t",
            duration,
            "-i",
            str(image_path),
            "-f",
            "lavfi",
            "-t",
            duration,
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf",
            "fps=30,format=yuv420p",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            str(output_path),
        ]
    )


def build_image_segment(
    *,
    segment: dict[str, Any],
    output_path: Path,
    ffmpeg_bin: str,
) -> None:
    duration = str(segment["duration"])
    input_path = resolve_path(segment["input"])
    run_command(
        [
            ffmpeg_bin,
            "-y",
            "-loop",
            "1",
            "-t",
            duration,
            "-i",
            str(input_path),
            "-f",
            "lavfi",
            "-t",
            duration,
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-vf",
            (
                "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )


def build_clip_segment(
    *,
    segment: dict[str, Any],
    output_path: Path,
    ffmpeg_bin: str,
    ffprobe_bin: str,
) -> None:
    input_path = resolve_path(segment["input"])
    start = segment["start"]
    end = segment["end"]
    command = [
        ffmpeg_bin,
        "-y",
        "-ss",
        start,
        "-to",
        end,
        "-i",
        str(input_path),
    ]
    input_has_audio = has_audio(input_path=input_path, ffprobe_bin=ffprobe_bin)
    if not input_has_audio:
        command.extend(
            [
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
    command.extend(
        [
            "-vf",
            (
                "scale=1920:1080:force_original_aspect_ratio=decrease,"
                "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:black,fps=30"
            ),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
        ]
    )
    if not input_has_audio:
        command.append("-shortest")
    command.append(str(output_path))
    run_command(command)


def concat_manifest(
    *,
    manifest_path: Path,
    output_path: Path,
    ffmpeg_bin: str,
) -> None:
    command = [
        ffmpeg_bin,
        "-y",
        "-fflags",
        "+genpts",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(manifest_path),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    validate_concat_demuxer_usage(command)
    run_command(command)


def compose_card_text(*, header: str, meta: str, body: str) -> str:
    blocks = [header.strip()]
    if meta.strip():
        blocks.append(meta.strip())
    if body.strip():
        blocks.append(body.strip())
    return "\n\n".join(blocks) + "\n"


def render_card_image(*, output_path: Path, text: str, font_file: str) -> None:
    width = 1920
    height = 1080
    background = (0, 0, 0)
    foreground = (255, 255, 255)
    header_font = ImageFont.truetype(font_file, 60)
    body_font = ImageFont.truetype(font_file, 40)
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    max_text_width = int(width * 0.78)
    paragraph_gap = 28
    line_gap = 14

    def wrap_paragraph(paragraph: str, font: ImageFont.FreeTypeFont) -> list[str]:
        wrapped: list[str] = []
        for segment in paragraph.splitlines():
            words = segment.split()
            if not words:
                wrapped.append("")
                continue
            current = words[0]
            for word in words[1:]:
                candidate = f"{current} {word}"
                bbox = draw.textbbox((0, 0), candidate, font=font)
                if (bbox[2] - bbox[0]) <= max_text_width:
                    current = candidate
                else:
                    wrapped.append(current)
                    current = word
            wrapped.append(current)
        return wrapped or [""]

    def line_height(font: ImageFont.FreeTypeFont) -> int:
        bbox = draw.textbbox((0, 0), "Ag", font=font)
        return int(bbox[3] - bbox[1])

    paragraphs = [paragraph.strip() for paragraph in text.strip().split("\n\n") if paragraph.strip()]
    header = paragraphs[0] if paragraphs else ""
    body_paragraphs = paragraphs[1:] if len(paragraphs) > 1 else []

    blocks: list[tuple[list[str], ImageFont.FreeTypeFont]] = []
    if header:
        blocks.append((wrap_paragraph(header, header_font), header_font))
    for paragraph in body_paragraphs:
        blocks.append((wrap_paragraph(paragraph, body_font), body_font))

    total_height = 0
    for block_index, (lines, font) in enumerate(blocks):
        height_for_font = line_height(font)
        total_height += len(lines) * height_for_font
        total_height += max(0, len(lines) - 1) * line_gap
        if block_index < len(blocks) - 1:
            total_height += paragraph_gap

    y = (height - total_height) / 2
    for block_index, (lines, font) in enumerate(blocks):
        height_for_font = line_height(font)
        for line in lines:
            if line:
                bbox = draw.textbbox((0, 0), line, font=font)
                line_width = bbox[2] - bbox[0]
                x = (width - line_width) / 2
                draw.text((x, y), line, font=font, fill=foreground)
            y += height_for_font + line_gap
        y -= line_gap
        if block_index < len(blocks) - 1:
            y += paragraph_gap

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path)


def resolve_font_file(font_file: str | None) -> str:
    candidates: list[str] = []
    if font_file:
        candidates.append(font_file)

    candidates.extend(
        [
            "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ]
    )

    for candidate in candidates:
        expanded = Path(os.path.expandvars(candidate)).expanduser()
        if expanded.exists():
            return str(expanded.resolve())

    raise RuntimeError(
        "Could not find a usable bold font for rough-cut cards. "
        "Pass --font-file or set 'font_file' in the spec."
    )


def has_audio(*, input_path: Path, ffprobe_bin: str) -> bool:
    completed = subprocess.run(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-select_streams",
            "a:0",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(input_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0 and "audio" in completed.stdout


def quote_concat_path(path: Path) -> str:
    escaped = str(path).replace("'", "'\\''")
    return f"'{escaped}'"


def resolve_path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def run_command(command: list[str]) -> None:
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed:\n{' '.join(command)}\n\n{completed.stderr.strip()}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
