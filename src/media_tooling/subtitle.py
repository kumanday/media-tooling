from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from lightning_whisper_mlx import LightningWhisperMLX
from lightning_whisper_mlx.transcribe import transcribe_audio

VIDEO_SUFFIXES = {
    ".avi",
    ".m4v",
    ".mkv",
    ".mov",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".webm",
}

AUDIO_SUFFIXES = {
    ".aac",
    ".aif",
    ".aiff",
    ".flac",
    ".m4a",
    ".mp3",
    ".ogg",
    ".wav",
}

DEFAULT_MODEL = "small"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate transcript, subtitles, and JSON metadata from audio or video files."
    )
    parser.add_argument("input", help="Path to an audio or video file.")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=[
            "tiny",
            "base",
            "small",
            "medium",
            "large",
            "large-v2",
            "large-v3",
            "distil-small.en",
            "distil-medium.en",
            "distil-large-v2",
            "distil-large-v3",
        ],
        help=f"Whisper model to use. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional language code such as 'en'. Auto-detects when omitted.",
    )
    parser.add_argument(
        "--initial-prompt",
        default=None,
        help="Optional glossary/context prompt to improve proper noun recognition.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=12,
        help="Batch size passed to lightning-whisper-mlx. Default: 12.",
    )
    parser.add_argument(
        "--quant",
        choices=["4bit", "8bit"],
        default=None,
        help="Optional quantization mode for non-distil models.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for generated outputs when explicit file paths are not provided.",
    )
    parser.add_argument(
        "--audio-out",
        default=None,
        help="Explicit path for extracted audio. Only used for video inputs.",
    )
    parser.add_argument(
        "--txt-out",
        default=None,
        help="Explicit path for transcript text output.",
    )
    parser.add_argument(
        "--srt-out",
        default=None,
        help="Explicit path for subtitle output.",
    )
    parser.add_argument(
        "--json-out",
        default=None,
        help="Explicit path for structured JSON output.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg for video-to-audio extraction.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip work when transcript, SRT, and JSON outputs already exist.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    try:
        audio_path, txt_path, srt_path, json_path = resolve_output_paths(input_path, args)
        run_transcription_job(
            input_path=input_path,
            model_name=args.model,
            language=args.language,
            batch_size=args.batch_size,
            quant=args.quant,
            audio_path=audio_path,
            txt_path=txt_path,
            srt_path=srt_path,
            json_path=json_path,
            ffmpeg_bin=args.ffmpeg_bin,
            overwrite=args.overwrite,
            skip_existing=args.skip_existing,
            initial_prompt=args.initial_prompt,
        )
    except (ValueError, FileExistsError, RuntimeError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def run_transcription_job(
    *,
    input_path: Path,
    model_name: str,
    language: str | None,
    batch_size: int,
    quant: str | None,
    audio_path: Path,
    txt_path: Path,
    srt_path: Path,
    json_path: Path,
    ffmpeg_bin: str,
    overwrite: bool,
    skip_existing: bool,
    initial_prompt: str | None,
) -> None:
    if skip_existing and txt_path.exists() and srt_path.exists() and json_path.exists():
        print(f"Skipping existing outputs for {input_path}")
        return

    ensure_parent_dirs(audio_path, txt_path, srt_path, json_path)

    if is_video_file(input_path):
        extract_audio(
            input_path=input_path,
            audio_path=audio_path,
            ffmpeg_bin=ffmpeg_bin,
            overwrite=overwrite,
        )
    else:
        audio_path = input_path

    ffmpeg_parent = str(Path(ffmpeg_bin).expanduser().resolve().parent)
    os.environ["PATH"] = f"{ffmpeg_parent}:{os.environ.get('PATH', '')}"

    print(f"Transcribing {audio_path} with model '{model_name}'", flush=True)
    model = LightningWhisperMLX(model_name, batch_size=batch_size, quant=quant)
    result = transcribe_audio(
        str(audio_path),
        path_or_hf_repo=f"./mlx_models/{model.name}",
        language=language,
        batch_size=batch_size,
        initial_prompt=initial_prompt,
    )
    segments = normalize_segments(result.get("segments", []))

    txt_text = build_txt(segments)
    srt_text = build_srt(segments)
    payload = {
        "input_path": str(input_path),
        "audio_path": str(audio_path),
        "model": model_name,
        "language": result.get("language"),
        "text": result.get("text", "").strip(),
        "segment_count": len(segments),
        "segments": segments,
    }

    write_text(txt_path, txt_text, overwrite)
    write_text(srt_path, srt_text, overwrite)
    write_text(json_path, json.dumps(payload, indent=2), overwrite)

    print(f"Transcript: {txt_path}")
    print(f"Subtitles:  {srt_path}")
    print(f"Metadata:   {json_path}")
    if is_video_file(input_path):
        print(f"Audio:      {audio_path}")


def resolve_output_paths(
    input_path: Path, args: argparse.Namespace
) -> tuple[Path, Path, Path, Path]:
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else input_path.parent
    stem = input_path.stem

    if is_video_file(input_path):
        audio_path = (
            Path(args.audio_out).expanduser().resolve()
            if args.audio_out
            else output_dir / f"{stem}.m4a"
        )
    elif is_audio_file(input_path):
        audio_path = input_path
    else:
        raise ValueError(f"Unsupported media type: {input_path.suffix}")

    txt_path = (
        Path(args.txt_out).expanduser().resolve()
        if args.txt_out
        else output_dir / f"{stem}.txt"
    )
    srt_path = (
        Path(args.srt_out).expanduser().resolve()
        if args.srt_out
        else output_dir / f"{stem}.srt"
    )
    json_path = (
        Path(args.json_out).expanduser().resolve()
        if args.json_out
        else output_dir / f"{stem}.json"
    )
    return audio_path, txt_path, srt_path, json_path


def ensure_parent_dirs(*paths: Path) -> None:
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_SUFFIXES


def is_audio_file(path: Path) -> bool:
    return path.suffix.lower() in AUDIO_SUFFIXES


def extract_audio(input_path: Path, audio_path: Path, ffmpeg_bin: str, overwrite: bool) -> None:
    if audio_path.exists() and not overwrite:
        print(f"Reusing existing audio {audio_path}")
        return

    copy_cmd = [
        ffmpeg_bin,
        "-y" if overwrite else "-n",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        "copy",
        str(audio_path),
    ]

    copy_result = subprocess.run(copy_cmd, capture_output=True, text=True)
    if copy_result.returncode == 0:
        return

    transcode_cmd = [
        ffmpeg_bin,
        "-y" if overwrite else "-n",
        "-i",
        str(input_path),
        "-vn",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(audio_path),
    ]
    transcode_result = subprocess.run(transcode_cmd, capture_output=True, text=True)
    if transcode_result.returncode == 0:
        print("Audio stream copy failed; used AAC transcode fallback.")
        return

    raise RuntimeError(
        "ffmpeg audio extraction failed.\n"
        f"Copy stderr:\n{copy_result.stderr}\n"
        f"Transcode stderr:\n{transcode_result.stderr}"
    )


def normalize_segments(raw_segments: list[Any]) -> list[dict[str, Any]]:
    normalized = []
    for segment in raw_segments:
        if isinstance(segment, dict):
            start = float(segment["start"])
            end = float(segment["end"])
            text = str(segment["text"]).strip()
        elif isinstance(segment, (list, tuple)) and len(segment) >= 3:
            start = float(segment[0]) / 1000.0
            end = float(segment[1]) / 1000.0
            text = str(segment[2]).strip()
        else:
            raise TypeError(f"Unsupported segment format: {segment!r}")

        normalized.append({"start": start, "end": end, "text": text})
    return normalized


def build_txt(segments: list[dict[str, Any]]) -> str:
    return "\n".join(
        f"[{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}] {segment['text']}"
        for segment in segments
    ).strip() + "\n"


def build_srt(segments: list[dict[str, Any]]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(segment['end'])}",
                    segment["text"],
                ]
            )
        )
    return "\n\n".join(blocks).strip() + "\n"


def write_text(path: Path, contents: str, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"Refusing to overwrite existing file without --overwrite: {path}")
    path.write_text(contents, encoding="utf-8")


def format_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"


def format_srt_timestamp(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole_seconds = int(seconds % 60)
    milliseconds = int(round((seconds - int(seconds)) * 1000))
    if milliseconds == 1000:
        whole_seconds += 1
        milliseconds = 0
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{milliseconds:03d}"


if __name__ == "__main__":
    raise SystemExit(main())
