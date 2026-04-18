from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from media_tooling.loudnorm import (
    LOUDNORM_I,
    LOUDNORM_LRA,
    LOUDNORM_TP,
    apply_loudnorm_preview,
    apply_loudnorm_two_pass,
    has_video_stream,
    main,
    measure_loudness,
    parse_args,
)

SAMPLE_MEASUREMENT_JSON = json.dumps({
    "input_i": "-24.0",
    "input_tp": "-1.5",
    "input_lra": "15.0",
    "input_thresh": "-34.2",
    "target_offset": "-0.3",
})


def _mock_subprocess_run_factory(stdout: str = "", stderr: str = "", returncode: int = 0) -> mock.MagicMock:
    result = mock.MagicMock()
    result.stdout = stdout
    result.stderr = stderr
    result.returncode = returncode
    return result


class HasVideoStreamTests(unittest.TestCase):
    def test_returns_true_when_video_stream_found(self) -> None:
        mock_result = _mock_subprocess_run_factory(stdout="video\n")
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=mock_result):
            result = has_video_stream(Path("input.mp4"))

        self.assertTrue(result)

    def test_returns_false_when_no_video_stream(self) -> None:
        mock_result = _mock_subprocess_run_factory(stdout="")
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=mock_result):
            result = has_video_stream(Path("audio.mp3"))

        self.assertFalse(result)

    def test_uses_ffprobe_bin(self) -> None:
        mock_result = _mock_subprocess_run_factory(stdout="")
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=mock_result) as mock_run:
            has_video_stream(Path("input.mp4"), ffprobe_bin="/usr/local/bin/ffprobe")

        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "/usr/local/bin/ffprobe")


class MeasureLoudnessTests(unittest.TestCase):
    def test_parses_json_output_from_stderr(self) -> None:
        measurement_json = SAMPLE_MEASUREMENT_JSON
        mock_result = _mock_subprocess_run_factory(stderr=measurement_json)
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=mock_result):
            result = measure_loudness(Path("input.mp4"))

        assert result is not None
        self.assertEqual(result["input_i"], "-24.0")
        self.assertEqual(result["input_tp"], "-1.5")
        self.assertEqual(result["input_lra"], "15.0")
        self.assertEqual(result["input_thresh"], "-34.2")
        self.assertEqual(result["target_offset"], "-0.3")

    def test_returns_none_when_no_json_in_stderr(self) -> None:
        mock_result = _mock_subprocess_run_factory(stderr="no json here")
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=mock_result):
            result = measure_loudness(Path("input.mp4"))

        self.assertIsNone(result)

    def test_returns_none_when_json_missing_required_keys(self) -> None:
        incomplete_json = json.dumps({"input_i": "-24.0"})
        mock_result = _mock_subprocess_run_factory(stderr=incomplete_json)
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=mock_result):
            result = measure_loudness(Path("input.mp4"))

        self.assertIsNone(result)

    def test_uses_correct_filter_string(self) -> None:
        mock_result = _mock_subprocess_run_factory(stderr=SAMPLE_MEASUREMENT_JSON)
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=mock_result) as mock_run:
            measure_loudness(Path("input.mp4"), ffmpeg_bin="/usr/local/bin/ffmpeg")

        cmd = mock_run.call_args[0][0]
        self.assertEqual(cmd[0], "/usr/local/bin/ffmpeg")
        af_index = cmd.index("-af")
        filter_str = cmd[af_index + 1]
        self.assertIn(f"I={LOUDNORM_I}", filter_str)
        self.assertIn(f"TP={LOUDNORM_TP}", filter_str)
        self.assertIn(f"LRA={LOUDNORM_LRA}", filter_str)
        self.assertIn("print_format=json", filter_str)


