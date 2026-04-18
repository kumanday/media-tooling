from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.grade import (
    PRESETS,
    _parse_metadata_file,
    _parse_signalstats_value,
    _sample_frame_stats,
    apply_grade,
    auto_grade_for_clip,
    get_preset,
    main,
)


class GetPresetTests(unittest.TestCase):
    def test_subtle_preset(self) -> None:
        result = get_preset("subtle")
        self.assertEqual(result, "eq=contrast=1.03:saturation=0.98")

    def test_neutral_punch_preset(self) -> None:
        result = get_preset("neutral_punch")
        self.assertIn("eq=contrast=1.06", result)
        self.assertIn("curves=master=", result)

    def test_warm_cinematic_preset(self) -> None:
        result = get_preset("warm_cinematic")
        self.assertIn("eq=contrast=1.12", result)
        self.assertIn("saturation=0.88", result)
        self.assertIn("colorbalance=", result)
        self.assertIn("curves=master=", result)

    def test_none_preset_returns_empty(self) -> None:
        result = get_preset("none")
        self.assertEqual(result, "")

    def test_unknown_preset_raises(self) -> None:
        with self.assertRaises(KeyError) as ctx:
            get_preset("nonexistent")
        self.assertIn("nonexistent", str(ctx.exception))

    def test_all_preset_names_are_gettable(self) -> None:
        for name in PRESETS:
            result = get_preset(name)
            self.assertIsInstance(result, str)


class ParseSignalstatsValueTests(unittest.TestCase):
    def test_parses_numeric_value(self) -> None:
        result = _parse_signalstats_value("lavfi.signalstats.YAVG=128.5")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 128.5)  # type: ignore[arg-type]

    def test_parses_integer_value(self) -> None:
        result = _parse_signalstats_value("lavfi.signalstats.YBITDEPTH=8")
        self.assertIsNotNone(result)
        self.assertAlmostEqual(result, 8.0)  # type: ignore[arg-type]

    def test_returns_none_on_bad_value(self) -> None:
        self.assertIsNone(_parse_signalstats_value("lavfi.signalstats.YAVG=abc"))

    def test_returns_none_on_no_equals(self) -> None:
        self.assertIsNone(_parse_signalstats_value("nonsense"))


