from __future__ import annotations

import argparse
import contextlib
import json
import os
import platform
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:
    from lightning_whisper_mlx import LightningWhisperMLX
    from lightning_whisper_mlx.transcribe import transcribe_audio
except ImportError:  # pragma: no cover - depends on platform install
    LightningWhisperMLX = None
    transcribe_audio = None

try:
    from faster_whisper import BatchedInferencePipeline, WhisperModel
except ImportError:  # pragma: no cover - depends on platform install
    BatchedInferencePipeline = None
    WhisperModel = None

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
DEFAULT_BACKEND = "auto"
TIMESTAMP_RATIO_TOLERANCE = 0.02
TIMESTAMP_EXPECTED_MLX_RATIO = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate transcript, subtitles, and JSON metadata from audio or video files."
    )
    parser.add_argument("input", help="Path to an audio or video file.")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Whisper model to use. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "mlx", "faster-whisper"],
        default=DEFAULT_BACKEND,
        help=f"Transcription backend. Default: {DEFAULT_BACKEND}.",
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
        help="Batch size used by the transcription backend. Default: 12.",
    )
    parser.add_argument(
        "--quant",
        choices=["4bit", "8bit"],
        default=None,
        help="Optional quantization mode for the MLX backend.",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="Optional faster-whisper device such as 'cpu' or 'cuda'.",
    )
    parser.add_argument(
        "--compute-type",
        default=None,
        help="Optional faster-whisper compute type such as 'int8', 'float16', or 'float32'.",
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
    parser.add_argument(
        "--disable-timestamp-correction",
        action="store_true",
        help="Disable the post-transcription timestamp sanity check and auto-correction.",
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
            backend=args.backend,
            language=args.language,
            batch_size=args.batch_size,
            quant=args.quant,
            device=args.device,
            compute_type=args.compute_type,
            audio_path=audio_path,
            txt_path=txt_path,
            srt_path=srt_path,
            json_path=json_path,
            ffmpeg_bin=args.ffmpeg_bin,
            overwrite=args.overwrite,
            skip_existing=args.skip_existing,
            initial_prompt=args.initial_prompt,
            disable_timestamp_correction=args.disable_timestamp_correction,
        )
    except (ValueError, FileExistsError, RuntimeError, TypeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def run_transcription_job(
    *,
    input_path: Path,
    model_name: str,
    backend: str,
    language: str | None,
    batch_size: int,
    quant: str | None,
    device: str | None,
    compute_type: str | None,
    audio_path: Path,
    txt_path: Path,
    srt_path: Path,
    json_path: Path,
    ffmpeg_bin: str,
    overwrite: bool,
    skip_existing: bool,
    initial_prompt: str | None,
    disable_timestamp_correction: bool,
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

    resolved_backend = resolve_backend(backend)
    print(
        f"Transcribing {audio_path} with model '{model_name}' using backend '{resolved_backend}'",
        flush=True,
    )
    ffmpeg_parent = resolve_command_directory(ffmpeg_bin)
    with temporarily_prepended_path(ffmpeg_parent):
        result = transcribe_media(
            backend=resolved_backend,
            audio_path=audio_path,
            model_name=model_name,
            language=language,
            batch_size=batch_size,
            quant=quant,
            device=device,
            compute_type=compute_type,
            initial_prompt=initial_prompt,
        )
    segments = normalize_segments(result.get("segments", []))
    audio_duration = probe_media_duration(
        input_path=audio_path,
        ffprobe_bin=resolve_ffprobe_bin(ffmpeg_bin),
    )
    segments, timestamp_correction = maybe_correct_suspicious_timestamps(
        segments=segments,
        media_duration=audio_duration,
        backend=resolved_backend,
        enabled=not disable_timestamp_correction,
    )

    txt_text = build_txt(segments)
    srt_text = build_srt(segments)
    payload = {
        "input_path": str(input_path),
        "audio_path": str(audio_path),
        "backend": resolved_backend,
        "model": model_name,
        "language": result.get("language"),
        "audio_duration": audio_duration,
        "timestamp_correction": timestamp_correction,
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


def resolve_backend(requested_backend: str) -> str:
    if requested_backend == "auto":
        if mlx_backend_available():
            return "mlx"
        if faster_whisper_available():
            return "faster-whisper"
        raise RuntimeError(
            "No transcription backend is available. Install the platform-specific dependencies with 'uv sync'."
        )

    if requested_backend == "mlx":
        if not mlx_backend_available():
            raise RuntimeError(
                "The MLX backend requires Apple Silicon and an installation with 'lightning-whisper-mlx' available."
            )
        return requested_backend

    if requested_backend == "faster-whisper":
        if not faster_whisper_available():
            raise RuntimeError(
                "The faster-whisper backend is not available in this environment."
            )
        return requested_backend

    raise RuntimeError(f"Unsupported backend: {requested_backend}")


def mlx_backend_available() -> bool:
    return (
        sys.platform == "darwin"
        and platform.machine() == "arm64"
        and LightningWhisperMLX is not None
        and transcribe_audio is not None
    )


def faster_whisper_available() -> bool:
    return WhisperModel is not None and BatchedInferencePipeline is not None


def transcribe_media(
    *,
    backend: str,
    audio_path: Path,
    model_name: str,
    language: str | None,
    batch_size: int,
    quant: str | None,
    device: str | None,
    compute_type: str | None,
    initial_prompt: str | None,
) -> dict[str, Any]:
    if backend == "mlx":
        return transcribe_with_mlx(
            audio_path=audio_path,
            model_name=model_name,
            language=language,
            batch_size=batch_size,
            quant=quant,
            initial_prompt=initial_prompt,
        )
    if backend == "faster-whisper":
        return transcribe_with_faster_whisper(
            audio_path=audio_path,
            model_name=model_name,
            language=language,
            batch_size=batch_size,
            device=device,
            compute_type=compute_type,
            initial_prompt=initial_prompt,
        )
    raise RuntimeError(f"Unsupported backend: {backend}")


def transcribe_with_mlx(
    *,
    audio_path: Path,
    model_name: str,
    language: str | None,
    batch_size: int,
    quant: str | None,
    initial_prompt: str | None,
) -> dict[str, Any]:
    if LightningWhisperMLX is None or transcribe_audio is None:
        raise RuntimeError("The MLX backend is not available in this environment.")

    model = LightningWhisperMLX(model_name, batch_size=batch_size, quant=quant)
    return transcribe_audio(
        str(audio_path),
        path_or_hf_repo=f"./mlx_models/{model.name}",
        language=language,
        batch_size=batch_size,
        initial_prompt=initial_prompt,
    )


def transcribe_with_faster_whisper(
    *,
    audio_path: Path,
    model_name: str,
    language: str | None,
    batch_size: int,
    device: str | None,
    compute_type: str | None,
    initial_prompt: str | None,
) -> dict[str, Any]:
    if WhisperModel is None or BatchedInferencePipeline is None:
        raise RuntimeError("The faster-whisper backend is not available in this environment.")

    unsupported_models = {"distil-small.en", "distil-medium.en"}
    if model_name in unsupported_models:
        raise RuntimeError(
            f"The model '{model_name}' is not a supported faster-whisper preset. "
            "Use a standard Whisper model such as 'small' or 'medium', or a supported distil checkpoint such as 'distil-large-v3'."
        )

    resolved_device = device or "cpu"
    resolved_compute_type = compute_type or ("int8" if resolved_device == "cpu" else "float16")
    model = WhisperModel(model_name, device=resolved_device, compute_type=resolved_compute_type)
    pipeline = BatchedInferencePipeline(model=model)
    segments_iter, info = pipeline.transcribe(
        str(audio_path),
        batch_size=batch_size,
        language=language,
        initial_prompt=initial_prompt,
    )
    segments = [
        {
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text.strip(),
        }
        for segment in segments_iter
    ]
    full_text = " ".join(segment["text"] for segment in segments).strip()
    return {
        "language": getattr(info, "language", language),
        "text": full_text,
        "segments": segments,
    }


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


@contextlib.contextmanager
def temporarily_prepended_path(directory: str | None) -> Iterator[None]:
    if not directory:
        yield
        return

    previous_path = os.environ.get("PATH", "")
    os.environ["PATH"] = f"{directory}:{previous_path}" if previous_path else directory
    try:
        yield
    finally:
        os.environ["PATH"] = previous_path


def resolve_command_directory(command_name: str) -> str | None:
    command_location = shutil.which(command_name)
    if command_location:
        return str(Path(command_location).resolve().parent)

    expanded = Path(command_name).expanduser()
    if expanded.exists():
        return str(expanded.resolve().parent)

    return None


def resolve_ffprobe_bin(ffmpeg_bin: str) -> str:
    ffmpeg_location = shutil.which(ffmpeg_bin)
    if ffmpeg_location:
        sibling = Path(ffmpeg_location).with_name("ffprobe")
        if sibling.exists():
            return str(sibling)

    expanded = Path(ffmpeg_bin).expanduser()
    if expanded.exists():
        sibling = expanded.resolve().with_name("ffprobe")
        if sibling.exists():
            return str(sibling)

    return shutil.which("ffprobe") or "ffprobe"


def probe_media_duration(input_path: Path, ffprobe_bin: str) -> float | None:
    try:
        completed = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(input_path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    output = completed.stdout.strip()
    if not output:
        return None

    try:
        return float(output)
    except ValueError:
        return None


def maybe_correct_suspicious_timestamps(
    *,
    segments: list[dict[str, Any]],
    media_duration: float | None,
    backend: str,
    enabled: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw_last_segment_end = segments[-1]["end"] if segments else None
    correction = {
        "enabled": enabled,
        "backend": backend,
        "media_duration": media_duration,
        "raw_last_segment_end": raw_last_segment_end,
        "ratio_to_media_duration": None,
        "nearest_integer_ratio": None,
        "applied": False,
        "scale_factor": None,
        "corrected_last_segment_end": raw_last_segment_end,
        "reason": None,
    }

    if not enabled or backend != "mlx" or not segments or media_duration is None:
        return segments, correction

    if raw_last_segment_end is None or raw_last_segment_end <= 0:
        correction["reason"] = "missing-or-invalid-segment-end"
        return segments, correction

    ratio = media_duration / raw_last_segment_end
    nearest_integer_ratio = round(ratio)
    correction["ratio_to_media_duration"] = ratio
    correction["nearest_integer_ratio"] = nearest_integer_ratio

    if nearest_integer_ratio == 1:
        correction["reason"] = "ratio-close-to-1"
        return segments, correction

    if abs(ratio - nearest_integer_ratio) > TIMESTAMP_RATIO_TOLERANCE:
        correction["reason"] = "ratio-not-close-enough-to-integer"
        return segments, correction

    if nearest_integer_ratio != TIMESTAMP_EXPECTED_MLX_RATIO:
        correction["reason"] = "ratio-does-not-match-observed-mlx-compression"
        return segments, correction

    scaled_segments = [
        {
            "start": round(segment["start"] * ratio, 3),
            "end": round(segment["end"] * ratio, 3),
            "text": segment["text"],
        }
        for segment in segments
    ]
    correction["applied"] = True
    correction["scale_factor"] = ratio
    correction["corrected_last_segment_end"] = scaled_segments[-1]["end"]
    correction["reason"] = "media-duration-matched-observed-mlx-ten-x-compression"

    print(
        "Timestamp sanity check: "
        f"media duration {media_duration:.3f}s vs raw transcript end {raw_last_segment_end:.3f}s; "
        f"applying x{ratio:.6f} correction for MLX timestamps.",
        flush=True,
    )
    return scaled_segments, correction


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
