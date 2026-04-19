from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.verify import (
    Finding,
    VerifyReport,
    extract_cut_boundaries,
    parse_args,
    verify_audio_pop,
    verify_duration,
    verify_grade_consistency,
    verify_visual_discontinuity,
)

# ── Minimal EDL fixture ──────────────────────────────────────────────────────


def _minimal_edl() -> dict:
    return {
        "version": 1,
        "sources": ["source1.mp4"],
        "ranges": [
            {"source": "source1.mp4", "start": 0.0, "end": 10.0},
            {"source": "source1.mp4", "start": 20.0, "end": 30.0},
            {"source": "source1.mp4", "start": 40.0, "end": 50.0},
        ],
        "total_duration_s": 30.0,
    }


def _single_range_edl() -> dict:
    return {
        "version": 1,
        "sources": ["source1.mp4"],
        "ranges": [
            {"source": "source1.mp4", "start": 0.0, "end": 15.0},
        ],
        "total_duration_s": 15.0,
    }


# ── extract_cut_boundaries ───────────────────────────────────────────────────


class TestExtractCutBoundaries(unittest.TestCase):
    def test_multi_range_produces_boundaries(self) -> None:
        boundaries = extract_cut_boundaries(_minimal_edl())
        # Three ranges of 10s each → boundaries at 10.0 and 20.0
        self.assertEqual(len(boundaries), 2)
        self.assertAlmostEqual(boundaries[0], 10.0)
        self.assertAlmostEqual(boundaries[1], 20.0)

    def test_single_range_no_internal_boundaries(self) -> None:
        boundaries = extract_cut_boundaries(_single_range_edl())
        self.assertEqual(boundaries, [])

    def test_empty_ranges(self) -> None:
        boundaries = extract_cut_boundaries({"ranges": []})
        self.assertEqual(boundaries, [])

    def test_two_ranges_one_boundary(self) -> None:
        edl = {
            "ranges": [
                {"source": "a.mp4", "start": 0.0, "end": 5.0},
                {"source": "a.mp4", "start": 10.0, "end": 25.0},
            ]
        }
        boundaries = extract_cut_boundaries(edl)
        self.assertEqual(len(boundaries), 1)
        self.assertAlmostEqual(boundaries[0], 5.0)

    def test_unequal_durations(self) -> None:
        edl = {
            "ranges": [
                {"source": "a.mp4", "start": 0.0, "end": 3.0},
                {"source": "a.mp4", "start": 5.0, "end": 15.0},
                {"source": "a.mp4", "start": 20.0, "end": 20.5},
            ]
        }
        boundaries = extract_cut_boundaries(edl)
        self.assertEqual(len(boundaries), 2)
        self.assertAlmostEqual(boundaries[0], 3.0)
        self.assertAlmostEqual(boundaries[1], 13.0)  # 3 + 10


# ── verify_duration ──────────────────────────────────────────────────────────


class TestVerifyDuration(unittest.TestCase):
    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    def test_duration_matches(self, mock_probe: MagicMock) -> None:
        finding = verify_duration(Path("video.mp4"), _minimal_edl())
        self.assertTrue(finding.passed)
        self.assertEqual(finding.check, "duration")
        self.assertIn("30.000s", finding.details)

    @patch("media_tooling.verify.probe_duration", return_value=31.0)
    def test_duration_within_tolerance(self, mock_probe: MagicMock) -> None:
        finding = verify_duration(Path("video.mp4"), _minimal_edl(), tolerance=1.5)
        self.assertTrue(finding.passed)

    @patch("media_tooling.verify.probe_duration", return_value=35.0)
    def test_duration_outside_tolerance(self, mock_probe: MagicMock) -> None:
        finding = verify_duration(Path("video.mp4"), _minimal_edl())
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "fail")

    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    def test_missing_total_duration_field(self, mock_probe: MagicMock) -> None:
        edl = _minimal_edl()
        del edl["total_duration_s"]
        finding = verify_duration(Path("video.mp4"), edl)
        self.assertTrue(finding.passed)
        self.assertIn("no total_duration_s", finding.details)

    @patch("media_tooling.verify.probe_duration", side_effect=RuntimeError("ffprobe failed"))
    def test_ffprobe_failure(self, mock_probe: MagicMock) -> None:
        finding = verify_duration(Path("video.mp4"), _minimal_edl())
        self.assertFalse(finding.passed)
        self.assertIn("ffprobe failed", finding.details)

    @patch("media_tooling.verify.probe_duration", return_value=30.1)
    def test_custom_tolerance(self, mock_probe: MagicMock) -> None:
        finding = verify_duration(
            Path("video.mp4"), _minimal_edl(), tolerance=0.2
        )
        self.assertTrue(finding.passed)


