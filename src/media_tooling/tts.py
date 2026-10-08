from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

from media_tooling.subtitle_translate import parse_srt_file

try:
    import requests as _requests_module
except ImportError:  # pragma: no cover - optional dependency
    _requests_module = None


ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
RETRYABLE_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate narration audio from a text or SRT script."
    )
    parser.add_argument(
        "input",
        help="Path to a UTF-8 text/Markdown/SRT script, or '-' to read stdin.",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        help="Path for the generated audio file.",
    )
    parser.add_argument(
        "--backend",
        choices=["elevenlabs"],
        default="elevenlabs",
        help="TTS backend. Default: elevenlabs.",
    )
    parser.add_argument(
        "--voice-id",
        default=None,
        help="ElevenLabs voice ID. Falls back to ELEVENLABS_VOICE_ID_EN or ELEVENLABS_VOICE_ID.",
    )
    parser.add_argument(
        "--model",
        default=os.environ.get("ELEVENLABS_MODEL_ID", DEFAULT_MODEL),
        help=f"ElevenLabs model ID. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--output-format",
        default=DEFAULT_OUTPUT_FORMAT,
        help=f"ElevenLabs output format. Default: {DEFAULT_OUTPUT_FORMAT}.",
    )
    parser.add_argument("--stability", type=float, default=0.62)
    parser.add_argument("--similarity-boost", type=float, default=0.78)
    parser.add_argument("--style", type=float, default=0.12)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument(
        "--no-speaker-boost",
        action="store_true",
        help="Disable ElevenLabs speaker boost.",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--skip-existing", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output_path = Path(args.output).expanduser().resolve()

    if args.input != "-" and Path(args.input).expanduser().resolve() == output_path:
        print("Output must differ from the input script.", file=sys.stderr)
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
        text = read_script(args.input)
        audio = synthesize_text(
            backend=args.backend,
            text=text,
            voice_id=args.voice_id,
            model_id=args.model,
            output_format=args.output_format,
            stability=args.stability,
            similarity_boost=args.similarity_boost,
            style=args.style,
            speed=args.speed,
            use_speaker_boost=not args.no_speaker_boost,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(audio)
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Generated narration: {output_path}")
    return 0


def read_script(input_value: str) -> str:
    if input_value == "-":
        text = sys.stdin.read()
    else:
        input_path = Path(input_value).expanduser().resolve()
        if not input_path.exists():
            raise ValueError(f"Input script not found: {input_path}")
        if input_path.suffix.lower() == ".srt":
            text = "\n".join(cue.text for cue in parse_srt_file(input_path))
        else:
            text = input_path.read_text(encoding="utf-8")

    text = text.strip()
    if not text:
        raise ValueError("The input script is empty.")
    return text


def resolve_voice_id(voice_id: str | None = None) -> str:
    resolved = voice_id or os.environ.get("ELEVENLABS_VOICE_ID_EN")
    if not resolved:
        resolved = os.environ.get("ELEVENLABS_VOICE_ID")
    if not resolved or not resolved.strip():
        raise RuntimeError(
            "An ElevenLabs voice ID is required (set ELEVENLABS_VOICE_ID_EN "
            "or pass --voice-id)."
        )
    return resolved.strip()


def resolve_api_key() -> str:
    if _requests_module is None:
        raise RuntimeError(
            "The elevenlabs backend requires the 'requests' package. "
            "Install with: pip install media-tooling[elevenlabs]"
        )
    api_key = os.environ.get("ELEVENLABS_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Set ELEVENLABS_API_KEY before using the elevenlabs backend.")
    return api_key


def synthesize_text(
    *,
    backend: str,
    text: str,
    voice_id: str | None,
    model_id: str,
    output_format: str,
    stability: float,
    similarity_boost: float,
    style: float,
    speed: float,
    use_speaker_boost: bool,
) -> bytes:
    if backend != "elevenlabs":
        raise ValueError(f"Unsupported TTS backend: {backend}")

    return synthesize_with_elevenlabs(
        text=text,
        voice_id=resolve_voice_id(voice_id),
        model_id=model_id,
        output_format=output_format,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        speed=speed,
        use_speaker_boost=use_speaker_boost,
    )


def synthesize_with_elevenlabs(
    *,
    text: str,
    voice_id: str,
    model_id: str,
    output_format: str,
    stability: float,
    similarity_boost: float,
    style: float,
    speed: float,
    use_speaker_boost: bool,
) -> bytes:
    api_key = resolve_api_key()
    if _requests_module is None:  # pragma: no cover - guarded by resolve_api_key
        raise RuntimeError("The requests package is required for ElevenLabs TTS.")

    payload: dict[str, Any] = {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
            "speed": speed,
            "use_speaker_boost": use_speaker_boost,
        },
    }
    url = f"{ELEVENLABS_TTS_URL}/{voice_id}"
    last_error = ""
    for attempt in range(1, 5):
        try:
            response = _requests_module.post(
                url,
                params={"output_format": output_format},
                headers={"Content-Type": "application/json", "xi-api-key": api_key},
                json=payload,
                timeout=120,
            )
        except _requests_module.exceptions.RequestException:
            raise RuntimeError("Could not reach ElevenLabs. Check your connection and retry.") from None
        if response.ok:
            if not response.content:
                raise RuntimeError("ElevenLabs returned empty audio.")
            return bytes(response.content)

        last_error = f"HTTP {response.status_code}"
        if response.status_code not in RETRYABLE_STATUS_CODES:
            break
        if attempt < 4:
            time.sleep(0.75 * attempt)

    raise RuntimeError(f"ElevenLabs generation failed after {attempt} attempts. {last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
