"""Self-evaluation (verify) command for rendered video output.

Inspects a rendered video at every cut boundary defined in an EDL JSON file,
checking for:

- Visual discontinuity / flash / jump at cut boundaries
- Waveform spikes indicating audio pops
- Duration correctness vs EDL ``total_duration_s``
- Grade consistency across sampled points

Generates ``timeline_view`` PNGs at every cut boundary (±1.5 s window) and
produces a structured report of pass/fail findings.

Usage::

    media-verify final.mp4 --edl edl.json
    media-verify final.mp4 --edl edl.json --max-passes 3
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from media_tooling.edl_render import validate_edl
from media_tooling.ffprobe_utils import probe_duration
from media_tooling.timeline_view import compute_envelope

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CUT_BOUNDARY_WINDOW_S = 1.5  # ±1.5 s around each cut boundary
DEFAULT_MAX_PASSES = 3
DURATION_TOLERANCE_S = 0.5  # tolerance for duration check
VISUAL_DELTA_THRESHOLD = 0.25  # normalised pixel-delta threshold for discontinuity
AUDIO_SPIKE_THRESHOLD = 0.80  # normalised amplitude threshold for audio pop
MIN_ABSOLUTE_LEVEL = 0.05  # raw peak below this is too quiet for meaningful pop detection
GRADE_LUMINANCE_TOLERANCE = 0.15  # tolerance for grade consistency (normalised)
GRADE_SAMPLE_MIDPOINTS = 3  # number of mid-points to sample for grade consistency
N_FRAMES_PER_BOUNDARY = 4  # frames per boundary for visual check

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    """A single verification finding (pass or fail)."""

    check: str
    passed: bool
    details: str
    severity: str = "info"  # info | warning | fail
    cut_time: float | None = None
    timeline_png: str | None = None
    non_blocking: bool = False  # if True, doesn't affect overall report.passed

    def to_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "passed": self.passed,
            "details": self.details,
            "severity": self.severity,
            "cut_time": self.cut_time,
            "timeline_png": self.timeline_png,
            "non_blocking": self.non_blocking,
        }


@dataclass
class VerifyReport:
    """Aggregated verification report."""

    video: str
    edl: str
    passed: bool
    findings: list[Finding] = field(default_factory=list)
    pass_count: int = 0
    fail_count: int = 0
    warning_count: int = 0  # non-blocking failures (don't affect overall verdict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "video": self.video,
            "edl": self.edl,
            "passed": self.passed,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "warning_count": self.warning_count,
            "findings": [f.to_dict() for f in self.findings],
        }

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        if finding.passed:
            self.pass_count += 1
        elif finding.non_blocking:
            self.warning_count += 1
        else:
            self.fail_count += 1
            self.passed = False


# ---------------------------------------------------------------------------
# Cut boundary extraction
# ---------------------------------------------------------------------------


def extract_cut_boundaries(edl: dict[str, Any]) -> list[float]:
    """Return output-timeline cut boundary times from an EDL.

    Each range in the EDL contributes a segment in the output.  The
    cut boundaries are the transition points *between* segments — i.e.
    the cumulative duration after each segment except the last.

    For example, if ranges have durations [5, 10, 8], the cut
    boundaries are [5.0, 15.0].
    """
    ranges = edl.get("ranges", [])
    if not ranges:
        return []

    boundaries: list[float] = []
    cumulative = 0.0
    for r in ranges:
        seg_start = float(r["start"])
        seg_end = float(r["end"])
        seg_duration = seg_end - seg_start
        cumulative += seg_duration
        boundaries.append(cumulative)

    # The last boundary is the end of the video, not a cut — remove it
    if boundaries:
        boundaries.pop()

    return boundaries


# ---------------------------------------------------------------------------
# Duration verification
# ---------------------------------------------------------------------------


def verify_duration(
    video_path: Path,
    edl: dict[str, Any],
    ffprobe_bin: str = "ffprobe",
    tolerance: float = DURATION_TOLERANCE_S,
) -> Finding:
    """Verify output duration matches EDL ``total_duration_s``."""
    expected = edl.get("total_duration_s")
    if expected is None:
        return Finding(
            check="duration",
            passed=False,
            details="EDL has no total_duration_s field; duration check not performed.",
            severity="warning",
            non_blocking=True,
        )

    try:
        actual = probe_duration(video_path, ffprobe_bin)
    except (RuntimeError, json.JSONDecodeError) as exc:
        return Finding(
            check="duration",
            passed=False,
            details=f"ffprobe failed: {exc}",
            severity="fail",
        )

    delta = abs(actual - float(expected))
    passed = delta <= tolerance
    return Finding(
        check="duration",
        passed=passed,
        details=(
            f"expected={float(expected):.3f}s actual={actual:.3f}s "
            f"delta={delta:.3f}s tolerance={tolerance:.3f}s"
        ),
        severity="info" if passed else "fail",
    )


# ---------------------------------------------------------------------------
# Visual discontinuity check
# ---------------------------------------------------------------------------


def _extract_single_frame(
    video: Path, timestamp: float, ffmpeg_bin: str, dest: Path
) -> Path | None:
    """Extract a single frame at *timestamp*; return path or None on failure."""
    cmd = [
        ffmpeg_bin, "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video),
        "-frames:v", "1",
        "-q:v", "4",
        "-vf", "scale=320:-2",
        str(dest),
    ]
    result = subprocess.run(
        cmd, check=False,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0 or not dest.exists():
        return None
    return dest


def _compute_frame_delta(frame_a: Path, frame_b: Path) -> float | None:
    """Compute a normalised mean-absolute-difference between two frames.

    Returns a value in [0, 1] where 0 = identical and 1 = maximum difference.
    Returns ``None`` if frames cannot be compared (corrupt, missing, etc.).
    """
    try:
        with Image.open(frame_a) as img_a, Image.open(frame_b) as img_b:
            arr_a = np.asarray(img_a.convert("RGB"), dtype=np.float32) / 255.0
            arr_b = np.asarray(img_b.convert("RGB"), dtype=np.float32) / 255.0
            # Crop to same size if dimensions differ
            min_h = min(arr_a.shape[0], arr_b.shape[0])
            min_w = min(arr_a.shape[1], arr_b.shape[1])
            arr_a = arr_a[:min_h, :min_w]
            arr_b = arr_b[:min_h, :min_w]
            delta = float(np.mean(np.abs(arr_a - arr_b)))
            return delta
    except Exception:
        return None


def verify_visual_discontinuity(
    video_path: Path,
    cut_time: float,
    ffmpeg_bin: str = "ffmpeg",
    window: float = CUT_BOUNDARY_WINDOW_S,
    threshold: float = VISUAL_DELTA_THRESHOLD,
) -> Finding:
    """Check for visual discontinuity at a cut boundary.

    Extracts frames just before and just after the cut and compares
    them.  A large delta suggests a flash, jump, or discontinuity.

    The *before* frame is sampled *window* seconds before the cut.
    The *after* frame is sampled ``min(window, 0.5)`` seconds after
    the cut — capped at 0.5 s to ensure the seek crosses the nearest
    keyframe boundary (ffmpeg ``-ss`` is keyframe-aligned; sampling
    too close to the cut may return the pre-cut frame).
    """
    before_t = max(0.0, cut_time - window)
    after_t = cut_time + min(window, 0.5)  # up to 0.5s after to cross keyframe boundaries

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        frame_before = tmp / "before.jpg"
        frame_after = tmp / "after.jpg"

        fa = _extract_single_frame(video_path, before_t, ffmpeg_bin, frame_before)
        fb = _extract_single_frame(video_path, after_t, ffmpeg_bin, frame_after)

        if fa is None or fb is None:
            return Finding(
                check="visual_discontinuity",
                passed=False,
                details="Could not extract frames at cut boundary; check not performed.",
                severity="warning",
                cut_time=cut_time,
                non_blocking=True,
            )

        delta = _compute_frame_delta(frame_before, frame_after)
        if delta is None:
            return Finding(
                check="visual_discontinuity",
                passed=False,
                details="Frame comparison failed; check not performed.",
                severity="warning",
                cut_time=cut_time,
                non_blocking=True,
            )

        passed = delta <= threshold
        return Finding(
            check="visual_discontinuity",
            passed=passed,
            details=(
                f"cut={cut_time:.2f}s delta={delta:.4f} "
                f"threshold={threshold:.4f}"
            ),
            severity="info" if passed else "fail",
            cut_time=cut_time,
        )


# ---------------------------------------------------------------------------
# Audio pop detection
# ---------------------------------------------------------------------------


def verify_audio_pop(
    video_path: Path,
    cut_time: float,
    ffmpeg_bin: str = "ffmpeg",
    window: float = CUT_BOUNDARY_WINDOW_S,
    threshold: float = AUDIO_SPIKE_THRESHOLD,
    min_absolute_level: float = MIN_ABSOLUTE_LEVEL,
) -> Finding:
    """Check for waveform spikes near a cut boundary indicating audio pops.

    Examines the normalised audio envelope ±window around the cut.
    A spike (value above *threshold*) near the cut suggests an audio pop.

    If the raw peak of the un-normalised envelope is below *min_absolute_level*,
    the audio is too quiet for meaningful pop detection and the check is
    skipped (non-blocking pass).
    """
    start = max(0.0, cut_time - window)
    end = cut_time + window

    try:
        envelope, raw_peak = compute_envelope(video_path, start, end, ffmpeg_bin, samples=500)
    except Exception as exc:
        return Finding(
            check="audio_pop",
            passed=False,
            details=f"Could not compute envelope: {exc}; check not performed.",
            severity="warning",
            cut_time=cut_time,
            non_blocking=True,
        )

    if envelope.size == 0 or envelope.max() == 0:
        return Finding(
            check="audio_pop",
            passed=False,
            details="No audio data near cut boundary; check not performed.",
            severity="warning",
            cut_time=cut_time,
            non_blocking=True,
        )

    # Minimum-absolute-level gate: if the raw peak is too low, the
    # normalised threshold is meaningless (a barely-audible segment
    # normalises to 1.0 just like a full-scale one).  Skip detection.
    if raw_peak < min_absolute_level:
        return Finding(
            check="audio_pop",
            passed=True,
            details=(
                f"cut={cut_time:.2f}s raw_peak={raw_peak:.4f} "
                f"< min_level={min_absolute_level:.3f}; "
                f"too quiet for meaningful pop detection"
            ),
            severity="info",
            cut_time=cut_time,
            non_blocking=True,
        )

    # Check for any spike above threshold near the cut boundary
    near_cut_start = max(0, int((cut_time - 0.5 - start) / (end - start) * envelope.size))
    near_cut_end = min(envelope.size, int((cut_time + 0.5 - start) / (end - start) * envelope.size))
    near_cut_region = envelope[near_cut_start:near_cut_end]
    max_spike_near_cut = float(near_cut_region.max()) if near_cut_region.size > 0 else 0.0
    max_spike = float(envelope.max())
    passed = max_spike_near_cut <= threshold

    return Finding(
        check="audio_pop",
        passed=passed,
        details=(
            f"cut={cut_time:.2f}s raw_peak={raw_peak:.4f} "
            f"max_spike={max_spike:.3f} "
            f"max_near_cut={max_spike_near_cut:.3f} "
            f"threshold={threshold:.3f}"
        ),
        severity="info" if passed else "fail",
        cut_time=cut_time,
    )


# ---------------------------------------------------------------------------
# Grade consistency check
# ---------------------------------------------------------------------------


def _sample_luminance(video: Path, timestamp: float, ffmpeg_bin: str) -> float | None:
    """Extract a frame at *timestamp* and return mean luminance in [0, 1]."""
    with tempfile.TemporaryDirectory() as tmpdir:
        frame_path = Path(tmpdir) / "sample.jpg"
        result = _extract_single_frame(video, timestamp, ffmpeg_bin, frame_path)
        if result is None:
            return None
        try:
            with Image.open(frame_path) as img:
                arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
                return float(np.mean(arr))
        except Exception:
            return None


def verify_grade_consistency(
    video_path: Path,
    total_duration: float,
    ffmpeg_bin: str = "ffmpeg",
    tolerance: float = GRADE_LUMINANCE_TOLERANCE,
    n_midpoints: int = GRADE_SAMPLE_MIDPOINTS,
) -> Finding:
    """Sample luminance at key points and check for grade consistency.

    Samples at approximately 1 s from the start, 1 s from the end,
    and *n_midpoints* evenly-spaced mid-points.  If any pair of
    samples differs by more than *tolerance*, the check fails.
    """
    if total_duration < 4.0:
        return Finding(
            check="grade_consistency",
            passed=False,
            details="Video too short for grade consistency sampling; check not performed.",
            severity="warning",
            non_blocking=True,
        )

    sample_times: list[float] = []
    # ~1 s from start
    sample_times.append(min(1.0, total_duration * 0.1))
    # Mid-points
    for i in range(1, n_midpoints + 1):
        frac = i / (n_midpoints + 1)
        sample_times.append(total_duration * frac)
    # ~1 s from end
    sample_times.append(max(total_duration - 1.0, total_duration * 0.9))

    luminances: list[tuple[float, float]] = []
    for t in sample_times:
        lum = _sample_luminance(video_path, t, ffmpeg_bin)
        if lum is not None:
            luminances.append((t, lum))

    if len(luminances) < 2:
        return Finding(
            check="grade_consistency",
            passed=False,
            details="Insufficient frames for grade consistency check; not performed.",
            severity="warning",
            non_blocking=True,
        )

    # Find max pairwise delta
    max_delta = 0.0
    worst_pair = (0.0, 0.0)
    for i in range(len(luminances)):
        for j in range(i + 1, len(luminances)):
            delta = abs(luminances[i][1] - luminances[j][1])
            if delta > max_delta:
                max_delta = delta
                worst_pair = (luminances[i][0], luminances[j][0])

    passed = max_delta <= tolerance
    return Finding(
        check="grade_consistency",
        passed=passed,
        details=(
            f"samples={len(luminances)} max_delta={max_delta:.4f} "
            f"worst_pair=({worst_pair[0]:.1f}s, {worst_pair[1]:.1f}s) "
            f"tolerance={tolerance:.4f}"
        ),
        severity="info" if passed else "fail",
    )


# ---------------------------------------------------------------------------
# Timeline PNG generation at cut boundaries
# ---------------------------------------------------------------------------


def generate_boundary_timelines(
    video_path: Path,
    cut_boundaries: list[float],
    output_dir: Path,
    ffmpeg_bin: str = "ffmpeg",
    window: float = CUT_BOUNDARY_WINDOW_S,
) -> tuple[dict[int, str], list[tuple[int, float, str]]]:
    """Generate timeline_view PNGs at every cut boundary.

    Returns a tuple of (boundary_png_map, failed_boundaries).
    ``boundary_png_map`` maps boundary index → PNG path (only successful).
    Each failed entry is (index, cut_time, error_message).
    """
    from media_tooling.timeline_view import generate_timeline

    png_map: dict[int, str] = {}
    failed: list[tuple[int, float, str]] = []
    for i, cut_time in enumerate(cut_boundaries):
        start = max(0.0, cut_time - window)
        end = cut_time + window
        out_path = output_dir / f"boundary_{i:03d}_{cut_time:.2f}s.png"
        try:
            generate_timeline(
                input_path=video_path,
                output_path=out_path,
                start=start,
                end=end,
                n_frames=N_FRAMES_PER_BOUNDARY,
                transcript_path=None,
                ffmpeg_bin=ffmpeg_bin,
            )
            png_map[i] = str(out_path)
        except Exception as exc:
            failed.append((i, cut_time, str(exc)))
            print(f"  warning: timeline generation failed at {cut_time:.2f}s: {exc}",
                  file=sys.stderr)

    return png_map, failed


# ---------------------------------------------------------------------------
# Main verification pipeline
# ---------------------------------------------------------------------------


def run_verification(
    video_path: Path,
    edl: dict[str, Any],
    output_dir: Path | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    max_passes: int = DEFAULT_MAX_PASSES,
    generate_timelines: bool = True,
) -> VerifyReport:
    """Run all verification checks on *video_path* against *edl*.

    Re-runs checks up to *max_passes* times.  After each pass, only
    the failing checks are re-evaluated.  Once *max_passes* is
    exhausted, any remaining failures are flagged as unresolved.

    Returns a :class:`VerifyReport` with structured findings.
    """
    report = VerifyReport(
        video=str(video_path),
        edl="<provided>",
        passed=True,
    )

    # 1. Duration verification
    finding = verify_duration(video_path, edl, ffprobe_bin)
    report.add(finding)

    # 2. Cut boundary extraction
    cut_boundaries = extract_cut_boundaries(edl)
    if not cut_boundaries:
        report.add(Finding(
            check="cut_boundaries",
            passed=True,
            details="No internal cut boundaries (single segment or no ranges).",
            severity="info",
        ))
    else:
        report.add(Finding(
            check="cut_boundaries",
            passed=True,
            details=f"Found {len(cut_boundaries)} cut boundary/ies: "
                    + ", ".join(f"{t:.2f}s" for t in cut_boundaries),
            severity="info",
        ))

    # 3. Visual discontinuity at each cut
    for ct in cut_boundaries:
        finding = verify_visual_discontinuity(video_path, ct, ffmpeg_bin)
        report.add(finding)

    # 4. Audio pop at each cut
    for ct in cut_boundaries:
        finding = verify_audio_pop(video_path, ct, ffmpeg_bin)
        report.add(finding)

    # 5. Grade consistency
    try:
        total_duration = probe_duration(video_path, ffprobe_bin)
    except (RuntimeError, json.JSONDecodeError):
        total_duration = 0.0

    if total_duration > 0:
        finding = verify_grade_consistency(video_path, total_duration, ffmpeg_bin)
        report.add(finding)
    else:
        report.add(Finding(
            check="grade_consistency",
            passed=False,
            details="cannot verify grade consistency: video duration unavailable",
            severity="warning",
            non_blocking=True,
        ))

    # 6. Retry loop: re-evaluate failed (blocking) checks up to max_passes
    # Non-blocking warnings (structural issues like missing audio data,
    # unavailable tools) are excluded — retrying won't fix them.
    for pass_num in range(1, max_passes + 1):
        failed_checks = [f for f in report.findings if not f.passed and not f.non_blocking]
        if not failed_checks:
            break  # all blocking checks passing

        # Re-run only the checkable failures (not info-only findings like cut_boundaries)
        recheck_findings: list[Finding] = []
        for f in failed_checks:
            if f.check == "visual_discontinuity" and f.cut_time is not None:
                recheck_findings.append(
                    verify_visual_discontinuity(video_path, f.cut_time, ffmpeg_bin)
                )
            elif f.check == "audio_pop" and f.cut_time is not None:
                recheck_findings.append(
                    verify_audio_pop(video_path, f.cut_time, ffmpeg_bin)
                )
            elif f.check == "duration":
                recheck_findings.append(
                    verify_duration(video_path, edl, ffprobe_bin)
                )
            elif f.check == "grade_consistency" and total_duration > 0:
                recheck_findings.append(
                    verify_grade_consistency(video_path, total_duration, ffmpeg_bin)
                )

        # Update report: replace failed findings with re-check results
        for old_f in failed_checks:
            for ri, rf in enumerate(recheck_findings):
                if rf.check == old_f.check:
                    if old_f.cut_time is not None and rf.cut_time is not None:
                        if math.isclose(old_f.cut_time, rf.cut_time, abs_tol=0.01):
                            old_f.passed = rf.passed
                            old_f.details = f"[retry {pass_num}] {rf.details}"
                            old_f.severity = rf.severity
                            old_f.non_blocking = rf.non_blocking
                            recheck_findings.pop(ri)
                            break
                    elif old_f.cut_time is None and rf.cut_time is None:
                        # Match on check name alone for checks without cut_time
                        old_f.passed = rf.passed
                        old_f.details = f"[retry {pass_num}] {rf.details}"
                        old_f.severity = rf.severity
                        old_f.non_blocking = rf.non_blocking
                        recheck_findings.pop(ri)
                        break

        # Recalculate pass/fail/warning counts
        report.pass_count = sum(1 for f in report.findings if f.passed)
        report.fail_count = sum(
            1 for f in report.findings if not f.passed and not f.non_blocking
        )
        report.warning_count = sum(
            1 for f in report.findings if not f.passed and f.non_blocking
        )
        report.passed = report.fail_count == 0

    # Flag remaining failures after max_passes exhausted
    # Only flag severity="fail" findings as unresolved; severity="warning"
    # findings represent structural issues (missing data, unavailable tools)
    # that retrying cannot fix.
    if report.fail_count > 0:
        for f in report.findings:
            if not f.passed and f.severity == "fail" and "unresolved" not in f.details:
                f.details += " [unresolved after max passes]"

    # 7. Timeline PNGs
    if generate_timelines and cut_boundaries:
        timeline_dir = output_dir or video_path.parent / "verify_timelines"
        timeline_dir.mkdir(parents=True, exist_ok=True)
        png_map, failed_boundaries = generate_boundary_timelines(
            video_path, cut_boundaries, timeline_dir, ffmpeg_bin,
        )

        # Report on timeline PNGs (non-blocking: doesn't affect overall verdict)
        if png_map:
            png_passed = len(failed_boundaries) == 0
            report.add(Finding(
                check="timeline_pngs",
                passed=png_passed,
                details=(
                    f"Generated {len(png_map)}/{len(cut_boundaries)} "
                    f"timeline PNG(s) in {timeline_dir}"
                ),
                severity="info" if png_passed else "warning",
                non_blocking=True,
            ))
            # Attach PNG paths to the corresponding visual discontinuity findings
            for finding in report.findings:
                if finding.check == "visual_discontinuity" and finding.cut_time is not None:
                    for bi, bt in enumerate(cut_boundaries):
                        if math.isclose(bt, finding.cut_time, abs_tol=0.01):
                            finding.timeline_png = png_map.get(bi)
                            break
        else:
            report.add(Finding(
                check="timeline_pngs",
                passed=False,
                details=f"timeline PNG generation failed for all {len(cut_boundaries)} cut boundary/ies",
                severity="warning",
                non_blocking=True,
            ))

        # Report each failed boundary as a separate finding (non-blocking)
        for fail_idx, fail_ct, fail_err in failed_boundaries:
            report.add(Finding(
                check="timeline_png_generation",
                passed=False,
                details=(
                    f"Timeline PNG failed at boundary {fail_idx} "
                    f"({fail_ct:.2f}s): {fail_err}"
                ),
                severity="warning",
                non_blocking=True,
            ))

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify rendered video output against an EDL specification.",
    )
    parser.add_argument(
        "video", help="Path to the rendered video file to verify.",
    )
    parser.add_argument(
        "--edl", required=True,
        help="Path to the EDL JSON file.",
    )
    parser.add_argument(
        "--output-dir", default=None,
        help="Directory for timeline PNGs and report. Default: beside video.",
    )
    parser.add_argument(
        "--max-passes", type=int, default=DEFAULT_MAX_PASSES,
        help=f"Maximum re-evaluation attempts. Default: {DEFAULT_MAX_PASSES}.",
    )
    parser.add_argument(
        "--no-timelines", action="store_true",
        help="Skip timeline PNG generation.",
    )
    parser.add_argument(
        "--ffmpeg-bin", default="ffmpeg",
        help="Path to ffmpeg binary.",
    )
    parser.add_argument(
        "--ffprobe-bin", default="ffprobe",
        help="Path to ffprobe binary.",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output report as JSON.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    video_path = Path(args.video).expanduser().resolve()
    if not video_path.exists():
        print(f"Video file not found: {video_path}", file=sys.stderr)
        return 1

    edl_path = Path(args.edl).expanduser().resolve()
    if not edl_path.exists():
        print(f"EDL file not found: {edl_path}", file=sys.stderr)
        return 1

    try:
        edl = json.loads(edl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Cannot read EDL: {exc}", file=sys.stderr)
        return 1

    try:
        validate_edl(edl)
    except Exception as exc:
        print(f"EDL validation error: {exc}", file=sys.stderr)
        return 1

    output_dir = Path(args.output_dir) if args.output_dir else None

    report = run_verification(
        video_path=video_path,
        edl=edl,
        output_dir=output_dir,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
        max_passes=args.max_passes,
        generate_timelines=not args.no_timelines,
    )

    # Output
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report)

    return 0 if report.passed else 1


def _print_report(report: VerifyReport) -> None:
    """Print a human-readable verification report."""
    status = "PASS" if report.passed else "FAIL"
    print(f"\n{'='*60}")
    print(f"  Verify Report: {status}")
    print(f"  Video: {report.video}")
    print(f"{'='*60}")
    for f in report.findings:
        icon = "✓" if f.passed else "✗"
        severity_tag = f" ({f.severity})" if f.severity != "info" else ""
        suffix = " [non-blocking]" if f.non_blocking else ""
        print(f"  {icon} [{f.check}]{severity_tag}{suffix} {f.details}")
    print(f"{'-'*60}")
    parts = [f"{report.pass_count} passed"]
    if report.fail_count:
        parts.append(f"{report.fail_count} failed")
    if report.warning_count:
        parts.append(f"{report.warning_count} warning(s)")
    print(f"  Total: {', '.join(parts)}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    raise SystemExit(main())