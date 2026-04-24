from __future__ import annotations

import argparse
from pathlib import Path

from media_tooling.batch_utils import finish_batch, load_manifest_inputs, record_failure
from media_tooling.subtitle import run_transcription_job


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Batch subtitle/transcript generation for a manifest of media files."
    )
    parser.add_argument(
        "--inputs-file",
        required=True,
        help="Text file with one media path per line.",
    )
    parser.add_argument(
        "--audio-dir",
        required=True,
        help="Directory for extracted audio files.",
    )
    parser.add_argument(
        "--transcripts-dir",
        required=True,
        help="Directory for transcript .txt and .json outputs.",
    )
    parser.add_argument(
        "--subtitles-dir",
        required=True,
        help="Directory for .srt outputs.",
    )
    parser.add_argument(
        "--model",
        default="small",
        help="Whisper model to use.",
    )
    parser.add_argument(
        "--backend",
        choices=["whisper", "auto", "mlx", "faster-whisper", "elevenlabs"],
        default="whisper",
        help="Transcription backend.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Optional language code such as 'en'.",
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
        help="Batch size used by the transcription backend.",
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
        help="Optional faster-whisper compute type such as 'int8' or 'float16'.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing outputs.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files when txt, json, and srt already exist.",
    )
    parser.add_argument(
        "--disable-timestamp-correction",
        action="store_true",
        help="Disable the post-transcription timestamp sanity check and auto-correction.",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for the transcription backend (e.g. ElevenLabs). Falls back to ELEVENLABS_API_KEY env var.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    inputs_file = Path(args.inputs_file).expanduser().resolve()
    audio_dir = Path(args.audio_dir).expanduser().resolve()
    transcripts_dir = Path(args.transcripts_dir).expanduser().resolve()
    subtitles_dir = Path(args.subtitles_dir).expanduser().resolve()

    for directory in [audio_dir, transcripts_dir, subtitles_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    items = load_manifest_inputs(inputs_file)
    print(f"Loaded {len(items)} input files from {inputs_file}")
    failures: list[str] = []

    for item in items:
        stem = item.stem
        print(f"\n=== {item.name} ===")
        try:
            run_transcription_job(
                input_path=item,
                model_name=args.model,
                backend=args.backend,
                language=args.language,
                batch_size=args.batch_size,
                quant=args.quant,
                device=args.device,
                compute_type=args.compute_type,
                audio_path=audio_dir / f"{stem}.m4a",
                txt_path=transcripts_dir / f"{stem}.txt",
                srt_path=subtitles_dir / f"{stem}.srt",
                json_path=transcripts_dir / f"{stem}.json",
                ffmpeg_bin=args.ffmpeg_bin,
                overwrite=args.overwrite,
                skip_existing=args.skip_existing,
                initial_prompt=args.initial_prompt,
                disable_timestamp_correction=args.disable_timestamp_correction,
                api_key=args.api_key,
            )
        except Exception as exc:  # noqa: BLE001
            record_failure(failures, item, str(exc))

    return finish_batch(failures)


if __name__ == "__main__":
    raise SystemExit(main())