class ParseMetadataFileTests(unittest.TestCase):
    """Test _parse_metadata_file as a pure function — no mocks needed."""

    def test_empty_file_returns_neutral_defaults(self) -> None:
        """When metadata file is empty, neutral defaults are returned."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            metadata_path = f.name
        try:
            result = _parse_metadata_file(metadata_path)
        finally:
            os.unlink(metadata_path)
        self.assertAlmostEqual(result["y_mean"], 0.5)
        self.assertAlmostEqual(result["y_range"], 0.72)
        self.assertAlmostEqual(result["sat_mean"], 0.25)

    def test_parses_signalstats_metadata(self) -> None:
        """Parse a realistic signalstats metadata file."""
        metadata_lines = [
            "lavfi.signalstats.YBITDEPTH=8\n",
            "lavfi.signalstats.YAVG=128\n",
            "lavfi.signalstats.YMIN=16\n",
            "lavfi.signalstats.YMAX=235\n",
            "lavfi.signalstats.SATAVG=64\n",
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            metadata_path = f.name
            for line in metadata_lines:
                f.write(line)
        try:
            result = _parse_metadata_file(metadata_path)
        finally:
            os.unlink(metadata_path)
        # 8-bit: max_val = 255
        # y_mean = 128/255 ~ 0.502
        self.assertAlmostEqual(result["y_mean"], 128 / 255, places=3)
        # y_range = (235 - 16)/255 ~ 0.859
        self.assertAlmostEqual(result["y_range"], (235 - 16) / 255, places=3)
        # sat_mean = 64/255 ~ 0.251
        self.assertAlmostEqual(result["sat_mean"], 64 / 255, places=3)

    def test_10bit_metadata(self) -> None:
        """10-bit video normalises by 1023, not 255."""
        metadata_lines = [
            "lavfi.signalstats.YBITDEPTH=10\n",
            "lavfi.signalstats.YAVG=512\n",
            "lavfi.signalstats.YMIN=64\n",
            "lavfi.signalstats.YMAX=960\n",
            "lavfi.signalstats.SATAVG=256\n",
        ]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            metadata_path = f.name
            for line in metadata_lines:
                f.write(line)
        try:
            result = _parse_metadata_file(metadata_path)
        finally:
            os.unlink(metadata_path)
        self.assertAlmostEqual(result["y_mean"], 512 / 1023, places=3)
        self.assertAlmostEqual(result["y_range"], (960 - 64) / 1023, places=3)


class SampleFrameStatsTests(unittest.TestCase):
    @patch("media_tooling.grade.subprocess.run")
    def test_delegates_to_parse_metadata_file(self, mock_run: MagicMock) -> None:
        """_sample_frame_stats runs ffmpeg then delegates parsing."""
        mock_run.return_value = MagicMock(returncode=0)
        # Write a real metadata file that the code will read
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            metadata_path = f.name
            f.write("lavfi.signalstats.YBITDEPTH=8\n")
            f.write("lavfi.signalstats.YAVG=128\n")
            f.write("lavfi.signalstats.YMIN=16\n")
            f.write("lavfi.signalstats.YMAX=235\n")
            f.write("lavfi.signalstats.SATAVG=64\n")
        try:
            with patch("media_tooling.grade.tempfile.NamedTemporaryFile") as mock_tf:
                mock_tf.return_value.__enter__ = MagicMock(return_value=MagicMock(name="f"))
                mock_tf.return_value.__enter__().name = metadata_path
                mock_tf.return_value.__exit__ = MagicMock(return_value=False)
                with patch("media_tooling.grade.Path.unlink"):
                    result = _sample_frame_stats(Path("test.mp4"), start=0.0, duration=10.0)
        finally:
            os.unlink(metadata_path)
        self.assertAlmostEqual(result["y_mean"], 128 / 255, places=3)

    @patch("media_tooling.grade.subprocess.run",
           side_effect=FileNotFoundError)
    def test_ffmpeg_not_found_raises_runtime_error(self, mock_run: MagicMock) -> None:
        """Missing ffmpeg during analysis raises RuntimeError."""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as f:
            metadata_path = f.name
        try:
            with patch("media_tooling.grade.tempfile.NamedTemporaryFile") as mock_tf:
                mock_tf.return_value.__enter__ = MagicMock(return_value=MagicMock(name="f"))
                mock_tf.return_value.__enter__().name = metadata_path
                mock_tf.return_value.__exit__ = MagicMock(return_value=False)
                with patch("media_tooling.grade.Path.unlink"):
                    with self.assertRaises(RuntimeError) as ctx:
                        _sample_frame_stats(Path("test.mp4"), start=0.0, duration=10.0)
            self.assertIn("ffmpeg not found", str(ctx.exception))
        finally:
            os.unlink(metadata_path)

    @patch("media_tooling.grade.subprocess.run",
           side_effect=subprocess.CalledProcessError(1, "ffmpeg"))
    def test_ffmpeg_analysis_failure_raises_runtime_error(self, mock_run: MagicMock) -> None:
        """ffmpeg analysis failure raises RuntimeError with context."""
        with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as f:
            metadata_path = f.name
        try:
            with patch("media_tooling.grade.tempfile.NamedTemporaryFile") as mock_tf:
                mock_tf.return_value.__enter__ = MagicMock(return_value=MagicMock(name="f"))
                mock_tf.return_value.__enter__().name = metadata_path
                mock_tf.return_value.__exit__ = MagicMock(return_value=False)
                with patch("media_tooling.grade.Path.unlink"):
                    with self.assertRaises(RuntimeError) as ctx:
                        _sample_frame_stats(Path("test.mp4"), start=0.0, duration=10.0)
            self.assertIn("exit code", str(ctx.exception))
        finally:
            os.unlink(metadata_path)


class AutoGradeForClipTests(unittest.TestCase):
    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_well_balanced_clip_returns_empty_filter(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.72, "sat_mean": 0.25}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        # Well-balanced clip should get no correction (empty filter)
        self.assertEqual(filter_string, "")

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_dark_clip_gets_gamma_lift(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.35, "y_range": 0.72, "sat_mean": 0.25}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        self.assertIn("gamma=", filter_string)

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_flat_clip_gets_contrast_boost(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.40, "sat_mean": 0.25}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        self.assertIn("contrast=", filter_string)

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_contrast_bounded_to_8_percent(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        """Even extremely flat/dark footage should not exceed +/-8% correction."""
        # Very dark + very flat + low saturation -- worst case
        mock_stats.return_value = {"y_mean": 0.10, "y_range": 0.20, "sat_mean": 0.05}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        # Parse the filter to check bounds -- every parameter must be in [0.92, 1.08]
        if filter_string.startswith("eq="):
            parts_str = filter_string[3:]
            parts = parts_str.split(":")
            for part in parts:
                key, val = part.split("=")
                val_f = float(val)
                self.assertLessEqual(val_f, 1.08, f"{key}={val_f} exceeds +8%")
                self.assertGreaterEqual(val_f, 0.92, f"{key}={val_f} exceeds -8%")

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_overexposed_clip_gets_proportional_gamma_pullback(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.70, "y_range": 0.72, "sat_mean": 0.25}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        self.assertIn("gamma=", filter_string)
        # Should be a pullback (gamma < 1.0) and proportional, not fixed
        gamma_val = float(
            filter_string.split("gamma=")[1].split(":")[0].split(",")[0]
        )
        self.assertLess(gamma_val, 1.0)
        self.assertGreater(gamma_val, 0.92)  # within bounds

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_high_saturation_gets_proportional_pullback(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.72, "sat_mean": 0.45}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        self.assertIn("saturation=", filter_string)
        sat_val = float(
            filter_string.split("saturation=")[1].split(":")[0].split(",")[0]
        )
        self.assertLess(sat_val, 1.0)
        self.assertGreater(sat_val, 0.92)  # within bounds

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_low_saturation_gets_proportional_boost(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.72, "sat_mean": 0.08}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        self.assertIn("saturation=", filter_string)
        sat_val = float(
            filter_string.split("saturation=")[1].split(":")[0].split(",")[0]
        )
        self.assertGreater(sat_val, 1.0)
        self.assertLessEqual(sat_val, 1.08)

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_verbose_mode_prints(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.35, "y_range": 0.72, "sat_mean": 0.25}
        with patch("builtins.print") as mock_print:
            auto_grade_for_clip(Path("test.mp4"), verbose=True)
        self.assertTrue(mock_print.called)

    @patch("media_tooling.grade.subprocess.check_output", side_effect=Exception("probe fail"))
    @patch("media_tooling.grade._sample_frame_stats")
    def test_ffprobe_failure_warns_in_verbose(
        self, mock_stats: MagicMock, mock_probe: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.72, "sat_mean": 0.25}
        with patch("builtins.print") as mock_print:
            auto_grade_for_clip(Path("test.mp4"), verbose=True)
        printed = " ".join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        self.assertIn("warning", printed.lower())

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_threshold_continuity(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        """Proportional maps are continuous at threshold boundaries."""
        # Test contrast at y_range=0.65 boundary
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.649, "sat_mean": 0.25}
        f1, _ = auto_grade_for_clip(Path("test.mp4"))
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.651, "sat_mean": 0.25}
        f2, _ = auto_grade_for_clip(Path("test.mp4"))
        # Both should produce very similar results near the boundary
        # f1 has contrast, f2 doesn't — but at boundary contrast should be ~1.0
        # so the jump should be negligible (< 0.5%)
        if f1 and "contrast=" in f1:
            c1 = float(f1.split("contrast=")[1].split(":")[0])
            self.assertLess(abs(c1 - 1.0), 0.005, "contrast at boundary should be ~1.0")


class ApplyGradeTests(unittest.TestCase):
    def _mock_popen(self, returncode: int = 0) -> MagicMock:
        """Create a mock Popen process that simulates successful ffmpeg."""
        mock_proc = MagicMock()
        mock_proc.stderr = iter([])
        mock_proc.wait.return_value = None
        mock_proc.returncode = returncode
        return mock_proc

    @patch("media_tooling.grade.subprocess.Popen")
    def test_reencode_command_includes_filter_and_codec(self, mock_popen: MagicMock) -> None:
        """Re-encode path builds the correct ffmpeg command."""
        mock_popen.return_value = self._mock_popen()
        apply_grade(Path("in.mp4"), Path("out.mp4"), "eq=contrast=1.05")
        cmd = mock_popen.call_args[0][0]
        self.assertIn("libx264", cmd)
        self.assertIn("+faststart", cmd)
        self.assertIn("eq=contrast=1.05", cmd)

    @patch("media_tooling.grade.subprocess.Popen")
    def test_stream_copy_command_uses_copy(self, mock_popen: MagicMock) -> None:
        """Empty filter string triggers stream-copy path with faststart for MP4."""
        mock_popen.return_value = self._mock_popen()
        apply_grade(Path("in.mp4"), Path("out.mp4"), "")
        cmd = mock_popen.call_args[0][0]
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)
        self.assertIn("+faststart", cmd)
        self.assertNotIn("libx264", cmd)

    @patch("media_tooling.grade.subprocess.Popen")
    def test_mkv_output_no_faststart(self, mock_popen: MagicMock) -> None:
        """Non-MP4 containers omit -movflags +faststart."""
        mock_popen.return_value = self._mock_popen()
        apply_grade(Path("in.mp4"), Path("out.mkv"), "eq=contrast=1.05")
        cmd = mock_popen.call_args[0][0]
        self.assertNotIn("+faststart", cmd)

    def test_same_input_output_raises(self) -> None:
        """Input and output resolving to the same file raises ValueError."""
        p = Path("/tmp/same_file.mp4")
        with self.assertRaises(ValueError):
            apply_grade(p, p, "")

    @patch("media_tooling.grade.subprocess.Popen", side_effect=FileNotFoundError)
    def test_ffmpeg_not_found_raises_runtime_error(self, mock_popen: MagicMock) -> None:
        """Missing ffmpeg raises RuntimeError with actionable message."""
        with self.assertRaises(RuntimeError) as ctx:
            apply_grade(Path("in.mp4"), Path("out.mp4"), "")
        self.assertIn("ffmpeg not found", str(ctx.exception))

    def test_ffmpeg_failure_raises_runtime_error(self) -> None:
        """ffmpeg failure raises RuntimeError with exit code info."""
        mock_proc = MagicMock()
        mock_proc.stderr = iter(["error line\n"])
        mock_proc.wait.return_value = None
        mock_proc.returncode = 1
        with patch("media_tooling.grade.subprocess.Popen", return_value=mock_proc):
            with self.assertRaises(RuntimeError) as ctx:
                apply_grade(Path("in.mp4"), Path("out.mp4"), "")
        self.assertIn("exit code", str(ctx.exception))


class CLIMainTests(unittest.TestCase):
    def test_list_presets(self) -> None:
        with patch("builtins.print") as mock_print:
            result = main(["--list-presets"])
        self.assertEqual(result, 0)
        output = "\n".join(str(c) for c in mock_print.call_args_list)
        self.assertIn("subtle", output)
        self.assertIn("warm_cinematic", output)
        self.assertIn("neutral_punch", output)
        self.assertIn("none", output)

    def test_print_preset_subtle(self) -> None:
        with patch("builtins.print") as mock_print:
            result = main(["--print-preset", "subtle"])
        self.assertEqual(result, 0)
        mock_print.assert_called_with("eq=contrast=1.03:saturation=0.98")

    def test_print_preset_none(self) -> None:
        with patch("builtins.print") as mock_print:
            result = main(["--print-preset", "none"])
        self.assertEqual(result, 0)
        mock_print.assert_called_with("")

    def test_print_preset_unknown_fails(self) -> None:
        result = main(["--print-preset", "nonexistent"])
        self.assertEqual(result, 1)

    def test_missing_input_output_fails(self) -> None:
        result = main([])
        self.assertEqual(result, 1)

    def test_custom_filter_passthrough(self) -> None:
        """--filter passes raw ffmpeg filter string directly."""
        with patch("media_tooling.grade.apply_grade") as mock_apply:
            with patch("builtins.print"):
                with patch.object(Path, "exists", return_value=True):
                    result = main(
                        ["input.mp4", "-o", "output.mp4", "--filter", "eq=brightness=0.1"]
                    )
        self.assertEqual(result, 0)
        mock_apply.assert_called_once()
        call_args = mock_apply.call_args
        self.assertEqual(call_args[0][2], "eq=brightness=0.1")

    def test_preset_flag_uses_preset(self) -> None:
        """--preset uses the named preset filter string."""
        with patch("media_tooling.grade.apply_grade") as mock_apply:
            with patch("builtins.print"):
                with patch.object(Path, "exists", return_value=True):
                    result = main(
                        ["input.mp4", "-o", "output.mp4", "--preset", "subtle"]
                    )
        self.assertEqual(result, 0)
        mock_apply.assert_called_once()
        call_args = mock_apply.call_args
        self.assertEqual(call_args[0][2], get_preset("subtle"))

    def test_preset_none_produces_copy(self) -> None:
        """--preset none results in empty filter (stream copy)."""
        with patch("media_tooling.grade.apply_grade") as mock_apply:
            with patch("builtins.print"):
                with patch.object(Path, "exists", return_value=True):
                    result = main(
                        ["input.mp4", "-o", "output.mp4", "--preset", "none"]
                    )
        self.assertEqual(result, 0)
        mock_apply.assert_called_once()
        call_args = mock_apply.call_args
        self.assertEqual(call_args[0][2], "")

    @patch("media_tooling.grade.auto_grade_for_clip")
    def test_default_mode_uses_auto_grade(self, mock_auto: MagicMock) -> None:
        """Without --preset or --filter, auto-grade is used."""
        mock_auto.return_value = ("eq=contrast=1.05", {"y_mean": 0.5})
        with patch("media_tooling.grade.apply_grade") as mock_apply:
            with patch("builtins.print"):
                with patch.object(Path, "exists", return_value=True):
                    result = main(["input.mp4", "-o", "output.mp4"])
        self.assertEqual(result, 0)
        mock_auto.assert_called_once()
        mock_apply.assert_called_once()

    @patch("media_tooling.grade.auto_grade_for_clip")
    def test_start_and_duration_passed_to_auto_grade(self, mock_auto: MagicMock) -> None:
        """--start and --duration are forwarded to auto_grade_for_clip."""
        mock_auto.return_value = ("", {"y_mean": 0.5})
        with patch("media_tooling.grade.apply_grade"):
            with patch("builtins.print"):
                with patch.object(Path, "exists", return_value=True):
                    result = main([
                        "input.mp4", "-o", "output.mp4",
                        "--start", "30", "--duration", "60",
                    ])
        self.assertEqual(result, 0)
        mock_auto.assert_called_once_with(
            Path("input.mp4"), start=30.0, duration=60.0, verbose=True
        )

    @patch("media_tooling.grade.auto_grade_for_clip")
    def test_analyze_uses_start_and_duration(self, mock_auto: MagicMock) -> None:
        """--analyze also passes --start and --duration."""
        mock_auto.return_value = ("", {"y_mean": 0.5})
        with patch("builtins.print"):
            with patch.object(Path, "exists", return_value=True):
                result = main([
                    "--analyze", "input.mp4",
                    "--start", "10", "--duration", "20",
                ])
        self.assertEqual(result, 0)
        mock_auto.assert_called_once_with(
            Path("input.mp4"), start=10.0, duration=20.0, verbose=True
        )

    def test_analyze_nonexistent_file_fails(self) -> None:
        with patch.object(Path, "exists", return_value=False):
            result = main(["--analyze", "nonexistent.mp4"])
        self.assertEqual(result, 1)

    def test_input_nonexistent_file_fails(self) -> None:
        with patch.object(Path, "exists", return_value=False):
            result = main(["nonexistent.mp4", "-o", "output.mp4"])
        self.assertEqual(result, 1)

    @patch("media_tooling.grade.auto_grade_for_clip")
    def test_same_file_valueerror_caught_in_cli(self, mock_auto: MagicMock) -> None:
        """ValueError from apply_grade (same-file guard) is caught by main()."""
        mock_auto.return_value = ("", {"y_mean": 0.5})
        with patch("media_tooling.grade.apply_grade",
                   side_effect=ValueError("same file")):
            with patch("builtins.print"):
                with patch.object(Path, "exists", return_value=True):
                    result = main(["input.mp4", "-o", "output.mp4"])
        self.assertEqual(result, 1)

    @patch("media_tooling.grade.auto_grade_for_clip")
    def test_runtime_error_caught_in_cli(self, mock_auto: MagicMock) -> None:
        """RuntimeError from apply_grade is caught by main()."""
        mock_auto.return_value = ("", {"y_mean": 0.5})
        with patch("media_tooling.grade.apply_grade",
                   side_effect=RuntimeError("ffmpeg failed")):
            with patch("builtins.print"):
                with patch.object(Path, "exists", return_value=True):
                    result = main(["input.mp4", "-o", "output.mp4"])
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
