from __future__ import annotations

import unittest

from media_tooling.subtitle import (
    SUBTITLE_MAX_DURATION_SECONDS,
    maybe_correct_suspicious_timestamps,
    resegment_for_subtitles,
)


class TimestampCorrectionTests(unittest.TestCase):
    def test_applies_observed_ten_x_correction_for_mlx(self) -> None:
        segments = [
            {
                "start": 0.0,
                "end": 30.0,
                "text": "one",
                "words": [
                    {"word": "one", "start": 0.0, "end": 30.0},
                ],
            },
            {"start": 30.0, "end": 286.853, "text": "two", "words": []},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=2868.551959,
            backend="mlx",
            enabled=True,
        )

        self.assertTrue(correction["applied"])
        self.assertAlmostEqual(correction["scale_factor"], 10.000076551, places=6)
        self.assertAlmostEqual(corrected[0]["end"], 300.002, places=3)
        self.assertAlmostEqual(corrected[-1]["end"], 2868.552, places=3)
        self.assertAlmostEqual(corrected[0]["words"][0]["start"], 0.0, places=3)
        self.assertAlmostEqual(corrected[0]["words"][0]["end"], 300.002, places=3)

    def test_skips_non_mlx_backends(self) -> None:
        segments = [
            {"start": 0.0, "end": 30.0, "text": "one"},
            {"start": 30.0, "end": 286.853, "text": "two"},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=2868.551959,
            backend="faster-whisper",
            enabled=True,
        )

        self.assertFalse(correction["applied"])
        self.assertEqual(corrected, segments)

    def test_skips_ratio_close_to_one(self) -> None:
        segments = [
            {"start": 0.0, "end": 15.0, "text": "one"},
            {"start": 15.0, "end": 60.0, "text": "two"},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=60.004,
            backend="mlx",
            enabled=True,
        )

        self.assertFalse(correction["applied"])
        self.assertEqual(correction["reason"], "ratio-close-to-1")
        self.assertEqual(corrected, segments)

    def test_skips_other_integer_ratios_for_mlx(self) -> None:
        segments = [
            {"start": 0.0, "end": 10.0, "text": "one"},
            {"start": 10.0, "end": 30.0, "text": "two"},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=60.0,
            backend="mlx",
            enabled=True,
        )

        self.assertFalse(correction["applied"])
        self.assertEqual(
            correction["reason"], "ratio-does-not-match-observed-mlx-compression"
        )
        self.assertEqual(corrected, segments)


class SubtitleResegmentationTests(unittest.TestCase):
    def test_resegments_long_segment_with_word_timestamps(self) -> None:
        segment = {
            "start": 0.0,
            "end": 12.0,
            "text": "Hello everyone, thanks for joining. Today we will review the workflow. Then we will discuss next steps.",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 1.0},
                {"word": " everyone,", "start": 1.0, "end": 2.0},
                {"word": " thanks", "start": 2.0, "end": 3.0},
                {"word": " for", "start": 3.0, "end": 4.0},
                {"word": " joining.", "start": 4.0, "end": 5.0},
                {"word": " Today", "start": 5.0, "end": 6.0},
                {"word": " we", "start": 6.0, "end": 7.0},
                {"word": " will", "start": 7.0, "end": 8.0},
                {"word": " review", "start": 8.0, "end": 9.0},
                {"word": " the", "start": 9.0, "end": 10.0},
                {"word": " workflow.", "start": 10.0, "end": 11.0},
                {"word": " Then", "start": 11.0, "end": 11.5},
                {"word": " we", "start": 11.5, "end": 11.75},
                {"word": " will", "start": 11.75, "end": 11.9},
                {"word": " discuss", "start": 11.9, "end": 11.95},
                {"word": " next", "start": 11.95, "end": 11.98},
                {"word": " steps.", "start": 11.98, "end": 12.0},
            ],
        }

        refined, metadata = resegment_for_subtitles([segment])

        self.assertTrue(metadata["used_word_timestamps"])
        self.assertGreater(len(refined), 1)
        self.assertTrue(
            all(
                subtitle["end"] - subtitle["start"] <= SUBTITLE_MAX_DURATION_SECONDS
                for subtitle in refined
            )
        )
        self.assertEqual(refined[0]["text"], "Hello everyone, thanks for joining.")

    def test_resegments_long_segment_without_word_timestamps(self) -> None:
        segment = {
            "start": 0.0,
            "end": 12.0,
            "text": "This is a deliberately long subtitle segment without word timestamps so it should still be split into shorter readable captions for video.",
            "words": [],
        }

        refined, metadata = resegment_for_subtitles([segment])

        self.assertFalse(metadata["used_word_timestamps"])
        self.assertGreater(len(refined), 1)
        self.assertTrue(
            all(
                subtitle["end"] - subtitle["start"] <= SUBTITLE_MAX_DURATION_SECONDS
                for subtitle in refined
            )
        )
        self.assertEqual(refined[0]["start"], 0.0)
        self.assertEqual(refined[-1]["end"], 12.0)


if __name__ == "__main__":
    unittest.main()
