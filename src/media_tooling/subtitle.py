from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
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

try:
    import requests as _requests_module
except ImportError:  # pragma: no cover - optional dependency
    _requests_module = None

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
DEFAULT_BACKEND = "whisper"
ELEVENLABS_SCRIBE_URL = "https://api.elevenlabs.io/v1/speech-to-text"
TIMESTAMP_RATIO_TOLERANCE = 0.02
TIMESTAMP_EXPECTED_MLX_RATIO = 10
SUBTITLE_TARGET_DURATION_SECONDS = 4.0
SUBTITLE_MAX_DURATION_SECONDS = 5.0
SUBTITLE_MAX_CHARACTERS = 84
SUBTITLE_MAX_WORDS = 14
SUBTITLE_LONG_GAP_SECONDS = 0.45


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate transcript, subtitles, and JSON metadata from audio or video files."
    )
    parser.add_argument("input", help="Path to an audio or video file.")
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model to use (ignored for elevenlabs backend). Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--backend",
        choices=["whisper", "auto", "mlx", "faster-whisper", "elevenlabs"],
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
    resolved_backend = resolve_backend(backend)
    source_hash_value: str | None = None

    if skip_existing:
        if txt_path.exists() and srt_path.exists() and json_path.exists():
            source_hash_value = compute_source_hash(input_path)
            if source_matches_cache(json_path, input_path, backend=resolved_backend, computed_hash=source_hash_value):
                print(f"Skipping existing outputs for {input_path}")
                return
            else:
                print(f"Cache miss for {input_path}; re-transcribing.")
                overwrite = True  # stale outputs should be replaced
        else:
            # No outputs exist yet; source_hash will be computed after transcription
            source_hash_value = None

    ensure_parent_dirs(audio_path, txt_path, srt_path, json_path)

    wav_cleanup_path: Path | None = None
    persistent_audio_path = audio_path  # path that survives WAV cleanup
    if is_video_file(input_path):
        if resolved_backend == "elevenlabs":
            # Extract persistent audio (same as whisper) for user reference
            extract_audio(
                input_path=input_path,
                audio_path=audio_path,
                ffmpeg_bin=ffmpeg_bin,
                overwrite=overwrite,
            )
            # Also extract temp mono 16kHz PCM WAV for Scribe API upload.
            # Use .pcm.wav suffix to avoid overwriting any existing .wav.
            wav_audio_path = audio_path.with_suffix(".pcm.wav")
            extract_audio_pcm_wav(
                input_path=input_path,
                wav_path=wav_audio_path,
                ffmpeg_bin=ffmpeg_bin,
            )
            audio_path = wav_audio_path
            wav_cleanup_path = wav_audio_path
        else:
            extract_audio(
                input_path=input_path,
                audio_path=audio_path,
                ffmpeg_bin=ffmpeg_bin,
                overwrite=overwrite,
            )
    else:
        if resolved_backend == "elevenlabs":
            # Always convert to mono 16kHz PCM WAV for Scribe API,
            # even if input is already .wav (user .wav files are rarely mono 16kHz).
            # Use .pcm.wav suffix to avoid overwriting the original file.
            wav_audio_path = audio_path.with_suffix(".pcm.wav")
            extract_audio_pcm_wav(
                input_path=input_path,
                wav_path=wav_audio_path,
                ffmpeg_bin=ffmpeg_bin,
            )
            audio_path = wav_audio_path
            wav_cleanup_path = wav_audio_path
        else:
            audio_path = input_path

    effective_model = resolve_model_name(resolved_backend, model_name)
    # Show the user-friendly source path, not the temp PCM WAV used internally
    # for ElevenLabs uploads.
    display_path = input_path if resolved_backend == "elevenlabs" else audio_path
    print(
        f"Transcribing {display_path} with model '{effective_model}' using backend '{resolved_backend}'",
        flush=True,
    )
    try:
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
        # Probe the original input for duration — the PCM WAV (for ElevenLabs)
        # has the same duration, but probing the source is more robust and
        # avoids issues if the WAV extraction was incomplete.
        audio_duration = probe_media_duration(
            input_path=input_path,
            ffprobe_bin=resolve_ffprobe_bin(ffmpeg_bin),
        )
        segments, timestamp_correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=audio_duration,
            backend=resolved_backend,
            enabled=not disable_timestamp_correction,
        )
        source_segment_count = len(segments)
        segments, subtitle_segmentation = resegment_for_subtitles(segments)

        txt_text = build_txt(segments)
        srt_text = build_srt(segments)
        payload: dict[str, Any] = {
            "input_path": str(input_path),
            "audio_path": str(persistent_audio_path),
            "backend": resolved_backend,
            "model": effective_model,
            "language": result.get("language"),
            "audio_duration": audio_duration,
            "timestamp_correction": timestamp_correction,
            "text": result.get("text", "").strip(),
            "source_segment_count": source_segment_count,
            "segment_count": len(segments),
            "subtitle_segmentation": subtitle_segmentation,
            "segments": segments,
        }
        if source_hash_value is not None:
            payload["source_hash"] = source_hash_value
        elif skip_existing:
            # First run with --skip-existing: compute hash now so future
            # runs can detect source changes without re-transcribing.
            payload["source_hash"] = compute_source_hash(input_path)

        # Always include audio_events for consistent JSON schema across backends.
        # ElevenLabs provides actual audio event tags; Whisper produces an empty list.
        payload["audio_events"] = result.get("audio_events", [])

        write_text(txt_path, txt_text, overwrite)
        write_text(srt_path, srt_text, overwrite)
        write_text(json_path, json.dumps(payload, indent=2), overwrite)
    finally:
        # Clean up temporary PCM WAV file created for ElevenLabs upload
        if wav_cleanup_path is not None and wav_cleanup_path.exists():
            wav_cleanup_path.unlink()
            print(f"Cleaned up temporary WAV: {wav_cleanup_path}")

    print(f"Transcript: {txt_path}")
    print(f"Subtitles:  {srt_path}")
    print(f"Metadata:   {json_path}")
    if is_video_file(input_path):
        print(f"Audio:      {persistent_audio_path}")


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
    if requested_backend in ("auto", "whisper"):
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

    if requested_backend == "elevenlabs":
        if not elevenlabs_backend_available():
            raise RuntimeError(
                "The elevenlabs backend requires the 'requests' package "
                "(install with: pip install media-tooling[elevenlabs]) "
                "and the ELEVENLABS_API_KEY environment variable."
            )
        return requested_backend

    raise RuntimeError(f"Unsupported backend: {requested_backend}")


