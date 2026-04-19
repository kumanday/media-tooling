from __future__ import annotations

import json
import subprocess
from pathlib import Path


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
    payload = json.loads(completed.stdout)
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
    payload = json.loads(completed.stdout)
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
