from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_tooling.batch_subtitle import main


class BatchSubtitleBackendTests(unittest.TestCase):
    """Tests for --backend and --api-key passthrough in media-batch-subtitle."""

    def _make_manifest(
        self,
        temp_dir: Path,
        media_names: list[str],
    ) -> Path:
        """Create a manifest file and touch media files."""
        inputs_file = temp_dir / "inputs.txt"
        media_dir = temp_dir / "media"
        media_dir.mkdir()

        lines: list[str] = []
        for name in media_names:
            media_path = media_dir / name
            media_path.touch()
            lines.append(str(media_path))

        inputs_file.write_text("\n".join(lines), encoding="utf-8")
        return inputs_file

    def test_backend_whisper_default(self) -> None:
        """Default --backend is whisper."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                    ],
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job"
                ) as mock_run,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs["backend"], "whisper")

    def test_backend_elevenlabs_accepted(self) -> None:
        """--backend elevenlabs is accepted and forwarded."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                        "--backend",
                        "elevenlabs",
                    ],
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job"
                ) as mock_run,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs["backend"], "elevenlabs")

    def test_api_key_flag_passed_through(self) -> None:
        """--api-key flag is forwarded to run_transcription_job."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                        "--backend",
                        "elevenlabs",
                        "--api-key",
                        "test-key-123",
                    ],
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job"
                ) as mock_run,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs["api_key"], "test-key-123")

    def test_api_key_default_none(self) -> None:
        """api_key is None when --api-key is not provided."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                    ],
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job"
                ) as mock_run,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_run.call_args
            self.assertIsNone(call_kwargs["api_key"])

    def test_backend_elevenlabs_with_api_key_no_env_var(self) -> None:
        """--backend elevenlabs with --api-key works even without ELEVENLABS_API_KEY env var."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                        "--backend",
                        "elevenlabs",
                        "--api-key",
                        "explicit-key",
                    ],
                ),
                patch.dict(
                    __import__("os").environ,
                    {},
                    clear=True,
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job"
                ) as mock_run,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs["api_key"], "explicit-key")

    def test_run_transcription_job_error_reported_as_failure(self) -> None:
        """When run_transcription_job raises, the failure is reported and exit code is 1."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                        "--backend",
                        "elevenlabs",
                    ],
                ),
                patch.dict(
                    __import__("os").environ,
                    {},
                    clear=True,
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job",
                    side_effect=RuntimeError(
                        "An API key is required for the elevenlabs backend "
                        "(set ELEVENLABS_API_KEY env var or pass --api-key)."
                    ),
                ),
            ):
                result = main()

            self.assertEqual(result, 1)


class BatchSubtitleBackendChoiceTests(unittest.TestCase):
    """Test that all valid --backend choices are accepted."""

    def test_backend_mlx_accepted(self) -> None:
        """--backend mlx is accepted and forwarded."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = root / "inputs.txt"
            media_dir = root / "media"
            media_dir.mkdir()
            media_path = media_dir / "a.mp4"
            media_path.touch()
            inputs_file.write_text(str(media_path), encoding="utf-8")

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                        "--backend",
                        "mlx",
                    ],
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job"
                ) as mock_run,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs["backend"], "mlx")

    def test_backend_faster_whisper_accepted(self) -> None:
        """--backend faster-whisper is accepted and forwarded."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = root / "inputs.txt"
            media_dir = root / "media"
            media_dir.mkdir()
            media_path = media_dir / "a.mp4"
            media_path.touch()
            inputs_file.write_text(str(media_path), encoding="utf-8")

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                        "--backend",
                        "faster-whisper",
                    ],
                ),
                patch(
                    "media_tooling.batch_subtitle.run_transcription_job"
                ) as mock_run,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_run.call_args
            self.assertEqual(call_kwargs["backend"], "faster-whisper")

    def test_backend_elevenlabs_without_key_reports_failure(self) -> None:
        """--backend elevenlabs without --api-key or env var reports failure."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = root / "inputs.txt"
            media_dir = root / "media"
            media_dir.mkdir()
            media_path = media_dir / "a.mp4"
            media_path.touch()
            inputs_file.write_text(str(media_path), encoding="utf-8")

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-subtitle",
                        "--inputs-file",
                        str(inputs_file),
                        "--audio-dir",
                        str(root / "audio"),
                        "--transcripts-dir",
                        str(root / "transcripts"),
                        "--subtitles-dir",
                        str(root / "subs"),
                        "--backend",
                        "elevenlabs",
                    ],
                ),
                patch.dict(
                    __import__("os").environ,
                    {},
                    clear=True,
                ),
                patch(
                    "media_tooling.subtitle._requests_module",
                    MagicMock(),
                ),
            ):
                result = main()

            self.assertNotEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