def resolve_model_name(backend: str, model_name: str) -> str:
    """Return the effective model name for a given backend.

    ElevenLabs uses 'scribe_v1' regardless of the --model argument;
    Whisper backends pass through the user-supplied model name.
    """
    return "scribe_v1" if backend == "elevenlabs" else model_name


def mlx_backend_available() -> bool:
    return (
        sys.platform == "darwin"
        and platform.machine() == "arm64"
        and LightningWhisperMLX is not None
        and transcribe_audio is not None
    )


def faster_whisper_available() -> bool:
    return WhisperModel is not None and BatchedInferencePipeline is not None


def elevenlabs_backend_available() -> bool:
    return _requests_module is not None and bool(os.environ.get("ELEVENLABS_API_KEY", "").strip())


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
    if backend == "elevenlabs":
        return transcribe_with_elevenlabs(
            audio_path=audio_path,
            language=language,
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
        word_timestamps=True,
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
        word_timestamps=True,
    )
    segments = [
        normalize_backend_segment(segment)
        for segment in segments_iter
    ]
    full_text = " ".join(segment["text"] for segment in segments).strip()
    return {
        "language": getattr(info, "language", language),
        "text": full_text,
        "segments": segments,
    }


def transcribe_with_elevenlabs(
    *,
    audio_path: Path,
    language: str | None,
) -> dict[str, Any]:
    if _requests_module is None:
        raise RuntimeError(
            "The elevenlabs backend requires the 'requests' package. "
            "Install with: pip install media-tooling[elevenlabs]"
        )
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "ELEVENLABS_API_KEY environment variable is required for the elevenlabs backend."
        )
    return call_scribe_api(audio_path=audio_path, api_key=api_key, language=language)


