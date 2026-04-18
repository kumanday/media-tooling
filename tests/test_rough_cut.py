from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_tooling.rough_cut import (
    AssemblyMethodError,
    build_afade_filter,
    build_card_segment,
    build_clip_segment,
    build_image_segment,
    parse_time_to_seconds,
    validate_concat_demuxer_usage,
)


class ParseTimeToSecondsTest(unittest.TestCase):
    def test_plain_seconds(self) -> None:
        self.assertAlmostEqual(parse_time_to_seconds("90.5"), 90.5)

    def test_integer_seconds(self) -> None:
        self.assertAlmostEqual(parse_time_to_seconds("30"), 30.0)

    def test_float_value(self) -> None:
        self.assertAlmostEqual(parse_time_to_seconds(90.5), 90.5)

    def test_mm_ss(self) -> None:
        self.assertAlmostEqual(parse_time_to_seconds("01:30"), 90.0)

    def test_hh_mm_ss(self) -> None:
        self.assertAlmostEqual(parse_time_to_seconds("00:01:30.5"), 90.5)

    def test_hh_mm_ss_integer(self) -> None:
        self.assertAlmostEqual(parse_time_to_seconds("01:02:03"), 3723.0)

    def test_unrecognised_format_raises(self) -> None:
        with self.assertRaises(ValueError):
            parse_time_to_seconds("1:2:3:4")


class BuildAfadeFilterTest(unittest.TestCase):
    def test_typical_duration(self) -> None:
        result = build_afade_filter(start=0, end=10)
        self.assertEqual(
            result,
            "afade=t=in:st=0:d=0.03,afade=t=out:st=9.97:d=0.03",
        )

    def test_timecode_inputs(self) -> None:
        result = build_afade_filter(start="00:00:05", end="00:00:15")
        self.assertEqual(
            result,
            "afade=t=in:st=0:d=0.03,afade=t=out:st=9.97:d=0.03",
        )

    def test_short_duration_returns_empty(self) -> None:
        result = build_afade_filter(start=0, end=0.05)
        self.assertEqual(result, "")

    def test_exact_minimum_duration(self) -> None:
        # Duration of exactly 0.06 (2 * fade duration) should produce fades
        result = build_afade_filter(start=0, end=0.06)
        self.assertEqual(
            result,
            "afade=t=in:st=0:d=0.03,afade=t=out:st=0.03:d=0.03",
        )

    def test_just_below_minimum_duration(self) -> None:
        result = build_afade_filter(start=0, end=0.059)
        self.assertEqual(result, "")

    def test_string_seconds(self) -> None:
        result = build_afade_filter(start="5", end="25")
        self.assertEqual(
            result,
            "afade=t=in:st=0:d=0.03,afade=t=out:st=19.97:d=0.03",
        )


class ClipSegmentAfadeTest(unittest.TestCase):
    """Verify that clip segments include the afade filter in the ffmpeg command."""

    @patch("media_tooling.rough_cut.has_audio", return_value=True)
    @patch("media_tooling.rough_cut.run_command")
    def test_clip_with_audio_includes_afade(
        self, mock_run: unittest.mock.MagicMock, mock_has_audio: unittest.mock.MagicMock
    ) -> None:
        build_clip_segment(
            segment={"name": "clip1", "type": "clip", "input": "/tmp/input.mp4", "start": "5", "end": "15"},
            output_path=Path("/tmp/out.mp4"),
            ffmpeg_bin="ffmpeg",
            ffprobe_bin="ffprobe",
        )
        args = mock_run.call_args[0][0]
        af_index = args.index("-af")
        afade_value = args[af_index + 1]
        self.assertIn("afade=t=in:st=0:d=0.03", afade_value)
        self.assertIn("afade=t=out:st=9.97:d=0.03", afade_value)

    @patch("media_tooling.rough_cut.has_audio", return_value=False)
    @patch("media_tooling.rough_cut.run_command")
    def test_clip_without_audio_omits_afade(
        self, mock_run: unittest.mock.MagicMock, mock_has_audio: unittest.mock.MagicMock
    ) -> None:
        """Clips with no audio track should not have -af (fading silence is a no-op)."""
        build_clip_segment(
            segment={"name": "clip2", "type": "clip", "input": "/tmp/input.mp4", "start": "0", "end": "10"},
            output_path=Path("/tmp/out.mp4"),
            ffmpeg_bin="ffmpeg",
            ffprobe_bin="ffprobe",
        )
        args = mock_run.call_args[0][0]
        self.assertNotIn("-af", args)

    @patch("media_tooling.rough_cut.has_audio", return_value=True)
    @patch("media_tooling.rough_cut.run_command")
    def test_very_short_clip_omits_afade(
        self, mock_run: unittest.mock.MagicMock, mock_has_audio: unittest.mock.MagicMock
    ) -> None:
        """Clips shorter than 60ms should not have -af in the command."""
        build_clip_segment(
            segment={"name": "clip3", "type": "clip", "input": "/tmp/input.mp4", "start": "0", "end": "0.05"},
            output_path=Path("/tmp/out.mp4"),
            ffmpeg_bin="ffmpeg",
            ffprobe_bin="ffprobe",
        )
        args = mock_run.call_args[0][0]
        self.assertNotIn("-af", args)


