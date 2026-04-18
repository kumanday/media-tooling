from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_tooling.batch_burn_subtitles import main


class BatchBurnSubtitlesMainTests(unittest.TestCase):
    """Tests for the media-batch-burn-subtitles CLI entry point."""

    def _make_manifest(
        self,
        temp_dir: Path,
        video_names: list[str],
    ) -> Path:
        """Create a manifest file and touch video files + SRT files."""
        inputs_file = temp_dir / "inputs.txt"
        video_dir = temp_dir / "videos"
        srt_dir = temp_dir / "srt"
        video_dir.mkdir()
        srt_dir.mkdir()

        lines: list[str] = []
        for name in video_names:
            video_path = video_dir / name
            video_path.touch()
            srt_path = srt_dir / f"{video_path.stem}.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )
            lines.append(str(video_path))

        inputs_file.write_text("\n".join(lines), encoding="utf-8")
        return inputs_file

    def test_all_success_returns_zero(self) -> None:
        """All items processed successfully -> exit code 0."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4", "b.mp4"])
            output_dir = root / "output"

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                    ],
                ),
                patch("media_tooling.batch_burn_subtitles.burn_subtitles"),
            ):
                result = main()

            self.assertEqual(result, 0)

    def test_failure_returns_one(self) -> None:
        """Any item failing -> exit code 1."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4", "b.mp4"])
            output_dir = root / "output"

            def _fail_on_second(*, input_path: Path, **kwargs: object) -> None:
                if input_path.stem == "b":
                    raise ValueError("SRT not found")

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles",
                    side_effect=_fail_on_second,
                ),
            ):
                result = main()

            self.assertEqual(result, 1)

    def test_skip_existing_skips_output(self) -> None:
        """--skip-existing skips items whose output file already exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4", "b.mp4"])
            output_dir = root / "output"
            output_dir.mkdir()
            # Pre-create output for "a"
            (output_dir / "a-burned.mp4").touch()

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                        "--skip-existing",
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles"
                ) as mock_burn,
            ):
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    result = main()

            # Only "b" should be processed; "a" skipped
            self.assertEqual(mock_burn.call_count, 1)
            self.assertEqual(result, 0)
            output_text = stream.getvalue()
            self.assertIn("Skipping existing", output_text)

    def test_no_overwrite_no_skip_existing_fails_on_existing(self) -> None:
        """Output exists without --overwrite or --skip-existing -> failure for that item."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])
            output_dir = root / "output"
            output_dir.mkdir()
            (output_dir / "a-burned.mp4").touch()

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles"
                ) as mock_burn,
            ):
                result = main()

            # burn_subtitles should NOT have been called
            self.assertEqual(mock_burn.call_count, 0)
            self.assertEqual(result, 1)

    def test_overwrite_processes_existing_output(self) -> None:
        """--overwrite processes items even if output already exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])
            output_dir = root / "output"
            output_dir.mkdir()
            (output_dir / "a-burned.mp4").touch()

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                        "--overwrite",
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles"
                ) as mock_burn,
            ):
                result = main()

            self.assertEqual(mock_burn.call_count, 1)
            self.assertEqual(result, 0)

    def test_overwrite_and_skip_existing_both_set_skip_wins(self) -> None:
        """When both --overwrite and --skip-existing are set, skip-existing wins."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])
            output_dir = root / "output"
            output_dir.mkdir()
            (output_dir / "a-burned.mp4").touch()

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                        "--overwrite",
                        "--skip-existing",
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles"
                ) as mock_burn,
            ):
                stream = io.StringIO()
                with contextlib.redirect_stdout(stream):
                    result = main()

            # Existing output should be skipped, not overwritten
            self.assertEqual(mock_burn.call_count, 0)
            self.assertEqual(result, 0)
            self.assertIn("Skipping existing", stream.getvalue())

    def test_style_passed_to_burn_subtitles(self) -> None:
        """--style argument is forwarded to burn_subtitles."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])
            output_dir = root / "output"

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                        "--style",
                        "natural-sentence",
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles"
                ) as mock_burn,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_burn.call_args
            self.assertEqual(call_kwargs["style"], "natural-sentence")

    def test_pre_filters_passed_to_burn_subtitles(self) -> None:
        """--pre-filters argument is forwarded to burn_subtitles."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])
            output_dir = root / "output"

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                        "--pre-filters",
                        "scale=1920:-2",
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles"
                ) as mock_burn,
            ):
                result = main()

            self.assertEqual(result, 0)
            _, call_kwargs = mock_burn.call_args
            self.assertEqual(call_kwargs["pre_filters"], "scale=1920:-2")

    def test_output_dir_created_if_missing(self) -> None:
        """Output directory is created automatically if it does not exist."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = self._make_manifest(root, ["a.mp4"])
            output_dir = root / "nested" / "output"

            self.assertFalse(output_dir.exists())

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(root / "srt"),
                        "--output-dir",
                        str(output_dir),
                    ],
                ),
                patch("media_tooling.batch_burn_subtitles.burn_subtitles"),
            ):
                result = main()

            self.assertTrue(output_dir.exists())
            self.assertEqual(result, 0)

    def test_missing_srt_reports_clear_error(self) -> None:
        """Missing SRT file is caught before burn_subtitles with a clear message."""
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            inputs_file = root / "inputs.txt"
            video_dir = root / "videos"
            video_dir.mkdir()
            video_path = video_dir / "a.mp4"
            video_path.touch()
            # No SRT directory at all
            srt_dir = root / "srt"
            srt_dir.mkdir()
            # No SRT file for "a"
            inputs_file.write_text(str(video_path), encoding="utf-8")
            output_dir = root / "output"

            with (
                patch.object(
                    __import__("sys"),
                    "argv",
                    [
                        "media-batch-burn-subtitles",
                        "--inputs-file",
                        str(inputs_file),
                        "--srt-dir",
                        str(srt_dir),
                        "--output-dir",
                        str(output_dir),
                    ],
                ),
                patch(
                    "media_tooling.batch_burn_subtitles.burn_subtitles"
                ) as mock_burn,
            ):
                result = main()

            # burn_subtitles should NOT have been called
            self.assertEqual(mock_burn.call_count, 0)
            self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