def call_scribe_api(
    *,
    audio_path: Path,
    api_key: str,
    language: str | None = None,
) -> dict[str, Any]:
    if _requests_module is None:  # pragma: no cover — defense in depth
        raise RuntimeError("requests library is required for ElevenLabs transcription")
    data: dict[str, str] = {
        "model_id": "scribe_v1",
        "diarize": "true",
        "tag_audio_events": "true",
        "timestamps_granularity": "word",
    }
    if language:
        data["language_code"] = language

    max_retries = 3
    base_backoff = 2.0
    last_exc: Exception | None = None
    # Read file content into memory so the handle is not held open during
    # retry sleeps (avoids holding a kernel fd idle for up to 60 s on 429s).
    file_content = audio_path.read_bytes()
    for attempt in range(max_retries):
        try:
            resp = _requests_module.post(
                ELEVENLABS_SCRIBE_URL,
                headers={"xi-api-key": api_key},
                files={"file": (audio_path.name, file_content, "audio/wav")},
                data=data,
                timeout=300,
            )
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(base_backoff * (2 ** attempt))
                continue
            raise RuntimeError(
                f"ElevenLabs Scribe API request failed after {max_retries} attempts: {exc}"
            ) from exc

        if resp.status_code == 200:
            scribe_response = resp.json()
            return parse_scribe_response(scribe_response)

        # Retry on transient server errors (429 rate-limit, 5xx)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
            retry_after = resp.headers.get("Retry-After")
            wait = base_backoff * (2 ** attempt)
            if retry_after:
                try:
                    wait = min(float(retry_after), 60.0)  # cap at 60s
                except ValueError:
                    # Retry-After may be an HTTP-date (e.g. "Fri, 18 Apr 2026 11:00:00 GMT")
                    try:
                        target = parsedate_to_datetime(retry_after)
                        delta = (target - datetime.now(timezone.utc)).total_seconds()
                        if delta > 0:
                            wait = min(delta, 60.0)  # cap at 60s
                    except (ValueError, TypeError):
                        pass  # fall back to exponential backoff
            time.sleep(wait)
            continue

        raise RuntimeError(f"ElevenLabs Scribe returned {resp.status_code}: {resp.text[:500]}")

    # Should not reach here, but just in case
    raise RuntimeError(f"ElevenLabs Scribe API request failed after {max_retries} attempts: {last_exc}")


def parse_scribe_response(scribe_response: dict[str, Any]) -> dict[str, Any]:
    # Work on a shallow copy of the words list to avoid mutating the caller's dict.
    raw_words = [dict(w) for w in scribe_response.get("words", [])]

    # Pre-fill LEADING None speaker_ids from the first non-None speaker.
    # When diarization is uncertain, the API may return None for early words;
    # without this pass the first segment gets speaker_id=None and
    # normalization drops the key, producing a tiny no-speaker fragment
    # when a real speaker_id appears on the next word.
    # Only leading Nones (before the first non-None) are filled; mid-stream
    # Nones are handled by the "inherit from previous segment" logic below.
    first_non_none_idx: int | None = None
    first_non_none_speaker: str | None = None
    for idx, raw_word in enumerate(raw_words):
        sid = raw_word.get("speaker_id")
        if sid is not None:
            first_non_none_idx = idx
            first_non_none_speaker = sid
            break
    if first_non_none_speaker is not None and first_non_none_idx is not None and first_non_none_idx > 0:
        for raw_word in raw_words[:first_non_none_idx]:
            if raw_word.get("speaker_id") is None:
                raw_word["speaker_id"] = first_non_none_speaker

    segments: list[dict[str, Any]] = []
    current_segment: dict[str, Any] | None = None
    current_words: list[dict[str, Any]] = []

    for raw_word in raw_words:
        word_text = raw_word.get("text", raw_word.get("word", ""))
        speaker_id = raw_word.get("speaker_id")
        # When diarization is uncertain, the API may return None for speaker_id.
        # Treat it as "same speaker as previous segment" to prevent fragmentation
        # into many tiny alternating segments on None↔speaker_N transitions.
        if speaker_id is None and current_segment is not None:
            speaker_id = current_segment.get("speaker_id")
        start = float(raw_word.get("start", 0))
        end = float(raw_word.get("end", 0))

        if current_segment is None or current_segment.get("speaker_id") != speaker_id:
            if current_segment is not None:
                current_segment["words"] = current_words
                current_segment["text"] = "".join(w["word"] for w in current_words).strip()
                segments.append(current_segment)
            current_segment = {
                "start": start,
                "end": end,
                "text": "",
                "words": [],
                "speaker_id": speaker_id,
            }
            current_words = []

        current_words.append({
            "word": word_text if not current_words else f" {word_text}",
            "start": start,
            "end": end,
        })
        current_segment["end"] = end

    if current_segment is not None and current_words:
        current_segment["words"] = current_words
        current_segment["text"] = "".join(w["word"] for w in current_words).strip()
        segments.append(current_segment)

    full_text = " ".join(segment["text"] for segment in segments).strip()
    audio_events = scribe_response.get("audio_events", [])
    language_code = scribe_response.get("language_code", scribe_response.get("language"))

    return {
        "language": language_code,
        "text": full_text,
        "segments": segments,
        "audio_events": audio_events,
    }


