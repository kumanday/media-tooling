from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.grade import (
    PRESETS,
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


class SampleFrameStatsTests(unittest.TestCase):
    @patch("media_tooling.grade.subprocess.run")
    def test_returns_neutral_defaults_when_no_metadata(self, mock_run: MagicMock) -> None:
        """When ffmpeg produces no signalstats output, neutral defaults are returned."""
        mock_run.return_value = MagicMock(returncode=0)
        # Write a real empty metadata file — tests the actual file-reading path
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            metadata_path = f.name
            # Write nothing — empty file
        try:
            with patch("media_tooling.grade.tempfile.NamedTemporaryFile") as mock_tf:
                mock_tf.return_value.__enter__ = MagicMock(return_value=MagicMock(name="f"))
                mock_tf.return_value.__enter__().name = metadata_path
                mock_tf.return_value.__exit__ = MagicMock(return_value=False)
                # Suppress the unlink in the finally block of _sample_frame_stats
                with patch("media_tooling.grade.Path.unlink"):
                    result = _sample_frame_stats(Path("test.mp4"), start=0.0, duration=10.0)
        finally:
            os.unlink(metadata_path)
        self.assertAlmostEqual(result["y_mean"], 0.5)
        self.assertAlmostEqual(result["y_range"], 0.72)
        self.assertAlmostEqual(result["sat_mean"], 0.25)

    @patch("media_tooling.grade.subprocess.run")
    def test_parses_signalstats_metadata(self, mock_run: MagicMock) -> None:
        """Parse a realistic signalstats metadata file."""
        metadata_lines = [
            "lavfi.signalstats.YBITDEPTH=8\n",
            "lavfi.signalstats.YAVG=128\n",
            "lavfi.signalstats.YMIN=16\n",
            "lavfi.signalstats.YMAX=235\n",
            "lavfi.signalstats.SATAVG=64\n",
        ]
        mock_run.return_value = MagicMock(returncode=0)
        # Write real temp file with known content
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            metadata_path = f.name
            for line in metadata_lines:
                f.write(line)
        try:
            with patch("media_tooling.grade.tempfile.NamedTemporaryFile") as mock_tf:
                mock_tf.return_value.__enter__ = MagicMock(return_value=MagicMock(name="f"))
                mock_tf.return_value.__enter__().name = metadata_path
                mock_tf.return_value.__exit__ = MagicMock(return_value=False)
                # Suppress the unlink in the finally block of _sample_frame_stats
                with patch("media_tooling.grade.Path.unlink"):
                    result = _sample_frame_stats(Path("test.mp4"), start=0.0, duration=10.0)
        finally:
            os.unlink(metadata_path)
        # 8-bit: max_val = 255
        # y_mean = 128/255 ≈ 0.502
        self.assertAlmostEqual(result["y_mean"], 128 / 255, places=3)
        # y_range = (235 - 16)/255 ≈ 0.859
        self.assertAlmostEqual(result["y_range"], (235 - 16) / 255, places=3)
        # sat_mean = 64/255 ≈ 0.251
        self.assertAlmostEqual(result["sat_mean"], 64 / 255, places=3)


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
        """Even extremely flat/dark footage should not exceed ±8% correction."""
        # Very dark + very flat + low saturation — worst case
        mock_stats.return_value = {"y_mean": 0.10, "y_range": 0.20, "sat_mean": 0.05}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        # Parse the filter to check bounds — every parameter must be in [0.92, 1.08]
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
    def test_overexposed_clip_gets_gamma_pullback(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.70, "y_range": 0.72, "sat_mean": 0.25}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        self.assertIn("gamma=", filter_string)
        # Should be a pullback (gamma < 1.0)
        self.assertIn("gamma=0.95", filter_string)

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_high_saturation_gets_pullback(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.48, "y_range": 0.72, "sat_mean": 0.45}
        filter_string, stats = auto_grade_for_clip(Path("test.mp4"))
        self.assertIn("saturation=0.94", filter_string)

    @patch("media_tooling.grade._sample_frame_stats")
    @patch("media_tooling.grade.subprocess.check_output")
    def test_verbose_mode_prints(
        self, mock_probe: MagicMock, mock_stats: MagicMock
    ) -> None:
        mock_stats.return_value = {"y_mean": 0.35, "y_range": 0.72, "sat_mean": 0.25}
        with patch("builtins.print") as mock_print:
            auto_grade_for_clip(Path("test.mp4"), verbose=True)
        # Should have printed stats
        self.assertTrue(mock_print.called)


class ApplyGradeTests(unittest.TestCase):
    @patch("media_tooling.grade.subprocess.run")
    def test_reencode_command_includes_filter_and_codec(self, mock_run: MagicMock) -> None:
        """Re-encode path builds the correct ffmpeg command."""
        mock_run.return_value = MagicMock(returncode=0)
        apply_grade(Path("in.mp4"), Path("out.mp4"), "eq=contrast=1.05")
        cmd = mock_run.call_args[0][0]
        self.assertIn("libx264", cmd)
        self.assertIn("+faststart", cmd)
        self.assertIn("eq=contrast=1.05", cmd)

    @patch("media_tooling.grade.subprocess.run")
    def test_stream_copy_command_uses_copy(self, mock_run: MagicMock) -> None:
        """Empty filter string triggers stream-copy path with faststart."""
        mock_run.return_value = MagicMock(returncode=0)
        apply_grade(Path("in.mp4"), Path("out.mp4"), "")
        cmd = mock_run.call_args[0][0]
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)
        self.assertIn("+faststart", cmd)
        # Should NOT contain re-encode flags
        self.assertNotIn("libx264", cmd)

    def test_same_input_output_raises(self) -> None:
        """Input and output resolving to the same file raises ValueError."""
        p = Path("/tmp/same_file.mp4")
        with self.assertRaises(ValueError):
            apply_grade(p, p, "")


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

    def test_analyze_nonexistent_file_fails(self) -> None:
        with patch.object(Path, "exists", return_value=False):
            result = main(["--analyze", "nonexistent.mp4"])
        self.assertEqual(result, 1)

    def test_input_nonexistent_file_fails(self) -> None:
        with patch.object(Path, "exists", return_value=False):
            result = main(["nonexistent.mp4", "-o", "output.mp4"])
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()