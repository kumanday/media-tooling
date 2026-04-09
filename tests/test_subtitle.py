from __future__ import annotations

import unittest

from media_tooling.subtitle import maybe_correct_suspicious_timestamps


class TimestampCorrectionTests(unittest.TestCase):
    def test_applies_integer_ratio_correction_for_mlx(self) -> None:
        segments = [
            {"start": 0.0, "end": 30.0, "text": "one"},
            {"start": 30.0, "end": 286.853, "text": "two"},
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


if __name__ == "__main__":
    unittest.main()