# ── Finding / VerifyReport ───────────────────────────────────────────────────


class TestFindingAndReport(unittest.TestCase):
    def test_finding_to_dict(self) -> None:
        f = Finding(check="test", passed=True, details="ok", severity="info")
        d = f.to_dict()
        self.assertEqual(d["check"], "test")
        self.assertTrue(d["passed"])
        self.assertIsNone(d["cut_time"])

    def test_finding_with_cut_time(self) -> None:
        f = Finding(
            check="visual_discontinuity", passed=False, details="jump",
            severity="fail", cut_time=10.0,
        )
        d = f.to_dict()
        self.assertEqual(d["cut_time"], 10.0)

    def test_report_starts_as_passed(self) -> None:
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        self.assertTrue(report.passed)
        self.assertEqual(report.pass_count, 0)

    def test_report_add_pass(self) -> None:
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        report.add(Finding(check="x", passed=True, details="ok"))
        self.assertEqual(report.pass_count, 1)
        self.assertTrue(report.passed)

    def test_report_add_fail(self) -> None:
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        report.add(Finding(check="x", passed=False, details="bad", severity="fail"))
        self.assertEqual(report.fail_count, 1)
        self.assertFalse(report.passed)

    def test_report_to_dict(self) -> None:
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        report.add(Finding(check="c", passed=True, details="ok"))
        d = report.to_dict()
        self.assertIn("findings", d)
        self.assertEqual(len(d["findings"]), 1)
        self.assertTrue(d["passed"])


# ── verify_visual_discontinuity ───────────────────────────────────────────────


class TestVerifyVisualDiscontinuity(unittest.TestCase):
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    def test_no_discontinuity(self, mock_delta: MagicMock, mock_extract: MagicMock) -> None:
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            video = Path(f.name)
            # Create fake frame files
            mock_extract.return_value = Path("/tmp/frame.jpg")
            finding = verify_visual_discontinuity(video, 10.0)
            self.assertTrue(finding.passed)
            self.assertEqual(finding.check, "visual_discontinuity")

    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.40)
    def test_discontinuity_detected(self, mock_delta: MagicMock, mock_extract: MagicMock) -> None:
        mock_extract.return_value = Path("/tmp/frame.jpg")
        finding = verify_visual_discontinuity(Path("video.mp4"), 10.0)
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "fail")

    @patch("media_tooling.verify._extract_single_frame", return_value=None)
    def test_frame_extraction_failure_skips(self, mock_extract: MagicMock) -> None:
        finding = verify_visual_discontinuity(Path("video.mp4"), 10.0)
        self.assertTrue(finding.passed)
        self.assertIn("skipping", finding.details)


# ── verify_audio_pop ─────────────────────────────────────────────────────────


class TestVerifyAudioPop(unittest.TestCase):
    @patch("media_tooling.verify.compute_envelope")
    def test_no_pop(self, mock_env: MagicMock) -> None:
        import numpy as np
        # Smooth envelope, no spike
        mock_env.return_value = np.full(500, 0.3, dtype=np.float32)
        finding = verify_audio_pop(Path("video.mp4"), 10.0)
        self.assertTrue(finding.passed)

    @patch("media_tooling.verify.compute_envelope")
    def test_pop_near_cut(self, mock_env: MagicMock) -> None:
        import numpy as np
        env = np.full(500, 0.3, dtype=np.float32)
        # Spike at the cut point (middle of envelope ≈ cut_time)
        env[250] = 0.95
        mock_env.return_value = env
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        self.assertFalse(finding.passed)

    @patch("media_tooling.verify.compute_envelope")
    def test_pop_far_from_cut_ignored(self, mock_env: MagicMock) -> None:
        import numpy as np
        env = np.full(500, 0.3, dtype=np.float32)
        # Spike at the very start (far from cut at center)
        env[0] = 0.95
        mock_env.return_value = env
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        # The spike is at the start of the window, which is 1.5s before the cut
        # That's > 0.5s away, so it should pass
        self.assertTrue(finding.passed)

    @patch("media_tooling.verify.compute_envelope", side_effect=RuntimeError("no audio"))
    def test_envelope_failure(self, mock_env: MagicMock) -> None:
        finding = verify_audio_pop(Path("video.mp4"), 10.0)
        self.assertTrue(finding.passed)
        self.assertIn("skipping", finding.details)

    @patch("media_tooling.verify.compute_envelope")
    def test_silent_track(self, mock_env: MagicMock) -> None:
        import numpy as np
        mock_env.return_value = np.zeros(500, dtype=np.float32)
        finding = verify_audio_pop(Path("video.mp4"), 10.0)
        self.assertTrue(finding.passed)


