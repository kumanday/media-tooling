from __future__ import annotations

import json
import subprocess
from pathlib import Path


def _parse_ffprobe_json(stdout: str, input_path: Path) -> dict:
    """Parse ffprobe JSON stdout, raising RuntimeError on malformed output."""
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"ffprobe returned malformed JSON for {input_path}: {exc}"
        ) from exc


def probe_duration(input_path: Path, ffprobe_bin: str) -> float:
    """Return the duration of *input_path* in seconds using ffprobe."""
    command = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(input_path),
    ]
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {input_path}:\n{completed.stderr.strip()}")
    payload = _parse_ffprobe_json(completed.stdout, input_path)
    duration_value = payload.get("format", {}).get("duration")
    if duration_value is None:
        raise RuntimeError(f"Could not determine duration for {input_path}")
    return float(duration_value)


def probe_video_size(input_path: Path, ffprobe_bin: str = "ffprobe") -> tuple[int, int]:
    """Return ``(width, height)`` of the first video stream in *input_path*.

    Raises ``RuntimeError`` if the video dimensions cannot be determined.
    """
    command = [
        ffprobe_bin,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "json",
        str(input_path),
    ]
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {input_path}:\n{completed.stderr.strip()}")
    payload = _parse_ffprobe_json(completed.stdout, input_path)
    streams = payload.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream found in {input_path}")
    w = streams[0].get("width")
    h = streams[0].get("height")
    if w is None or h is None:
        raise RuntimeError(f"Could not determine video size for {input_path}")
    w, h = int(w), int(h)
    if w <= 0 or h <= 0:
        raise RuntimeError(
            f"Invalid video dimensions ({w}x{h}) for {input_path}; "
            "width and height must be positive"
        )
    return w, h


def probe_frame_rate(input_path: Path, ffprobe_bin: str = "ffprobe") -> int:
    """Return the frame rate (fps) of the first video stream as an integer.

    Uses ``r_frame_rate`` from ffprobe which returns a fraction like
    ``30/1`` or ``24000/1001``.  The result is rounded to the nearest
    integer.

    Raises ``RuntimeError`` if the frame rate cannot be determined.
    """
    command = [
        ffprobe_bin,
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=r_frame_rate",
        "-of", "json",
        str(input_path),
    ]
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {input_path}:\n{completed.stderr.strip()}")
    payload = _parse_ffprobe_json(completed.stdout, input_path)
    streams = payload.get("streams", [])
    if not streams:
        raise RuntimeError(f"No video stream found in {input_path}")
    raw = streams[0].get("r_frame_rate")
    if raw is None:
        raise RuntimeError(f"Could not determine frame rate for {input_path}")
    try:
        num, den = raw.split("/")
        fps = int(num) / int(den)
    except (ValueError, ZeroDivisionError) as exc:
        raise RuntimeError(
            f"Unexpected frame rate format '{raw}' for {input_path}: {exc}"
        ) from exc
    if fps <= 0:
        raise RuntimeError(
            f"Invalid frame rate ({fps}) for {input_path}; must be positive"
        )
    return round(fps)