class CardImageSegmentNoAfadeTest(unittest.TestCase):
    """Verify that card and image segments do NOT include afade filters."""

    @patch("media_tooling.rough_cut.render_card_image")
    @patch("media_tooling.rough_cut.run_command")
    def test_card_segment_no_afade(
        self, mock_run: unittest.mock.MagicMock, mock_render: unittest.mock.MagicMock
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            build_card_segment(
                segment={
                    "name": "card1",
                    "type": "card",
                    "duration": 5,
                    "header": "Title",
                    "meta": "",
                    "body": "Body",
                },
                output_path=Path("/tmp/out.mp4"),
                text_dir=Path(tmpdir),
                ffmpeg_bin="ffmpeg",
                font_file="/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            )
        args = mock_run.call_args[0][0]
        self.assertNotIn("-af", args)

    @patch("media_tooling.rough_cut.run_command")
    def test_image_segment_no_afade(self, mock_run: unittest.mock.MagicMock) -> None:
        build_image_segment(
            segment={
                "name": "img1",
                "type": "image",
                "duration": 3,
                "input": "/tmp/image.png",
            },
            output_path=Path("/tmp/out.mp4"),
            ffmpeg_bin="ffmpeg",
        )
        args = mock_run.call_args[0][0]
        self.assertNotIn("-af", args)


class ValidateConcatDemuxerUsageTests(unittest.TestCase):
    def _make_valid_concat_command(self) -> list[str]:
        """Return a valid concat demuxer command (the standard assembly approach)."""
        return [
            "ffmpeg",
            "-y",
            "-fflags", "+genpts",
            "-f", "concat",
            "-safe", "0",
            "-i", "/tmp/manifest.txt",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "48000",
            "-ac", "2",
            "-movflags", "+faststart",
            "/tmp/output.mp4",
        ]

    def test_valid_concat_command_passes(self) -> None:
        """A standard concat demuxer command should pass validation."""
        command = self._make_valid_concat_command()
        validate_concat_demuxer_usage(command)  # should not raise

    def test_concat_with_filter_complex_raises(self) -> None:
        """Concat command with -filter_complex violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        command.extend(["-filter_complex", "[0:v][1:v]xfade=transition=fade:duration=0.5"])
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))
        self.assertIn("-filter_complex", str(ctx.exception))

    def test_concat_with_lavfi_raises(self) -> None:
        """Concat command with -lavfi violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        command.extend(["-lavfi", "concat=n=2:v=1:a=1"])
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))

    def test_concat_with_xfade_in_filter_complex_raises(self) -> None:
        """xfade inside a -filter_complex value violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        command.extend(["-filter_complex", "[0:v][1:v]xfade=transition=fade:duration=0.5"])
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))
        self.assertIn("-filter_complex", str(ctx.exception))

    def test_concat_with_acrossfade_in_lavfi_raises(self) -> None:
        """acrossfade inside a -lavfi value violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        command.extend(["-lavfi", "acrossfade=d=1"])
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))

    def test_non_concat_command_passes(self) -> None:
        """Commands that are not concat assembly commands should not be validated."""
        command = [
            "ffmpeg",
            "-y",
            "-ss", "10.0",
            "-to", "20.0",
            "-i", "/tmp/input.mp4",
            "-vf", "scale=1920:1080",
            "-c:v", "libx264",
            "/tmp/segment.mp4",
        ]
        validate_concat_demuxer_usage(command)  # should not raise

    def test_filter_complex_without_concat_passes(self) -> None:
        """-filter_complex without -f concat should not trigger validation."""
        command = [
            "ffmpeg",
            "-y",
            "-i", "/tmp/a.mp4",
            "-i", "/tmp/b.mp4",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=1",
            "/tmp/output.mp4",
        ]
        validate_concat_demuxer_usage(command)  # should not raise

    def test_empty_command_passes(self) -> None:
        """An empty command should pass validation."""
        validate_concat_demuxer_usage([])


if __name__ == "__main__":
    unittest.main()