# ── verify_grade_consistency ──────────────────────────────────────────────────


class TestVerifyGradeConsistency(unittest.TestCase):
    @patch("media_tooling.verify._sample_luminance", return_value=0.5)
    def test_consistent_grade(self, mock_lum: MagicMock) -> None:
        finding = verify_grade_consistency(Path("video.mp4"), 60.0)
        self.assertTrue(finding.passed)
        self.assertEqual(finding.check, "grade_consistency")

    @patch("media_tooling.verify._sample_luminance")
    def test_inconsistent_grade(self, mock_lum: MagicMock) -> None:
        # Alternate between bright and dark
        mock_lum.side_effect = [0.2, 0.7, 0.2, 0.7, 0.2]
        finding = verify_grade_consistency(
            Path("video.mp4"), 60.0, tolerance=0.15
        )
        self.assertFalse(finding.passed)

    def test_short_video_skips(self) -> None:
        finding = verify_grade_consistency(Path("video.mp4"), 2.0)
        self.assertTrue(finding.passed)
        self.assertIn("too short", finding.details)

    @patch("media_tooling.verify._sample_luminance", return_value=None)
    def test_no_frames_extracted(self, mock_lum: MagicMock) -> None:
        finding = verify_grade_consistency(Path("video.mp4"), 60.0)
        self.assertTrue(finding.passed)
        self.assertIn("Insufficient", finding.details)


# ── parse_args ────────────────────────────────────────────────────────────────


class TestParseArgs(unittest.TestCase):
    def test_basic_invocation(self) -> None:
        args = parse_args(["video.mp4", "--edl", "edl.json"])
        self.assertEqual(args.video, "video.mp4")
        self.assertEqual(args.edl, "edl.json")
        self.assertEqual(args.max_passes, 3)

    def test_max_passes_flag(self) -> None:
        args = parse_args(["video.mp4", "--edl", "edl.json", "--max-passes", "5"])
        self.assertEqual(args.max_passes, 5)

    def test_no_timelines_flag(self) -> None:
        args = parse_args(["video.mp4", "--edl", "edl.json", "--no-timelines"])
        self.assertTrue(args.no_timelines)

    def test_json_output_flag(self) -> None:
        args = parse_args(["video.mp4", "--edl", "edl.json", "--json"])
        self.assertTrue(args.json)

    def test_output_dir_flag(self) -> None:
        args = parse_args(["video.mp4", "--edl", "edl.json", "--output-dir", "/tmp/out"])
        self.assertEqual(args.output_dir, "/tmp/out")

    def test_ffmpeg_bin_flag(self) -> None:
        args = parse_args(["video.mp4", "--edl", "edl.json", "--ffmpeg-bin", "/usr/local/bin/ffmpeg"])
        self.assertEqual(args.ffmpeg_bin, "/usr/local/bin/ffmpeg")


# ── Full report format ───────────────────────────────────────────────────────


class TestReportFormat(unittest.TestCase):
    def test_report_json_output(self) -> None:
        report = VerifyReport(video="test.mp4", edl="edl.json", passed=True)
        report.add(Finding(check="duration", passed=True, details="ok"))
        report.add(Finding(check="visual_discontinuity", passed=False,
                           details="jump at 5s", severity="fail", cut_time=5.0))
        d = report.to_dict()

        # Verify structure
        self.assertIn("video", d)
        self.assertIn("edl", d)
        self.assertIn("passed", d)
        self.assertIn("pass_count", d)
        self.assertIn("fail_count", d)
        self.assertIn("findings", d)
        self.assertFalse(d["passed"])  # one failure
        self.assertEqual(d["pass_count"], 1)
        self.assertEqual(d["fail_count"], 1)
        self.assertEqual(len(d["findings"]), 2)

        # Verify finding structure
        f0 = d["findings"][0]
        self.assertEqual(f0["check"], "duration")
        self.assertTrue(f0["passed"])
        self.assertIn("severity", f0)

        f1 = d["findings"][1]
        self.assertEqual(f1["check"], "visual_discontinuity")
        self.assertFalse(f1["passed"])
        self.assertEqual(f1["cut_time"], 5.0)


if __name__ == "__main__":
    unittest.main()