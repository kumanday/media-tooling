from __future__ import annotations

import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image

from media_tooling.verify import (
    Finding,
    VerifyReport,
    _compute_frame_delta,
    extract_cut_boundaries,
    parse_args,
    run_verification,
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
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "warning")
        self.assertTrue(finding.non_blocking)
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
        self.assertFalse(d["non_blocking"])

    def test_finding_with_cut_time(self) -> None:
        f = Finding(
            check="visual_discontinuity", passed=False, details="jump",
            severity="fail", cut_time=10.0,
        )
        d = f.to_dict()
        self.assertEqual(d["cut_time"], 10.0)

    def test_finding_non_blocking_to_dict(self) -> None:
        f = Finding(check="x", passed=False, details="info", non_blocking=True)
        d = f.to_dict()
        self.assertTrue(d["non_blocking"])

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

    def test_report_add_non_blocking_fail(self) -> None:
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        report.add(Finding(check="x", passed=False, details="info",
                           severity="warning", non_blocking=True))
        self.assertEqual(report.fail_count, 0)
        self.assertEqual(report.warning_count, 1)
        # non-blocking failure does NOT flip the overall verdict
        self.assertTrue(report.passed)

    def test_report_to_dict(self) -> None:
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        report.add(Finding(check="c", passed=True, details="ok"))
        d = report.to_dict()
        self.assertIn("findings", d)
        self.assertEqual(len(d["findings"]), 1)
        self.assertTrue(d["passed"])
        self.assertIn("warning_count", d)


# ── _compute_frame_delta (real images) ────────────────────────────────────────