class ApplyLoudnormTwoPassTests(unittest.TestCase):
    def test_two_pass_uses_measured_values_in_second_pass(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr=SAMPLE_MEASUREMENT_JSON)
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        apply_result = _mock_subprocess_run_factory()

        with mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run:
            mock_run.side_effect = [measure_result, probe_result, apply_result]
            success = apply_loudnorm_two_pass(
                Path("input.mp4"), Path("output.mp4"), ffmpeg_bin="ffmpeg"
            )

        self.assertTrue(success)
        self.assertEqual(mock_run.call_count, 3)

        # Third call (index 2) should use measured values with linear=true
        second_pass_cmd = mock_run.call_args_list[2][0][0]
        af_index = second_pass_cmd.index("-af")
        filter_str = second_pass_cmd[af_index + 1]
        self.assertIn("measured_I=-24.0", filter_str)
        self.assertIn("measured_TP=-1.5", filter_str)
        self.assertIn("measured_LRA=15.0", filter_str)
        self.assertIn("measured_thresh=-34.2", filter_str)
        self.assertIn("offset=-0.3", filter_str)
        self.assertIn("linear=true", filter_str)

    def test_returns_false_when_measurement_fails(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr="no json")
        with mock.patch("media_tooling.loudnorm.subprocess.run", return_value=measure_result):
            success = apply_loudnorm_two_pass(
                Path("input.mp4"), Path("output.mp4"), ffmpeg_bin="ffmpeg"
            )

        self.assertFalse(success)

    def test_second_pass_includes_video_copy_for_video_input(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr=SAMPLE_MEASUREMENT_JSON)
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        apply_result = _mock_subprocess_run_factory()

        with mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run:
            mock_run.side_effect = [measure_result, probe_result, apply_result]
            apply_loudnorm_two_pass(Path("input.mp4"), Path("output.mp4"))

        second_pass_cmd = mock_run.call_args_list[2][0][0]
        self.assertIn("-c:v", second_pass_cmd)
        cv_index = second_pass_cmd.index("-c:v")
        self.assertEqual(second_pass_cmd[cv_index + 1], "copy")
        self.assertIn("-c:a", second_pass_cmd)
        ca_index = second_pass_cmd.index("-c:a")
        self.assertEqual(second_pass_cmd[ca_index + 1], "aac")
        self.assertIn("-movflags", second_pass_cmd)

    def test_second_pass_omits_video_copy_for_audio_only_input(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr=SAMPLE_MEASUREMENT_JSON)
        probe_result = _mock_subprocess_run_factory(stdout="")
        apply_result = _mock_subprocess_run_factory()

        with mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run:
            mock_run.side_effect = [measure_result, probe_result, apply_result]
            apply_loudnorm_two_pass(Path("input.wav"), Path("output.mp4"))

        second_pass_cmd = mock_run.call_args_list[2][0][0]
        self.assertNotIn("-c:v", second_pass_cmd)
        self.assertIn("-c:a", second_pass_cmd)
        self.assertIn("-movflags", second_pass_cmd)

    def test_movflags_omitted_for_non_mp4_output(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr=SAMPLE_MEASUREMENT_JSON)
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        apply_result = _mock_subprocess_run_factory()

        with mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run:
            mock_run.side_effect = [measure_result, probe_result, apply_result]
            apply_loudnorm_two_pass(Path("input.mp4"), Path("output.mkv"))

        second_pass_cmd = mock_run.call_args_list[2][0][0]
        self.assertNotIn("-movflags", second_pass_cmd)


class ApplyLoudnormPreviewTests(unittest.TestCase):
    def test_preview_uses_single_pass_without_measured_values(self) -> None:
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        apply_result = _mock_subprocess_run_factory()
        with mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run:
            mock_run.side_effect = [probe_result, apply_result]
            apply_loudnorm_preview(Path("input.mp4"), Path("output.mp4"))

        self.assertEqual(mock_run.call_count, 2)
        # Second call (index 1) is the actual ffmpeg encode
        cmd = mock_run.call_args_list[1][0][0]
        af_index = cmd.index("-af")
        filter_str = cmd[af_index + 1]
        self.assertIn(f"I={LOUDNORM_I}", filter_str)
        self.assertIn(f"TP={LOUDNORM_TP}", filter_str)
        self.assertIn(f"LRA={LOUDNORM_LRA}", filter_str)
        self.assertNotIn("measured_I", filter_str)
        self.assertNotIn("linear=true", filter_str)

    def test_preview_copies_video_and_encodes_audio(self) -> None:
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        apply_result = _mock_subprocess_run_factory()
        with mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run:
            mock_run.side_effect = [probe_result, apply_result]
            apply_loudnorm_preview(Path("input.mp4"), Path("output.mp4"))

        cmd = mock_run.call_args_list[1][0][0]
        self.assertIn("-c:v", cmd)
        cv_index = cmd.index("-c:v")
        self.assertEqual(cmd[cv_index + 1], "copy")
        self.assertIn("-c:a", cmd)
        ca_index = cmd.index("-c:a")
        self.assertEqual(cmd[ca_index + 1], "aac")
        self.assertIn("-movflags", cmd)

    def test_preview_omits_video_copy_for_audio_only(self) -> None:
        probe_result = _mock_subprocess_run_factory(stdout="")
        apply_result = _mock_subprocess_run_factory()
        with mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run:
            mock_run.side_effect = [probe_result, apply_result]
            apply_loudnorm_preview(Path("input.wav"), Path("output.mp4"))

        cmd = mock_run.call_args_list[1][0][0]
        self.assertNotIn("-c:v", cmd)
        self.assertIn("-c:a", cmd)
        self.assertIn("-movflags", cmd)


