"""Apply a color grade to a video via ffmpeg filter chain.

Two modes:

  1. Preset mode — pick a named preset (e.g. ``warm_cinematic``, ``neutral_punch``).
     Simple fixed filter chain applied uniformly. Presets are intentionally
     creative and may exceed the ±8% auto-grade bounds — that's the point.

  2. Auto mode (DEFAULT) — analyze the clip mathematically and emit a subtle
     per-clip correction. Samples N frames via ffmpeg ``signalstats``, computes
     mean brightness, luminance range, saturation. Emits a bounded filter string
     that corrects under-exposure, flatness, and mild desaturation without
     applying any creative color shift. In auto mode, all adjustments are capped
     at ±8% on any axis (i.e. every parameter in [0.92, 1.08]).

     The goal is "make it look clean without looking graded". Never applies
     creative LUTs, teal/orange splits, or filmic curves. For creative looks,
     use ``--preset warm_cinematic`` explicitly.

Mental model follows ASC CDL:
  slope   → highlights (contrast)
  offset  → shadows    (brightness/gamma lift)
  power   → midtones   (gamma curve)
  saturation → global saturation

Can also be imported programmatically:
  ``get_preset(name)`` and ``auto_grade_for_clip(path, start, duration)``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PRESETS: dict[str, str] = {
    # Subtle baseline — barely perceptible cleanup. No color shift.
    # Use when auto-analysis isn't available or when you want a safe floor.
    "subtle": "eq=contrast=1.03:saturation=0.98",
    # Minimal corrective grade: light contrast + subtle S-curve, no color shifts.
    "neutral_punch": (
        "eq=contrast=1.06:brightness=0.0:saturation=1.0,"
        "curves=master='0/0 0.25/0.23 0.75/0.77 1/1'"
    ),
    # OPT-IN creative preset for retro/cinematic looks ONLY. Not a default.
    # +12% contrast, crushed blacks, -12% sat, warm shadows + cool highs, filmic curve.
    # Originally from HEURISTICS §6 — too aggressive for standard launch content.
    "warm_cinematic": (
        "eq=contrast=1.12:brightness=-0.02:saturation=0.88,"
        "colorbalance="
        "rs=0.02:gs=0.0:bs=-0.03:"
        "rm=0.04:gm=0.01:bm=-0.02:"
        "rh=0.08:gh=0.02:bh=-0.05,"
        "curves=master='0/0 0.25/0.22 0.75/0.78 1/1'"
    ),
    # Flat — no grade. Useful as a sentinel for "skip grading this source".
    "none": "",
}


def get_preset(name: str) -> str:
    """Return the ffmpeg filter string for a preset name.

    Empty string for 'none'. Raises KeyError for unknown presets.
    """
    if name not in PRESETS:
        raise KeyError(
            f"unknown preset '{name}'. Available: {', '.join(sorted(PRESETS))}"
        )
    return PRESETS[name]


# -------- Auto grade (data-driven, per-clip) --------------------------------


def _parse_signalstats_value(line: str) -> float | None:
    """Parse a ``lavfi.signalstats.*=N`` value from a metadata line."""
    try:
        return float(line.rsplit("=", 1)[1])
    except (ValueError, IndexError):
        return None


def _parse_metadata_file(metadata_path: str) -> dict[str, float]:
    """Parse a signalstats metadata file into normalised stats.

    Reads the file produced by ``ffmpeg signalstats,metadata=print`` and
    returns ``{"y_mean": float, "y_range": float, "sat_mean": float}``
    with all values normalised to 0..1 regardless of source bit depth.

    If no signalstats lines are found, returns neutral defaults (no correction).
    """
    y_avgs: list[float] = []
    y_mins: list[float] = []
    y_maxs: list[float] = []
    sat_avgs: list[float] = []
    bit_depth: int = 8

    with open(metadata_path) as f:
        for line in f:
            line = line.strip()
            if "lavfi.signalstats.YBITDEPTH" in line:
                v = _parse_signalstats_value(line)
                if v is not None:
                    bit_depth = int(v)
            elif "lavfi.signalstats.YAVG" in line:
                v = _parse_signalstats_value(line)
                if v is not None:
                    y_avgs.append(v)
            elif "lavfi.signalstats.YMIN" in line:
                v = _parse_signalstats_value(line)
                if v is not None:
                    y_mins.append(v)
            elif "lavfi.signalstats.YMAX" in line:
                v = _parse_signalstats_value(line)
                if v is not None:
                    y_maxs.append(v)
            elif "lavfi.signalstats.SATAVG" in line:
                v = _parse_signalstats_value(line)
                if v is not None:
                    sat_avgs.append(v)

    if not y_avgs:
        return {"y_mean": 0.5, "y_range": 0.7, "sat_mean": 0.25}

    max_val = max(1, (2 ** bit_depth) - 1)

    y_mean = (sum(y_avgs) / len(y_avgs)) / max_val
    y_range = (
        ((sum(y_maxs) / len(y_maxs)) - (sum(y_mins) / len(y_mins))) / max_val
        if y_maxs and y_mins
        else 0.7
    )
    sat_mean = (
        (sum(sat_avgs) / len(sat_avgs)) / max_val if sat_avgs else 0.25
    )

    return {
        "y_mean": y_mean,
        "y_range": y_range,
        "sat_mean": sat_mean,
    }


def _sample_frame_stats(
    video: Path,
    start: float,
    duration: float,
    n_samples: int = 10,
) -> dict[str, float]:
    """Sample N frames from a range and compute brightness/contrast/saturation stats.

    Uses ffmpeg's ``signalstats`` filter which gives us YMIN, YMAX, YAVG,
    SATAVG etc. in the metadata. We average across the sample range.

    Returns:
        ``{"y_mean": float, "y_range": float, "sat_mean": float}``
        where all values are normalised to 0..1 regardless of source bit depth.
        ``y_range`` is the average (YMAX - YMIN) normalised by bit-depth max.
    """
    fps = max(0.5, min(n_samples / max(duration, 0.1), 10.0))

    with tempfile.NamedTemporaryFile(mode="w+", suffix=".txt", delete=False) as f:
        metadata_path = f.name

    try:
        # Escape path for ffmpeg filter syntax: colons and backslashes
        # are special in filter chains. Use ffmpeg's level-1 escaping:
        #   \ → \\   and   : → \:
        escaped_path = metadata_path.replace("\\", "\\\\").replace(":", "\\:")
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-nostats",
            "-ss", f"{start:.3f}",
            "-i", str(video),
            "-t", f"{duration:.3f}",
            "-vf", f"fps={fps:.2f},signalstats,metadata=print:file={escaped_path}",
            "-f", "null", "-",
        ]
        try:
            subprocess.run(
                cmd, check=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True
            )
        except FileNotFoundError:
            raise RuntimeError(
                "ffmpeg not found — ensure ffmpeg is installed and on PATH"
            )
        except subprocess.CalledProcessError as exc:
            stderr_snippet = (exc.stderr or "").strip().splitlines()[-1] if exc.stderr else ""
            raise RuntimeError(
                f"ffmpeg signalstats analysis failed (exit code {exc.returncode}). "
                f"Input: {video}. {stderr_snippet}"
            )

        return _parse_metadata_file(metadata_path)
    finally:
        Path(metadata_path).unlink(missing_ok=True)


def auto_grade_for_clip(
    video: Path,
    start: float = 0.0,
    duration: float | None = None,
    verbose: bool = False,
) -> tuple[str, dict[str, float]]:
    """Analyze a clip range and emit a subtle per-clip correction filter.

    Returns ``(filter_string, stats_dict)``. The filter is bounded to ±8%
    on every axis (all parameters in [0.92, 1.08]) and applies NO color
    shift. It only addresses:

      - Underexposure (lift gamma slightly if too dark)
      - Flatness (tiny contrast boost if range is narrow)
      - Desaturation (tiny sat boost if extremely flat)

    If the clip is already well-balanced, returns an empty filter string
    (no correction applied).
    """
    if duration is None:
        # Probe duration
        probe_cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(video),
        ]
        try:
            duration = float(
                subprocess.check_output(probe_cmd).decode().strip()
            )
        except Exception as exc:
            if verbose:
                print(f"  warning: ffprobe failed ({exc}); using 10s window")
            duration = 10.0

    stats = _sample_frame_stats(video, start, duration)

    y_mean = stats["y_mean"]
    y_range = stats["y_range"]
    sat_mean = stats["sat_mean"]

    # ------ Decision rules ---------------------------------------------------
    # All adjustments start at 1.0 (neutral). Corrections are only applied
    # when the analysis shows a measurable problem. Maps taper to exactly 1.0
    # at their outer boundary to avoid discontinuities. Everything is clamped
    # hard to ±8% → [0.92, 1.08].

    # Contrast: boost if the luminance range is narrow (flat footage).
    contrast_adj = 1.0
    if y_range < 0.65:
        # Map [0.40, 0.65] → [1.08, 1.00]  (continuous at y_range=0.65)
        t = max(0.0, min(1.0, (y_range - 0.40) / 0.25))
        contrast_adj = 1.08 - 0.08 * t

    # Gamma: target y_mean ~ 0.48. Lift gently if too dark, pull back if overexposed.
    gamma_adj = 1.0
    if y_mean < 0.42:
        # Map [0.30, 0.42] → [1.08, 1.00]  (continuous at y_mean=0.42)
        t = max(0.0, min(1.0, (y_mean - 0.30) / 0.12))
        gamma_adj = 1.08 - 0.08 * t
    elif y_mean > 0.60:
        # Map [0.60, 0.80] → [1.00, 0.92]  (continuous at y_mean=0.60)
        t = max(0.0, min(1.0, (y_mean - 0.60) / 0.20))
        gamma_adj = 1.00 - 0.08 * t

    # Saturation: scale proportionally like contrast/gamma.
    sat_adj = 1.0
    if sat_mean < 0.15:
        # Map [0.05, 0.15] → [1.08, 1.00]  (continuous at sat_mean=0.15)
        t = max(0.0, min(1.0, (sat_mean - 0.05) / 0.10))
        sat_adj = 1.08 - 0.08 * t
    elif sat_mean > 0.40:
        # Map [0.40, 0.55] → [1.00, 0.92]  (continuous at sat_mean=0.40)
        t = max(0.0, min(1.0, (sat_mean - 0.40) / 0.15))
        sat_adj = 1.00 - 0.08 * t

    # Clamp all adjustments hard to ±8% → [0.92, 1.08]
    contrast_adj = max(0.92, min(1.08, contrast_adj))
    gamma_adj = max(0.92, min(1.08, gamma_adj))
    sat_adj = max(0.92, min(1.08, sat_adj))

    # Build filter string
    eq_parts: list[str] = []
    if abs(contrast_adj - 1.0) > 0.005:
        eq_parts.append(f"contrast={contrast_adj:.3f}")
    if abs(gamma_adj - 1.0) > 0.005:
        eq_parts.append(f"gamma={gamma_adj:.3f}")
    if abs(sat_adj - 1.0) > 0.005:
        eq_parts.append(f"saturation={sat_adj:.3f}")

    if not eq_parts:
        filter_string = ""
    else:
        filter_string = "eq=" + ":".join(eq_parts)

    if verbose:
        print("  auto-grade stats:")
        print(f"    y_mean={y_mean:.3f}  y_range={y_range:.3f}  sat_mean={sat_mean:.3f}")
        print(f"    → contrast={contrast_adj:.3f}  gamma={gamma_adj:.3f}  sat={sat_adj:.3f}")
        print(f"    → filter: {filter_string or '(empty)'}")

    return filter_string, stats


def apply_grade(input_path: Path, output_path: Path, filter_string: str) -> None:
    """Apply a grade filter to a video file.

    If ``filter_string`` is empty, performs a straight stream copy (no
    re-encoding). Otherwise, re-encodes with libx264.

    ``-movflags +faststart`` is only added for MP4-family containers
    (.mp4, .m4v, .mov); it is invalid for other containers like .mkv.

    Raises:
      ValueError: if input and output paths resolve to the same file.
      RuntimeError: if ffmpeg fails or is not installed.
    """
    if input_path.resolve() == output_path.resolve():
        raise ValueError(
            f"input and output must be different files, got {input_path}"
        )

    mp4_suffixes = {".mp4", ".m4v", ".mov"}
    is_mp4 = output_path.suffix.lower() in mp4_suffixes
    faststart = ["-movflags", "+faststart"] if is_mp4 else []

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(f"cannot create output directory: {exc}") from exc

    if not filter_string:
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-c", "copy", *faststart, str(output_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-vf", filter_string,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",
            *faststart,
            str(output_path),
        ]
    try:
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        captured_chunks: list[bytes] = []
        stderr_pipe = proc.stderr
        if stderr_pipe is not None:
            for chunk in iter(lambda: stderr_pipe.read(4096), b""):
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()
                captured_chunks.append(chunk)
        proc.wait()
        if proc.returncode != 0:
            stderr_text = b"".join(captured_chunks).decode("utf-8", errors="replace")
            stderr_snippet = stderr_text.strip().splitlines()[-1] if stderr_text.strip() else ""
            raise RuntimeError(
                f"ffmpeg failed (exit code {proc.returncode}). "
                f"Command: {' '.join(cmd)}. {stderr_snippet}"
            )
    except FileNotFoundError:
        raise RuntimeError(
            "ffmpeg not found — ensure ffmpeg is installed and on PATH"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply a color grade via ffmpeg filter chain."
    )
    parser.add_argument("input", type=Path, nargs="?", help="Input video")
    parser.add_argument("-o", "--output", type=Path, help="Output video")
    parser.add_argument(
        "--preset",
        type=str,
        default=None,
        choices=list(PRESETS.keys()),
        help="Grade preset. Omit for auto mode (default).",
    )
    parser.add_argument(
        "--filter",
        type=str,
        default=None,
        dest="custom_filter",
        help="Raw ffmpeg filter string. Overrides --preset.",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=0.0,
        help="Start time (seconds) for auto-grade analysis window.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Duration (seconds) for auto-grade analysis window.",
    )
    parser.add_argument(
        "--analyze",
        type=Path,
        default=None,
        help="Analyze a clip and print the auto-grade filter it would produce. No output written.",
    )
    parser.add_argument(
        "--print-preset",
        type=str,
        default=None,
        help="Print the filter string for a preset and exit. No input/output needed.",
    )
    parser.add_argument(
        "--list-presets",
        action="store_true",
        help="List available presets and exit.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.list_presets:
        for name, f in PRESETS.items():
            print(f"{name}:")
            print(f"  {f}" if f else "  (no filter)")
            print()
        return 0

    if args.print_preset is not None:
        try:
            print(get_preset(args.print_preset))
        except KeyError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.analyze is not None:
        if not args.analyze.exists():
            print(f"input not found: {args.analyze}", file=sys.stderr)
            return 1
        try:
            filter_string, stats = auto_grade_for_clip(
                args.analyze, start=args.start, duration=args.duration, verbose=True
            )
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"\nfilter: {filter_string or '(none)'}")
        print(f"stats:  {json.dumps(stats, indent=2)}")
        return 0

    if not args.input or not args.output:
        print(
            "input and -o/--output are required unless using "
            "--analyze/--print-preset/--list-presets",
            file=sys.stderr,
        )
        return 1

    if not args.input.exists():
        print(f"input not found: {args.input}", file=sys.stderr)
        return 1

    # Decide filter string
    if args.custom_filter is not None:
        filter_string = args.custom_filter
    elif args.preset is not None:
        filter_string = get_preset(args.preset)
    else:
        # Auto mode (default)
        try:
            filter_string, _ = auto_grade_for_clip(
                args.input, start=args.start, duration=args.duration, verbose=True
            )
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

    print(f"grading {args.input.name} → {args.output.name}")
    if filter_string:
        suffix = "..." if len(filter_string) > 120 else ""
        print(f"  filter: {filter_string[:120]}{suffix}")
    else:
        print("  filter: (none — copy)")

    try:
        apply_grade(args.input, args.output, filter_string)
    except (RuntimeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"done: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