class TestComputeFrameDelta(unittest.TestCase):
    def test_identical_frames_return_zero(self) -> None:
        """Two identical images should have delta of 0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            # Create two identical black images
            img = Image.new("RGB", (64, 64), (0, 0, 0))
            path_a = tmp / "a.jpg"
            path_b = tmp / "b.jpg"
            img.save(str(path_a), "JPEG")
            img.save(str(path_b), "JPEG")
            delta = _compute_frame_delta(path_a, path_b)
            assert delta is not None
            self.assertAlmostEqual(delta, 0.0, places=2)

    def test_black_vs_white_returns_high(self) -> None:
        """Black vs white images should have delta close to 1.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            black = Image.new("RGB", (64, 64), (0, 0, 0))
            white = Image.new("RGB", (64, 64), (255, 255, 255))
            path_a = tmp / "black.jpg"
            path_b = tmp / "white.jpg"
            black.save(str(path_a), "JPEG")
            white.save(str(path_b), "JPEG")
            delta = _compute_frame_delta(path_a, path_b)
            # JPEG compression may shift values; delta should be close to 1.0
            assert delta is not None
            self.assertGreater(delta, 0.8)

    def test_similar_frames_return_low(self) -> None:
        """Two slightly different images should have low delta."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            img_a = Image.new("RGB", (64, 64), (128, 128, 128))
            img_b = Image.new("RGB", (64, 64), (130, 130, 130))
            path_a = tmp / "a.png"
            path_b = tmp / "b.png"
            img_a.save(str(path_a), "PNG")
            img_b.save(str(path_b), "PNG")
            delta = _compute_frame_delta(path_a, path_b)
            assert delta is not None
            self.assertLess(delta, 0.05)

    def test_different_sizes_crop_to_min(self) -> None:
        """Frames with different dimensions are cropped to the smaller size."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            img_a = Image.new("RGB", (64, 64), (0, 0, 0))
            img_b = Image.new("RGB", (32, 32), (255, 255, 255))
            path_a = tmp / "a.png"
            path_b = tmp / "b.png"
            img_a.save(str(path_a), "PNG")
            img_b.save(str(path_b), "PNG")
            delta = _compute_frame_delta(path_a, path_b)
            # Should still detect the difference (cropped area is black vs white)
            assert delta is not None
            self.assertGreater(delta, 0.5)

    def test_corrupt_file_returns_none(self) -> None:
        """Corrupt/missing files should return None, not 0.0."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            path_a = tmp / "a.jpg"
            path_b = tmp / "nonexistent.jpg"
            # Create one valid file
            Image.new("RGB", (64, 64), (0, 0, 0)).save(str(path_a), "JPEG")
            delta = _compute_frame_delta(path_a, path_b)
            self.assertIsNone(delta)


# ── verify_visual_discontinuity ───────────────────────────────────────────────


class TestVerifyVisualDiscontinuity(unittest.TestCase):
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    def test_no_discontinuity(self, mock_delta: MagicMock, mock_extract: MagicMock) -> None:
        mock_extract.return_value = Path("/tmp/frame.jpg")
        finding = verify_visual_discontinuity(Path("video.mp4"), 10.0)
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
    def test_frame_extraction_failure_returns_warning(self, mock_extract: MagicMock) -> None:
        finding = verify_visual_discontinuity(Path("video.mp4"), 10.0)
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "warning")
        self.assertTrue(finding.non_blocking)
        self.assertIn("not performed", finding.details)

    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=None)
    def test_frame_comparison_failure_returns_warning(self, mock_delta: MagicMock, mock_extract: MagicMock) -> None:
        mock_extract.return_value = Path("/tmp/frame.jpg")
        finding = verify_visual_discontinuity(Path("video.mp4"), 10.0)
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "warning")
        self.assertTrue(finding.non_blocking)
        self.assertIn("Frame comparison failed", finding.details)


# ── verify_audio_pop ─────────────────────────────────────────────────────────


class TestVerifyAudioPop(unittest.TestCase):
    @patch("media_tooling.verify.compute_envelope")
    def test_no_pop(self, mock_env: MagicMock) -> None:
        # Smooth envelope, no spike; raw_peak high enough to pass the gate
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        finding = verify_audio_pop(Path("video.mp4"), 10.0)
        self.assertTrue(finding.passed)

    @patch("media_tooling.verify.compute_envelope")
    def test_pop_near_cut(self, mock_env: MagicMock) -> None:
        env = np.full(500, 0.3, dtype=np.float32)
        # Spike at the cut point (middle of envelope ≈ cut_time)
        env[250] = 0.95
        mock_env.return_value = (env, 0.3)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        self.assertFalse(finding.passed)

    @patch("media_tooling.verify.compute_envelope")
    def test_pop_far_from_cut_ignored(self, mock_env: MagicMock) -> None:
        env = np.full(500, 0.3, dtype=np.float32)
        # Spike at the very start (far from cut at center)
        env[0] = 0.95
        mock_env.return_value = (env, 0.3)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        # The spike is at the start of the window, which is 1.5s before the cut
        # That's > 0.5s away, so it should pass
        self.assertTrue(finding.passed)

    @patch("media_tooling.verify.compute_envelope")
    def test_moderate_pop_at_cut_with_louder_elsewhere(self, mock_env: MagicMock) -> None:
        """A pop at the cut should be detected even if a louder spike exists far away."""
        env = np.full(500, 0.3, dtype=np.float32)
        # Louder spike far from cut (index 0 = start of window = 1.5s before cut)
        env[0] = 0.95
        # Moderate pop at the cut (index 250 ≈ cut_time for window=1.5)
        env[250] = 0.82
        mock_env.return_value = (env, 0.3)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        # The 0.82 spike at the cut is above threshold (0.80) and within ±0.5s
        self.assertFalse(finding.passed)

    @patch("media_tooling.verify.compute_envelope")
    def test_spike_near_but_outside_proximity_zone_passes(self, mock_env: MagicMock) -> None:
        """A spike just outside ±0.5s proximity zone should pass."""
        env = np.full(500, 0.3, dtype=np.float32)
        # Spike at ~0.6s before the cut (outside 0.5s proximity)
        # Window is 1.5s, so start = 8.5, end = 11.5, cut = 10.0
        # 0.6s before cut = 9.4s → index ≈ (9.4 - 8.5) / 3.0 * 500 = 150
        env[150] = 0.95
        mock_env.return_value = (env, 0.3)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        self.assertTrue(finding.passed)

    @patch("media_tooling.verify.compute_envelope")
    def test_multiple_spikes_near_cut_any_above_threshold_fails(self, mock_env: MagicMock) -> None:
        """Multiple spikes near cut: any above threshold should fail."""
        env = np.full(500, 0.3, dtype=np.float32)
        # Two spikes near the cut, both above threshold
        env[240] = 0.85
        env[260] = 0.90
        mock_env.return_value = (env, 0.3)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        self.assertFalse(finding.passed)
        self.assertIn("max_near_cut", finding.details)

    @patch("media_tooling.verify.compute_envelope", side_effect=RuntimeError("no audio"))
    def test_envelope_failure_returns_warning(self, mock_env: MagicMock) -> None:
        finding = verify_audio_pop(Path("video.mp4"), 10.0)
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "warning")
        self.assertTrue(finding.non_blocking)
        self.assertIn("not performed", finding.details)

    @patch("media_tooling.verify.compute_envelope")
    def test_silent_track_returns_warning(self, mock_env: MagicMock) -> None:
        mock_env.return_value = (np.zeros(500, dtype=np.float32), 0.0)
        finding = verify_audio_pop(Path("video.mp4"), 10.0)
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "warning")
        self.assertTrue(finding.non_blocking)
        self.assertIn("not performed", finding.details)

    @patch("media_tooling.verify.compute_envelope")
    def test_quiet_audio_skips_pop_detection(self, mock_env: MagicMock) -> None:
        """Audio with raw_peak below min_absolute_level is too quiet for meaningful pop detection."""
        # Normalized envelope has a spike at 1.0 (would normally fail), but raw_peak is 0.01
        env = np.full(500, 0.3, dtype=np.float32)
        env[250] = 1.0  # Normalized spike (would fail without the gate)
        mock_env.return_value = (env, 0.01)  # raw_peak=0.01 < MIN_ABSOLUTE_LEVEL=0.05
        finding = verify_audio_pop(Path("video.mp4"), 10.0)
        # Gate should kick in: too quiet to detect pops meaningfully
        self.assertTrue(finding.passed)
        self.assertTrue(finding.non_blocking)
        self.assertIn("too quiet", finding.details)
        self.assertIn("raw_peak=0.0100", finding.details)
        self.assertIn("min_level=0.050", finding.details)

    @patch("media_tooling.verify.compute_envelope")
    def test_quiet_audio_with_custom_min_level(self, mock_env: MagicMock) -> None:
        """Custom min_absolute_level threshold overrides the default."""
        env = np.full(500, 0.3, dtype=np.float32)
        env[250] = 1.0
        # raw_peak=0.08 > default 0.05, but we set min_level=0.10
        mock_env.return_value = (env, 0.08)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, min_absolute_level=0.10)
        self.assertTrue(finding.passed)
        self.assertTrue(finding.non_blocking)
        self.assertIn("too quiet", finding.details)

    @patch("media_tooling.verify.compute_envelope")
    def test_quiet_audio_just_above_gate_still_checked(self, mock_env: MagicMock) -> None:
        """Audio just above the min_absolute_level gate proceeds to normal pop detection."""
        env = np.full(500, 0.3, dtype=np.float32)
        env[250] = 0.95  # Spike above threshold
        # raw_peak=0.06 > 0.05 default, so gate doesn't skip
        mock_env.return_value = (env, 0.06)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        # Should NOT skip - raw_peak above gate, and spike at cut fails
        self.assertFalse(finding.passed)
        self.assertIn("raw_peak=0.0600", finding.details)

    @patch("media_tooling.verify.compute_envelope")
    def test_loud_audio_pop_detected_despite_normalized_spike(self, mock_env: MagicMock) -> None:
        """Loud audio with a real pop at cut boundary is correctly detected."""
        env = np.full(500, 0.3, dtype=np.float32)
        env[250] = 0.95
        # raw_peak=0.30 (well above 0.05 gate), so pop detection proceeds normally
        mock_env.return_value = (env, 0.30)
        finding = verify_audio_pop(Path("video.mp4"), 10.0, window=1.5)
        self.assertFalse(finding.passed)
        self.assertIn("raw_peak=0.3000", finding.details)


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
        self.assertFalse(finding.passed)
        self.assertEqual(finding.severity, "warning")
        self.assertTrue(finding.non_blocking)
        self.assertIn("too short", finding.details)

    @patch("media_tooling.verify._sample_luminance", return_value=None)
    def test_no_frames_extracted(self, mock_lum: MagicMock) -> None:
        finding = verify_grade_consistency(Path("video.mp4"), 60.0)
        self.assertFalse(finding.passed)
        self.assertIn("Insufficient", finding.details)
        self.assertEqual(finding.severity, "warning")
        self.assertTrue(finding.non_blocking)


# ── run_verification (integration) ───────────────────────────────────────────


class TestRunVerification(unittest.TestCase):
    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    @patch("media_tooling.verify._sample_luminance", return_value=0.5)
    def test_all_passing(
        self,
        mock_lum: MagicMock,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        mock_extract.return_value = Path("/tmp/frame.jpg")
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            generate_timelines=False,
        )
        self.assertTrue(report.passed)
        self.assertEqual(report.fail_count, 0)

    @patch("media_tooling.verify.probe_duration", return_value=35.0)
    def test_duration_failure_reported(
        self,
        mock_probe: MagicMock,
    ) -> None:
        report = run_verification(
            Path("video.mp4"),
            _single_range_edl(),
            generate_timelines=False,
        )
        # Duration mismatch: expected 15s, actual 35s
        self.assertFalse(report.passed)
        duration_findings = [f for f in report.findings if f.check == "duration"]
        self.assertEqual(len(duration_findings), 1)
        self.assertFalse(duration_findings[0].passed)

    @patch("media_tooling.verify.probe_duration", side_effect=RuntimeError("ffprobe failed"))
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    def test_grade_consistency_warning_when_probe_fails(
        self,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """When probe_duration fails, grade_consistency emits a warning finding."""
        mock_extract.return_value = Path("/tmp/frame.jpg")
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        report = run_verification(
            Path("video.mp4"),
            _single_range_edl(),
            generate_timelines=False,
        )
        grade_findings = [f for f in report.findings
                          if f.check == "grade_consistency"]
        self.assertEqual(len(grade_findings), 1)
        self.assertFalse(grade_findings[0].passed)
        self.assertEqual(grade_findings[0].severity, "warning")
        self.assertTrue(grade_findings[0].non_blocking)
        self.assertIn("duration unavailable", grade_findings[0].details)

    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta")
    def test_max_passes_limits_retries(
        self,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """With max_passes=1, one retry occurs and persistent failures are flagged."""
        mock_extract.return_value = Path("/tmp/frame.jpg")
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        # Always fail visual check
        mock_delta.return_value = 0.5
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            max_passes=1,
            generate_timelines=False,
        )
        self.assertFalse(report.passed)
        # Check that unresolved flag is present after max passes
        visual_findings = [f for f in report.findings
                          if f.check == "visual_discontinuity" and not f.passed]
        self.assertTrue(len(visual_findings) > 0)
        self.assertIn("unresolved after max passes", visual_findings[0].details)

    @patch("media_tooling.verify.probe_duration", side_effect=RuntimeError("ffprobe failed"))
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    def test_warnings_do_not_get_unresolved_suffix(
        self,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """Structural warnings (severity=warning) should not get 'unresolved' suffix."""
        mock_extract.return_value = Path("/tmp/frame.jpg")
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        report = run_verification(
            Path("video.mp4"),
            _single_range_edl(),
            max_passes=1,
            generate_timelines=False,
        )
        warning_findings = [f for f in report.findings
                            if not f.passed and f.severity == "warning"]
        for f in warning_findings:
            self.assertNotIn("unresolved after max passes", f.details)

    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    @patch("media_tooling.verify._sample_luminance", return_value=0.5)
    def test_non_blocking_warnings_not_retried(
        self,
        mock_lum: MagicMock,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """Non-blocking warnings should not consume retry passes."""
        mock_extract.return_value = Path("/tmp/frame.jpg")
        # Make audio pop check return a non-blocking warning (structural issue)
        mock_env.return_value = (np.zeros(500, dtype=np.float32), 0.0)  # silent → warning
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            max_passes=2,
            generate_timelines=False,
        )
        # Audio pop warnings should not have retry pass annotations
        audio_warnings = [f for f in report.findings
                         if f.check == "audio_pop" and not f.passed]
        for f in audio_warnings:
            self.assertNotIn("[pass", f.details)
        # Overall report should still pass (warnings are non-blocking)
        self.assertTrue(report.passed)
        self.assertEqual(report.fail_count, 0)
        self.assertGreater(report.warning_count, 0)

    @patch("media_tooling.verify.generate_boundary_timelines", return_value=({}, []))
    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    @patch("media_tooling.verify._sample_luminance", return_value=0.5)
    def test_timeline_generation_failure_produces_finding(
        self,
        mock_lum: MagicMock,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
        mock_timelines: MagicMock,
    ) -> None:
        """When timeline PNG generation fails, a non-blocking warning finding is produced."""
        mock_extract.return_value = Path("/tmp/frame.jpg")
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            generate_timelines=True,
        )
        timeline_findings = [f for f in report.findings
                             if f.check == "timeline_pngs"]
        self.assertEqual(len(timeline_findings), 1)
        self.assertFalse(timeline_findings[0].passed)
        self.assertEqual(timeline_findings[0].severity, "warning")
        self.assertTrue(timeline_findings[0].non_blocking)
        self.assertIn("failed", timeline_findings[0].details)
        # Timeline failure is non-blocking: overall report still passes
        self.assertTrue(report.passed)

    @patch("media_tooling.verify.generate_boundary_timelines")
    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    @patch("media_tooling.verify._sample_luminance", return_value=0.5)
    def test_partial_timeline_failure_reported(
        self,
        mock_lum: MagicMock,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
        mock_timelines: MagicMock,
    ) -> None:
        """When some timeline PNGs fail, each failure gets a non-blocking finding."""
        mock_extract.return_value = Path("/tmp/frame.jpg")
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        # 2 boundaries: first succeeds, second fails
        mock_timelines.return_value = (
            {0: "/tmp/boundary_000_10.00s.png"},
            [(1, 20.0, "ffmpeg error")],
        )
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            generate_timelines=True,
        )
        # timeline_pngs finding should show partial success
        png_findings = [f for f in report.findings if f.check == "timeline_pngs"]
        self.assertEqual(len(png_findings), 1)
        self.assertFalse(png_findings[0].passed)
        self.assertIn("1/2", png_findings[0].details)
        # Timeline findings are non-blocking: overall report still passes
        self.assertTrue(png_findings[0].non_blocking)
        self.assertTrue(report.passed)
        # Individual failure finding
        fail_findings = [f for f in report.findings
                         if f.check == "timeline_png_generation"]
        self.assertEqual(len(fail_findings), 1)
        self.assertFalse(fail_findings[0].passed)
        self.assertTrue(fail_findings[0].non_blocking)
        self.assertIn("20.00s", fail_findings[0].details)

    @patch("media_tooling.verify.generate_boundary_timelines")
    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.compute_envelope")
    @patch("media_tooling.verify._extract_single_frame")
    @patch("media_tooling.verify._compute_frame_delta", return_value=0.05)
    @patch("media_tooling.verify._sample_luminance", return_value=0.5)
    def test_timeline_png_index_mapping_with_gaps(
        self,
        mock_lum: MagicMock,
        mock_delta: MagicMock,
        mock_extract: MagicMock,
        mock_env: MagicMock,
        mock_probe: MagicMock,
        mock_timelines: MagicMock,
    ) -> None:
        """PNG-to-boundary mapping is correct even when middle boundary fails."""
        mock_extract.return_value = Path("/tmp/frame.jpg")
        mock_env.return_value = (np.full(500, 0.3, dtype=np.float32), 0.3)
        # 3-boundary EDL: boundary 0 (10.0s) succeeds, boundary 1 (20.0s) fails,
        # boundary 2 (30.0s) succeeds. PNG map keyed by boundary index.
        mock_timelines.return_value = (
            {0: "/tmp/boundary_000_10.00s.png", 2: "/tmp/boundary_002_30.00s.png"},
            [(1, 20.0, "ffmpeg error")],
        )
        # Use an EDL with 3 boundaries
        edl_3 = {
            "version": 1,
            "sources": ["s.mp4"],
            "ranges": [
                {"source": "s.mp4", "start": 0.0, "end": 10.0},
                {"source": "s.mp4", "start": 20.0, "end": 30.0},
                {"source": "s.mp4", "start": 40.0, "end": 50.0},
                {"source": "s.mp4", "start": 60.0, "end": 70.0},
            ],
            "total_duration_s": 40.0,
        }
        report = run_verification(
            Path("video.mp4"),
            edl_3,
            generate_timelines=True,
        )
        # boundary 0 (10.0s) should get its PNG
        vis_10 = [f for f in report.findings
                  if f.check == "visual_discontinuity"
                  and f.cut_time is not None
                  and math.isclose(f.cut_time, 10.0, abs_tol=0.01)]
        self.assertEqual(len(vis_10), 1)
        self.assertIsNotNone(vis_10[0].timeline_png)
        # boundary 1 (20.0s) has no PNG
        vis_20 = [f for f in report.findings
                  if f.check == "visual_discontinuity"
                  and f.cut_time is not None
                  and math.isclose(f.cut_time, 20.0, abs_tol=0.01)]
        self.assertEqual(len(vis_20), 1)
        self.assertIsNone(vis_20[0].timeline_png)
        # boundary 2 (30.0s) should get its PNG (NOT boundary 1's)
        vis_30 = [f for f in report.findings
                  if f.check == "visual_discontinuity"
                  and f.cut_time is not None
                  and math.isclose(f.cut_time, 30.0, abs_tol=0.01)]
        self.assertEqual(len(vis_30), 1)
        self.assertIsNotNone(vis_30[0].timeline_png)
        self.assertIn("002_30.00s", vis_30[0].timeline_png or "")

    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.verify_audio_pop")
    @patch("media_tooling.verify.verify_visual_discontinuity")
    @patch("media_tooling.verify.verify_grade_consistency")
    def test_max_passes_default_gives_three_retries(
        self,
        mock_grade: MagicMock,
        mock_visual: MagicMock,
        mock_audio: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """With max_passes=3, there should be exactly 3 retry iterations."""
        # Two-boundary EDL: visual gets called twice per pass
        # We want both boundaries to fail through retries 1-2, then pass on retry 3.
        mock_visual.side_effect = [
            # Initial pass
            Finding(check="visual_discontinuity", passed=False, details="fail",
                    severity="fail", cut_time=10.0),
            Finding(check="visual_discontinuity", passed=False, details="fail",
                    severity="fail", cut_time=20.0),
            # Retry 1
            Finding(check="visual_discontinuity", passed=False, details="fail",
                    severity="fail", cut_time=10.0),
            Finding(check="visual_discontinuity", passed=False, details="fail",
                    severity="fail", cut_time=20.0),
            # Retry 2
            Finding(check="visual_discontinuity", passed=False, details="fail",
                    severity="fail", cut_time=10.0),
            Finding(check="visual_discontinuity", passed=False, details="fail",
                    severity="fail", cut_time=20.0),
            # Retry 3 — passes
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=10.0),
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=20.0),
        ]
        mock_audio.return_value = Finding(
            check="audio_pop", passed=True, details="ok", cut_time=10.0,
        )
        mock_grade.return_value = Finding(
            check="grade_consistency", passed=True, details="ok", severity="info",
        )
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            max_passes=3,
            generate_timelines=False,
        )
        # With 3 retries, the 3rd retry should succeed
        self.assertTrue(report.passed)

    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.verify_audio_pop")
    @patch("media_tooling.verify.verify_visual_discontinuity")
    @patch("media_tooling.verify.verify_grade_consistency")
    def test_retry_recovers_from_transient_failure(
        self,
        mock_grade: MagicMock,
        mock_visual: MagicMock,
        mock_audio: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """When a check fails then passes on retry, the report reflects recovery."""
        # First call fails, second call (retry) passes
        # There are 2 cut boundaries, so visual is called twice per pass
        mock_visual.side_effect = [
            Finding(check="visual_discontinuity", passed=False, details="fail",
                    severity="fail", cut_time=10.0),
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=20.0),
            # Retry for cut_time=10.0
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=10.0),
        ]
        mock_audio.return_value = Finding(
            check="audio_pop", passed=True, details="ok", cut_time=10.0,
        )
        mock_grade.return_value = Finding(
            check="grade_consistency", passed=True, details="ok", severity="info",
        )
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            max_passes=3,
            generate_timelines=False,
        )
        self.assertTrue(report.passed)

    @patch("media_tooling.verify.probe_duration")
    @patch("media_tooling.verify.verify_audio_pop")
    @patch("media_tooling.verify.verify_visual_discontinuity")
    @patch("media_tooling.verify.verify_duration")
    @patch("media_tooling.verify.verify_grade_consistency")
    def test_retry_recovers_duration_failure(
        self,
        mock_grade: MagicMock,
        mock_duration: MagicMock,
        mock_visual: MagicMock,
        mock_audio: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """Duration check (no cut_time) should be retried and updated."""
        mock_probe.return_value = 30.0
        mock_visual.return_value = Finding(
            check="visual_discontinuity", passed=True, details="ok",
            severity="info", cut_time=10.0,
        )
        mock_audio.return_value = Finding(
            check="audio_pop", passed=True, details="ok", cut_time=10.0,
        )
        mock_grade.return_value = Finding(
            check="grade_consistency", passed=True, details="ok",
        )
        # Duration fails first, passes on retry
        mock_duration.side_effect = [
            Finding(check="duration", passed=False, details="fail", severity="fail"),
            Finding(check="duration", passed=True, details="ok", severity="info"),
        ]
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            max_passes=3,
            generate_timelines=False,
        )
        self.assertTrue(report.passed)

    @patch("media_tooling.verify.probe_duration")
    @patch("media_tooling.verify.verify_audio_pop")
    @patch("media_tooling.verify.verify_visual_discontinuity")
    @patch("media_tooling.verify.verify_duration")
    @patch("media_tooling.verify.verify_grade_consistency")
    def test_retry_updates_non_blocking_flag(
        self,
        mock_grade: MagicMock,
        mock_duration: MagicMock,
        mock_visual: MagicMock,
        mock_audio: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """A check that transitions from blocking fail to non-blocking warning
        on retry must have its non_blocking flag updated so fail_count is correct."""
        mock_probe.return_value = 30.0
        # 2 cut boundaries (10.0, 20.0); cut 10.0 fails first, then becomes
        # non-blocking warning on retry; cut 20.0 passes throughout.
        mock_visual.side_effect = [
            # First pass: cut_time=10.0 fails (blocking)
            Finding(
                check="visual_discontinuity",
                passed=False,
                details="jump detected",
                severity="fail",
                cut_time=10.0,
                non_blocking=False,
            ),
            # First pass: cut_time=20.0 passes
            Finding(
                check="visual_discontinuity",
                passed=True,
                details="ok",
                severity="info",
                cut_time=20.0,
            ),
            # Retry pass 1: cut_time=10.0 now becomes non-blocking warning
            Finding(
                check="visual_discontinuity",
                passed=False,
                details="ffmpeg failed to extract frames",
                severity="warning",
                cut_time=10.0,
                non_blocking=True,
            ),
        ]
        mock_audio.side_effect = [
            Finding(check="audio_pop", passed=True, details="ok", cut_time=10.0),
            Finding(check="audio_pop", passed=True, details="ok", cut_time=20.0),
        ]
        mock_duration.return_value = Finding(
            check="duration", passed=True, details="ok", severity="info",
        )
        mock_grade.return_value = Finding(
            check="grade_consistency", passed=True, details="ok",
        )
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            max_passes=3,
            generate_timelines=False,
        )
        # The visual_discontinuity finding should now be non_blocking=True,
        # so it's counted as a warning, not a blocking failure.
        self.assertEqual(report.fail_count, 0)
        self.assertEqual(report.warning_count, 1)
        self.assertTrue(report.passed)
        vis_finding = [f for f in report.findings if f.check == "visual_discontinuity"][0]
        self.assertTrue(vis_finding.non_blocking)


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
        self.assertIn("warning_count", d)
        self.assertIn("findings", d)
        self.assertFalse(d["passed"])  # one blocking failure
        self.assertEqual(d["pass_count"], 1)
        self.assertEqual(d["fail_count"], 1)
        self.assertEqual(d["warning_count"], 0)
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

    def test_print_report_shows_severity(self) -> None:
        """_print_report output includes severity level for non-info findings."""
        from io import StringIO

        from media_tooling.verify import _print_report

        report = VerifyReport(video="test.mp4", edl="edl.json", passed=True)
        report.add(Finding(check="duration", passed=True, details="ok",
                           severity="info"))
        report.add(Finding(check="audio_pop", passed=False, details="check not performed",
                           severity="warning", non_blocking=True))
        buf = StringIO()
        import sys
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            _print_report(report)
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        # Severity shown for non-info findings
        self.assertIn("(warning)", output)
        # Info severity is NOT shown (reduces noise)
        self.assertNotIn("(info)", output)
        # Non-blocking should be indicated
        self.assertIn("[non-blocking]", output)
        # Warning count shown in summary
        self.assertIn("1 warning(s)", output)

    def test_non_blocking_findings_dont_flip_verdict(self) -> None:
        """Timeline-related findings (non-blocking) must not make report FAIL."""
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        # All verification checks pass
        report.add(Finding(check="duration", passed=True, details="ok"))
        report.add(Finding(check="visual_discontinuity", passed=True, details="ok",
                           cut_time=5.0))
        # Timeline PNG fails (non-blocking)
        report.add(Finding(check="timeline_pngs", passed=False,
                           details="Generated 0/1 timeline PNG(s)",
                           severity="warning", non_blocking=True))
        report.add(Finding(check="timeline_png_generation", passed=False,
                           details="Timeline PNG failed at boundary 0",
                           severity="warning", non_blocking=True))
        self.assertTrue(report.passed)
        self.assertEqual(report.fail_count, 0)
        self.assertEqual(report.warning_count, 2)

    def test_mixed_blocking_and_non_blocking(self) -> None:
        """Report with both blocking and non-blocking failures."""
        report = VerifyReport(video="v.mp4", edl="e.json", passed=True)
        report.add(Finding(check="duration", passed=True, details="ok"))
        report.add(Finding(check="visual_discontinuity", passed=False,
                           details="jump at 5s", severity="fail", cut_time=5.0))
        report.add(Finding(check="timeline_pngs", passed=False,
                           details="partial failure",
                           severity="warning", non_blocking=True))
        self.assertFalse(report.passed)
        self.assertEqual(report.fail_count, 1)
        self.assertEqual(report.warning_count, 1)


# ── generate_boundary_timelines PNG mapping ─────────────────────────────────


class TestBoundaryPngMapping(unittest.TestCase):
    """Verify that PNG paths are correctly attached to visual_discontinuity
    findings even when some boundaries fail PNG generation."""

    @patch("media_tooling.verify.probe_duration", return_value=30.0)
    @patch("media_tooling.verify.generate_boundary_timelines")
    @patch("media_tooling.verify.verify_audio_pop")
    @patch("media_tooling.verify.verify_visual_discontinuity")
    @patch("media_tooling.verify.verify_grade_consistency")
    def test_png_map_with_partial_failure(
        self,
        mock_grade: MagicMock,
        mock_visual: MagicMock,
        mock_audio: MagicMock,
        mock_gen: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """When boundary 0 fails and boundary 1 succeeds, boundary 1 gets its PNG."""
        mock_visual.side_effect = [
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=10.0),
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=20.0),
        ]
        mock_audio.side_effect = [
            Finding(check="audio_pop", passed=True, details="ok", cut_time=10.0),
            Finding(check="audio_pop", passed=True, details="ok", cut_time=20.0),
        ]
        mock_grade.return_value = Finding(
            check="grade_consistency", passed=True, details="ok", severity="info",
        )
        # Boundary 0 fails, boundary 1 succeeds
        mock_gen.return_value = (
            {1: "/tmp/boundary_001_20.00s.png"},
            [(0, 10.0, "ffmpeg error")],
        )
        report = run_verification(
            Path("video.mp4"),
            _minimal_edl(),
            generate_timelines=True,
            output_dir=Path("/tmp"),
        )
        # Boundary 1's visual_discontinuity finding should have the PNG
        findings_10 = [f for f in report.findings
                       if f.check == "visual_discontinuity" and f.cut_time is not None
                       and math.isclose(f.cut_time, 10.0, abs_tol=0.01)]
        findings_20 = [f for f in report.findings
                       if f.check == "visual_discontinuity" and f.cut_time is not None
                       and math.isclose(f.cut_time, 20.0, abs_tol=0.01)]
        self.assertEqual(len(findings_10), 1)
        self.assertEqual(len(findings_20), 1)
        # Boundary 0 (failed PNG) should have no timeline_png
        self.assertIsNone(findings_10[0].timeline_png)
        # Boundary 1 (successful PNG) should have its PNG attached
        self.assertEqual(findings_20[0].timeline_png, "/tmp/boundary_001_20.00s.png")

    @patch("media_tooling.verify.probe_duration", return_value=40.0)
    @patch("media_tooling.verify.generate_boundary_timelines")
    @patch("media_tooling.verify.verify_audio_pop")
    @patch("media_tooling.verify.verify_visual_discontinuity")
    @patch("media_tooling.verify.verify_grade_consistency")
    def test_png_map_with_first_boundary_fails(
        self,
        mock_grade: MagicMock,
        mock_visual: MagicMock,
        mock_audio: MagicMock,
        mock_gen: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """3 boundaries: #0 fails, #1 and #2 succeed → correct PNGs attached."""
        edl = {
            "version": 1,
            "sources": ["s.mp4"],
            "ranges": [
                {"source": "s.mp4", "start": 0.0, "end": 10.0},
                {"source": "s.mp4", "start": 20.0, "end": 30.0},
                {"source": "s.mp4", "start": 40.0, "end": 50.0},
                {"source": "s.mp4", "start": 60.0, "end": 70.0},
            ],
            "total_duration_s": 40.0,
        }
        mock_visual.side_effect = [
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=10.0),
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=20.0),
            Finding(check="visual_discontinuity", passed=True, details="ok",
                    severity="info", cut_time=30.0),
        ]
        mock_audio.side_effect = [
            Finding(check="audio_pop", passed=True, details="ok", cut_time=10.0),
            Finding(check="audio_pop", passed=True, details="ok", cut_time=20.0),
            Finding(check="audio_pop", passed=True, details="ok", cut_time=30.0),
        ]
        mock_grade.return_value = Finding(
            check="grade_consistency", passed=True, details="ok", severity="info",
        )
        # Boundary 0 fails, boundaries 1 and 2 succeed
        mock_gen.return_value = (
            {
                1: "/tmp/boundary_001_20.00s.png",
                2: "/tmp/boundary_002_30.00s.png",
            },
            [(0, 10.0, "ffmpeg error")],
        )
        report = run_verification(
            Path("video.mp4"),
            edl,
            generate_timelines=True,
            output_dir=Path("/tmp"),
        )
        # Verify PNG attachments
        vis_findings = [f for f in report.findings
                        if f.check == "visual_discontinuity" and f.cut_time is not None]
        by_cut = {f.cut_time: f for f in vis_findings}
        self.assertIsNone(by_cut[10.0].timeline_png)  # failed
        self.assertEqual(by_cut[20.0].timeline_png, "/tmp/boundary_001_20.00s.png")
        self.assertEqual(by_cut[30.0].timeline_png, "/tmp/boundary_002_30.00s.png")
        # Overall report still passes (timeline failures are non-blocking)
        self.assertTrue(report.passed)


if __name__ == "__main__":
    unittest.main()