class ParseArgsTests(unittest.TestCase):
    def test_requires_input_and_output(self) -> None:
        with mock.patch.object(sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4"]):
            args = parse_args()

        self.assertEqual(args.input, "input.mp4")
        self.assertEqual(args.output, "output.mp4")
        self.assertFalse(args.preview)

    def test_preview_flag(self) -> None:
        with mock.patch.object(
            sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4", "--preview"]
        ):
            args = parse_args()

        self.assertTrue(args.preview)

    def test_custom_ffmpeg_bin(self) -> None:
        with mock.patch.object(
            sys, "argv",
            ["media-loudnorm", "input.mp4", "-o", "output.mp4", "--ffmpeg-bin", "/opt/bin/ffmpeg"],
        ):
            args = parse_args()

        self.assertEqual(args.ffmpeg_bin, "/opt/bin/ffmpeg")

    def test_default_ffmpeg_bin(self) -> None:
        with mock.patch.object(sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4"]):
            args = parse_args()

        self.assertEqual(args.ffmpeg_bin, "ffmpeg")

    def test_custom_ffprobe_bin(self) -> None:
        with mock.patch.object(
            sys, "argv",
            ["media-loudnorm", "input.mp4", "-o", "output.mp4", "--ffprobe-bin", "/opt/bin/ffprobe"],
        ):
            args = parse_args()

        self.assertEqual(args.ffprobe_bin, "/opt/bin/ffprobe")

    def test_default_ffprobe_bin(self) -> None:
        with mock.patch.object(sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4"]):
            args = parse_args()

        self.assertEqual(args.ffprobe_bin, "ffprobe")


class MainTests(unittest.TestCase):
    def test_returns_1_for_missing_input_file(self) -> None:
        with mock.patch.object(
            sys, "argv", ["media-loudnorm", "/nonexistent/file.mp4", "-o", "output.mp4"]
        ):
            result = main()

        self.assertEqual(result, 1)

    def test_two_pass_mode_on_success(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr=SAMPLE_MEASUREMENT_JSON)
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        apply_result = _mock_subprocess_run_factory()
        with (
            mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run,
            mock.patch.object(sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4"]),
            mock.patch("pathlib.Path.exists", return_value=True),
        ):
            mock_run.side_effect = [measure_result, probe_result, apply_result]
            result = main()

        self.assertEqual(result, 0)

    def test_falls_back_to_preview_when_measurement_fails(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr="no json")
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        preview_result = _mock_subprocess_run_factory()
        with (
            mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run,
            mock.patch.object(sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4"]),
            mock.patch("pathlib.Path.exists", return_value=True),
        ):
            mock_run.side_effect = [measure_result, probe_result, preview_result]
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(mock_run.call_count, 3)

    def test_preview_mode_skips_measurement(self) -> None:
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        preview_result = _mock_subprocess_run_factory()
        with (
            mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run,
            mock.patch.object(
                sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4", "--preview"]
            ),
            mock.patch("pathlib.Path.exists", return_value=True),
        ):
            mock_run.side_effect = [probe_result, preview_result]
            result = main()

        self.assertEqual(result, 0)
        self.assertEqual(mock_run.call_count, 2)

    def test_returns_1_on_ffmpeg_failure(self) -> None:
        measure_result = _mock_subprocess_run_factory(stderr=SAMPLE_MEASUREMENT_JSON)
        probe_result = _mock_subprocess_run_factory(stdout="video\n")
        apply_error = subprocess.CalledProcessError(1, "ffmpeg", stderr="encoding error")
        with (
            mock.patch("media_tooling.loudnorm.subprocess.run") as mock_run,
            mock.patch.object(sys, "argv", ["media-loudnorm", "input.mp4", "-o", "output.mp4"]),
            mock.patch("pathlib.Path.exists", return_value=True),
        ):
            mock_run.side_effect = [measure_result, probe_result, apply_error]
            result = main()

        self.assertEqual(result, 1)


@unittest.skipUnless(shutil.which("ffmpeg"), "requires ffmpeg")
@unittest.skipUnless(shutil.which("ffprobe"), "requires ffprobe")
class IntegrationTests(unittest.TestCase):
    tmpdir: str
    audio_input: Path

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.audio_input = Path(cls.tmpdir) / "sine.wav"
        # Generate a 2-second 440 Hz sine wave as WAV
        subprocess.run(
            [
                "ffmpeg", "-y", "-f", "lavfi",
                "-i", "sine=frequency=440:duration=2",
                "-ar", "44100", "-ac", "1",
                str(cls.audio_input),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        import shutil as shutil_mod

        shutil_mod.rmtree(cls.tmpdir, ignore_errors=True)

    def test_two_pass_on_audio_only_input(self) -> None:
        output = Path(self.tmpdir) / "normalized_audio.mp4"
        result = main_with_args([
            "media-loudnorm",
            str(self.audio_input),
            "-o", str(output),
        ])
        self.assertEqual(result, 0)
        self.assertTrue(output.exists())
        self.assertGreater(output.stat().st_size, 0)

    def test_preview_on_audio_only_input(self) -> None:
        output = Path(self.tmpdir) / "preview_audio.mp4"
        result = main_with_args([
            "media-loudnorm",
            str(self.audio_input),
            "-o", str(output),
            "--preview",
        ])
        self.assertEqual(result, 0)
        self.assertTrue(output.exists())
        self.assertGreater(output.stat().st_size, 0)

    def test_has_video_stream_on_audio_file(self) -> None:
        self.assertFalse(has_video_stream(self.audio_input))


def main_with_args(argv: list[str]) -> int:
    """Run main() with a specific argv without mutating sys.argv."""
    with mock.patch.object(sys, "argv", argv):
        return main()


if __name__ == "__main__":
    unittest.main()