def extract_audio_pcm_wav(
    input_path: Path,
    wav_path: Path,
    ffmpeg_bin: str,
) -> None:
    """Extract audio as mono 16kHz PCM WAV for ElevenLabs Scribe upload.

    Always overwrites existing PCM WAV files to avoid stale-derived
    audio after source changes (Hard Rule 9: cache integrity).
    """
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", str(input_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg PCM WAV extraction failed.\n{result.stderr}"
        )
    print(f"Extracted PCM WAV: {wav_path}")


def compute_source_hash(source_path: Path) -> str:
    """Hash file content for cache invalidation.

    Uses SHA-256 of file content rather than mtime/size to avoid
    false invalidations from metadata-only changes (touch, rsync -a)
    which would waste paid API credits on re-transcription.
    """
    h = hashlib.sha256()
    with open(source_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def source_matches_cache(
    json_path: Path,
    input_path: Path,
    backend: str | None = None,
    computed_hash: str | None = None,
) -> bool:
    if not json_path.exists():
        return False
    try:
        cached = json.loads(json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    # Check backend field regardless of source_hash presence
    if backend is not None and cached.get("backend") != backend:
        return False
    cached_hash = cached.get("source_hash")
    if not cached_hash:
        # Outputs produced without --skip-existing lack source_hash;
        # honor skip-existing by falling back to backend match when
        # hash is absent.  This means a source change after a run
        # without --skip-existing will not be detected until the
        # user runs without --skip-existing or with --overwrite.
        # Users who need full cache integrity should always use
        # --skip-existing.
        return True
    current_hash = computed_hash or compute_source_hash(input_path)
    if cached_hash != current_hash:
        return False
    return True


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

    # Keys that are rebuilt by the scaling logic; everything else is forwarded
    # as-is so that fields like `speaker_id` are not silently dropped.
    _rebuilt_keys = {"start", "end", "text", "words"}
    scaled_segments = [
        {
            **{k: v for k, v in segment.items() if k not in _rebuilt_keys},
            "start": round(segment["start"] * ratio, 3),
            "end": round(segment["end"] * ratio, 3),
            "text": segment["text"],
            "words": [
                {
                    "word": word["word"],
                    "start": round(word["start"] * ratio, 3),
                    "end": round(word["end"] * ratio, 3),
                }
                for word in segment.get("words", [])
            ],
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
            normalized.append(normalize_backend_segment(segment))
        elif isinstance(segment, (list, tuple)) and len(segment) >= 3:
            start = float(segment[0]) / 1000.0
            end = float(segment[1]) / 1000.0
            text = str(segment[2]).strip()
            words: list[dict[str, Any]] = []
            normalized.append({"start": start, "end": end, "text": text, "words": words})
        else:
            raise TypeError(f"Unsupported segment format: {segment!r}")
    return normalized


def normalize_backend_segment(segment: Any) -> dict[str, Any]:
    if isinstance(segment, dict):
        start = float(segment["start"])
        end = float(segment["end"])
        text = str(segment["text"]).strip()
        raw_words = segment.get("words", [])
        speaker_id = segment.get("speaker_id")
    else:
        start = float(segment.start)
        end = float(segment.end)
        text = str(segment.text).strip()
        raw_words = getattr(segment, "words", None) or []
        speaker_id = getattr(segment, "speaker_id", None)

    result: dict[str, Any] = {
        "start": start,
        "end": end,
        "text": text,
        "words": normalize_words(raw_words),
    }
    if speaker_id is not None:
        result["speaker_id"] = speaker_id
    return result


def normalize_words(raw_words: list[Any]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for word in raw_words:
        if isinstance(word, dict):
            text = str(word["word"])
            start = word.get("start")
            end = word.get("end")
        else:
            text = str(word.word)
            start = getattr(word, "start", None)
            end = getattr(word, "end", None)

        if start is None or end is None:
            continue

        normalized.append(
            {
                "word": text,
                "start": float(start),
                "end": float(end),
            }
        )
    return normalized


def resegment_for_subtitles(
    segments: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    refined_segments: list[dict[str, Any]] = []
    used_word_timestamps = False

    for segment in segments:
        if segment.get("words"):
            used_word_timestamps = True
        refined_segments.extend(split_segment_for_subtitles(segment))

    metadata = {
        "applied": True,
        "source_segment_count": len(segments),
        "segment_count": len(refined_segments),
        "used_word_timestamps": used_word_timestamps,
        "target_duration_seconds": SUBTITLE_TARGET_DURATION_SECONDS,
        "max_duration_seconds": SUBTITLE_MAX_DURATION_SECONDS,
        "max_characters": SUBTITLE_MAX_CHARACTERS,
        "max_words": SUBTITLE_MAX_WORDS,
    }
    return refined_segments, metadata


def split_segment_for_subtitles(segment: dict[str, Any]) -> list[dict[str, Any]]:
    words = segment.get("words") or build_pseudo_words(segment)
    speaker_id = segment.get("speaker_id")
    if len(words) <= 1:
        return [minimal_segment(segment["start"], segment["end"], segment["text"], speaker_id=speaker_id)]

    blocks: list[dict[str, Any]] = []
    block_start_index = 0

    while block_start_index < len(words):
        committed_block = False
        best_break_index: int | None = None

        for current_index in range(block_start_index, len(words)):
            candidate_words = words[block_start_index : current_index + 1]
            candidate_text = join_words(candidate_words)
            if not candidate_text:
                continue

            candidate_start = candidate_words[0]["start"]
            candidate_end = candidate_words[-1]["end"]
            candidate_duration = max(0.0, candidate_end - candidate_start)
            candidate_word_count = count_spoken_words(candidate_words)

            if is_preferred_break(words, current_index):
                best_break_index = current_index

            if (
                candidate_duration <= SUBTITLE_MAX_DURATION_SECONDS
                and len(candidate_text) <= SUBTITLE_MAX_CHARACTERS
                and candidate_word_count <= SUBTITLE_MAX_WORDS
            ):
                if (
                    candidate_duration >= SUBTITLE_TARGET_DURATION_SECONDS
                    and is_preferred_break(words, current_index)
                ):
                    blocks.append(minimal_segment(candidate_start, candidate_end, candidate_text, speaker_id=speaker_id))
                    block_start_index = current_index + 1
                    committed_block = True
                    break
                continue

            split_index = best_break_index
            if split_index is None or split_index < block_start_index:
                split_index = max(block_start_index, current_index - 1)

            if split_index == current_index and split_index > block_start_index:
                split_index -= 1

            chosen_words = words[block_start_index : split_index + 1]
            if not chosen_words:
                chosen_words = candidate_words
                split_index = current_index

            blocks.append(
                minimal_segment(
                    chosen_words[0]["start"],
                    chosen_words[-1]["end"],
                    join_words(chosen_words),
                    speaker_id=speaker_id,
                )
            )
            block_start_index = split_index + 1
            committed_block = True
            break

        if committed_block:
            continue

        trailing_words = words[block_start_index:]
        blocks.append(
            minimal_segment(
                trailing_words[0]["start"],
                trailing_words[-1]["end"],
                join_words(trailing_words),
                speaker_id=speaker_id,
            )
        )
        break

    return merge_tiny_adjacent_blocks(blocks)


def build_pseudo_words(segment: dict[str, Any]) -> list[dict[str, Any]]:
    tokens = segment["text"].split()
    if not tokens:
        return []

    start = float(segment["start"])
    end = float(segment["end"])
    duration = max(0.0, end - start)
    step = duration / len(tokens) if tokens else 0.0

    words = []
    for index, token in enumerate(tokens):
        token_start = start + step * index
        token_end = end if index == len(tokens) - 1 else start + step * (index + 1)
        words.append(
            {
                "word": token if index == 0 else f" {token}",
                "start": round(token_start, 3),
                "end": round(token_end, 3),
            }
        )
    return words


def minimal_segment(
    start: float,
    end: float,
    text: str,
    speaker_id: str | None = None,
) -> dict[str, Any]:
    segment: dict[str, Any] = {
        "start": round(start, 3),
        "end": round(end, 3),
        "text": collapse_whitespace(text),
    }
    if speaker_id is not None:
        segment["speaker_id"] = speaker_id
    return segment


def join_words(words: list[dict[str, Any]]) -> str:
    return collapse_whitespace("".join(word["word"] for word in words))


def collapse_whitespace(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def count_spoken_words(words: list[dict[str, Any]]) -> int:
    return sum(1 for word in words if word["word"].strip())


def is_preferred_break(words: list[dict[str, Any]], index: int) -> bool:
    if index >= len(words) - 1:
        return True

    current_text = words[index]["word"].strip()
    if current_text.endswith((".", "?", "!", ";", ":", ",")):
        return True

    next_start = words[index + 1]["start"]
    current_end = words[index]["end"]
    return (next_start - current_end) >= SUBTITLE_LONG_GAP_SECONDS


def merge_tiny_adjacent_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(blocks) <= 1:
        return blocks

    merged: list[dict[str, Any]] = []
    for block in blocks:
        if not merged:
            merged.append(block)
            continue

        duration = block["end"] - block["start"]
        combined_text = f"{merged[-1]['text']} {block['text']}".strip()
        combined_duration = block["end"] - merged[-1]["start"]
        combined_word_count = len(combined_text.split())
        same_speaker = merged[-1].get("speaker_id") == block.get("speaker_id")

        if (
            same_speaker
            and duration < 1.0
            and len(combined_text) <= SUBTITLE_MAX_CHARACTERS
            and combined_duration <= SUBTITLE_MAX_DURATION_SECONDS
            and combined_word_count <= SUBTITLE_MAX_WORDS
        ):
            merged[-1] = minimal_segment(
                merged[-1]["start"], block["end"], combined_text,
                speaker_id=merged[-1].get("speaker_id"),
            )
            continue

        merged.append(block)

    return merged


def build_txt(segments: list[dict[str, Any]]) -> str:
    lines = []
    for segment in segments:
        speaker = segment.get("speaker_id")
        prefix = f"[{speaker}] " if speaker else ""
        lines.append(
            f"[{format_timestamp(segment['start'])} --> {format_timestamp(segment['end'])}] {prefix}{segment['text']}"
        )
    return "\n".join(lines).strip() + "\n"


def build_srt(segments: list[dict[str, Any]]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        speaker = segment.get("speaker_id")
        text = f"[{speaker}] {segment['text']}" if speaker else segment["text"]
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(segment['start'])} --> {format_srt_timestamp(segment['end'])}",
                    text,
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
