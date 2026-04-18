from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from media_tooling.rough_cut import (
    build_afade_filter,
    build_card_segment,
    build_clip_segment,
    build_image_segment,
    parse_time_to_seconds,
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


if __name__ == "__main__":
    unittest.main()