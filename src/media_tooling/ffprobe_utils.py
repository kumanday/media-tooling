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