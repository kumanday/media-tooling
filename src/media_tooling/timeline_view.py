from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from media_tooling.ffprobe_utils import probe_duration

try:
    _RESAMPLING = Image.Resampling.LANCZOS  # Pillow >=10
except AttributeError:
    _RESAMPLING = Image.LANCZOS  # type: ignore[attr-defined]  # Pillow <10

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_N_FRAMES = 10
SILENCE_THRESHOLD_SECS = 0.4
CANVAS_MIN_WIDTH = 1920
FRAME_HEIGHT = 180
MIN_FRAME_WIDTH = 10
WAVEFORM_HEIGHT = 220
FONT_CANDIDATES = [
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNSMono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]

# Colour palette
BG = (18, 18, 22)
FG = (235, 235, 235)
DIM = (110, 110, 120)
ACCENT = (255, 140, 60)
SILENCE_FILL = (50, 80, 120, 120)
WAVE_COLOUR = (140, 180, 255)

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a filmstrip + waveform composite PNG for a video time range.",
    )
    parser.add_argument("input", help="Path to a video or audio file.")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output PNG path. Defaults to <stem>-timeline.png beside the input.",
    )
    parser.add_argument(
        "--start",
        type=float,
        default=0.0,
        help="Start time in seconds. Default: 0.",
    )
    parser.add_argument(
        "--end",
        type=float,
        default=None,
        help="End time in seconds. Default: full duration.",
    )
    parser.add_argument(
        "--n-frames",
        type=int,
        default=DEFAULT_N_FRAMES,
        help=f"Number of evenly-spaced filmstrip frames. Default: {DEFAULT_N_FRAMES}.",
    )
    parser.add_argument(
        "--transcript",
        default=None,
        help="Path to transcript JSON (media-subtitle output) for word labels and silence shading.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg binary.",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default="ffprobe",
        help="Path to ffprobe binary.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing output PNG.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip work if the output PNG already exists.",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output
        else input_path.with_name(f"{input_path.stem}-timeline.png")
    )

    if output_path.exists():
        if args.skip_existing:
            print(f"Skipping existing timeline for {input_path}")
            return 0
        if not args.overwrite:
            print(
                f"Output already exists: {output_path}. Use --overwrite or --skip-existing.",
                file=sys.stderr,
            )
            return 1

    transcript_path = Path(args.transcript).resolve() if args.transcript else None
    if transcript_path is not None and not transcript_path.exists():
        print(f"Transcript not found: {transcript_path}", file=sys.stderr)
        return 1

    try:
        duration = probe_duration(input_path, args.ffprobe_bin)
        end = args.end if args.end is not None else duration
        start = args.start

        if start < 0:
            raise ValueError("start must be non-negative")
        if end <= start:
            raise ValueError("end must be greater than start")
        if start >= duration:
            raise ValueError("start is beyond media duration")

        end = min(end, duration)

        generate_timeline(
            input_path=input_path,
            output_path=output_path,
            start=start,
            end=end,
            n_frames=args.n_frames,
            transcript_path=transcript_path,
            ffmpeg_bin=args.ffmpeg_bin,
        )
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Timeline: {output_path}")
    return 0


# ---------------------------------------------------------------------------
# Frame extraction
# ---------------------------------------------------------------------------


def compute_frame_timestamps(start: float, end: float, n: int) -> list[float]:
    """Return *n* evenly-spaced timestamps across [start, end]."""
    if n < 1:
        n = 1
    if n == 1:
        return [(start + end) / 2.0]
    step = (end - start) / (n - 1)
    return [start + i * step for i in range(n)]


def extract_frames(
    video: Path,
    timestamps: list[float],
    ffmpeg_bin: str,
    dest_dir: Path,
) -> list[Path]:
    """Extract one frame per timestamp via ffmpeg. Returns frame file paths."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for i, t in enumerate(timestamps):
        out = dest_dir / f"f_{i:03d}.jpg"
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", f"{t:.3f}",
            "-i", str(video),
            "-frames:v", "1",
            "-q:v", "4",
            "-vf", "scale=320:-2",
            str(out),
        ]
        completed = subprocess.run(
            cmd, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if completed.returncode != 0 or not out.exists():
            # Frame extraction can fail for audio-only or very short clips;
            # produce a blank placeholder so the composite still renders.
            _create_placeholder_frame(out, 320, 180)
        paths.append(out)
    return paths


def _create_placeholder_frame(path: Path, width: int, height: int) -> None:
    """Write a small grey placeholder image when ffmpeg cannot extract a frame."""
    img = Image.new("RGB", (width, height), (40, 40, 44))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "JPEG")


# ---------------------------------------------------------------------------
# Audio envelope (RMS)
# ---------------------------------------------------------------------------


def compute_envelope(
    video: Path,
    start: float,
    end: float,
    ffmpeg_bin: str,
    samples: int = 2000,
) -> np.ndarray[tuple[int], np.dtype[np.float32]]:
    """Extract the audio segment and return a normalised RMS envelope of length *samples*."""
    wav_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            wav_path = Path(f.name)
        cmd = [
            ffmpeg_bin, "-y",
            "-ss", f"{start:.3f}",
            "-i", str(video),
            "-t", f"{(end - start):.3f}",
            "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(wav_path),
        ]
        result = subprocess.run(
            cmd, check=False,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if result.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            return np.zeros(samples, dtype=np.float32)

        pcm = _read_pcm_mono_16k(wav_path)
        if pcm.size == 0:
            return np.zeros(samples, dtype=np.float32)

        env = _windowed_rms(pcm, samples)
        # Normalise to [0, 1]
        if env.max() > 0:
            env = env / env.max()
        return env.astype(np.float32)
    finally:
        if wav_path is not None:
            wav_path.unlink(missing_ok=True)


def _read_pcm_mono_16k(wav_path: Path) -> np.ndarray[tuple[int], np.dtype[np.float32]]:
    """Read a mono 16-bit WAV and return float32 samples in [-1, 1]."""
    with wave.open(str(wav_path), "rb") as w:
        n_frames = w.getnframes()
        raw = w.readframes(n_frames)
    pcm = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return pcm


def _windowed_rms(
    pcm: np.ndarray[tuple[int], np.dtype[np.float32]],
    samples: int,
) -> np.ndarray[tuple[int], np.dtype[np.float32]]:
    """Compute windowed RMS, producing an array of exactly *samples* length."""
    n = pcm.size
    window = max(1, n // samples)
    usable = (n // window) * window
    reshaped = pcm[:usable].reshape(-1, window)
    env: np.ndarray[tuple[int], np.dtype[np.float32]] = np.sqrt(
        np.mean(reshaped ** 2, axis=1),
    ).astype(np.float32)
    if env.size < samples:
        env = np.pad(env, (0, samples - env.size))
    elif env.size > samples:
        env = env[:samples]
    return env


# ---------------------------------------------------------------------------
# Transcript / silence helpers
# ---------------------------------------------------------------------------


def load_words(transcript_path: Path | None, start: float, end: float) -> list[dict[str, Any]]:
    """Load word-level timestamps from transcript JSON, filtered to [start, end].

    Accepts two JSON layouts:
    - Flat ``{"words": [...]}`` (reference implementation format)
    - Segmented ``{"segments": [{"words": [...]}]}`` (media-subtitle output)
    """
    if transcript_path is None or not transcript_path.exists():
        return []
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    all_words: list[dict[str, Any]] = []

    # Flat format
    if "words" in data and isinstance(data["words"], list):
        all_words = data["words"]
    # Segmented format (media-subtitle JSON output)
    elif "segments" in data and isinstance(data["segments"], list):
        for seg in data["segments"]:
            for w in seg.get("words", []):
                all_words.append(w)
    else:
        return []

    # Filter to time range
    out: list[dict[str, Any]] = []
    for w in all_words:
        ws = float(w.get("start", 0))
        we = float(w.get("end", ws))
        if we <= start or ws >= end:
            continue
        out.append(w)
    return out


def find_silences(
    words: list[dict[str, Any]],
    start: float,
    end: float,
    threshold: float = SILENCE_THRESHOLD_SECS,
) -> list[tuple[float, float]]:
    """Find silence gaps >= *threshold* seconds within [start, end].

    Returns an empty list when *words* is empty — absence of transcript
    data is not the same as silence.  Words are sorted by start time
    to handle out-of-order input.
    """
    if not words:
        return []
    sorted_words = sorted(words, key=lambda w: float(w.get("start", 0)))
    gaps: list[tuple[float, float]] = []
    prev_end = start
    for w in sorted_words:
        ws = max(start, float(w.get("start", start)))
        if ws - prev_end >= threshold:
            gaps.append((prev_end, ws))
        prev_end = max(prev_end, float(w.get("end", ws)))
    if end - prev_end >= threshold:
        gaps.append((prev_end, end))
    return gaps


# ---------------------------------------------------------------------------
# Font loading
# ---------------------------------------------------------------------------


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fp in FONT_CANDIDATES:
        if Path(fp).exists():
            try:
                return ImageFont.truetype(fp, size)
            except Exception:
                continue
    return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Composite rendering
# ---------------------------------------------------------------------------


def compute_layout(
    frame_height: int = FRAME_HEIGHT,
    waveform_height: int = WAVEFORM_HEIGHT,
) -> dict[str, int]:
    """Return a dict of layout metrics used during rendering."""
    filmstrip_y = 50
    wave_y = filmstrip_y + frame_height + 20
    ruler_y = wave_y + waveform_height + 2
    label_y = ruler_y + 24
    canvas_height = label_y + 40
    return {
        "filmstrip_y": filmstrip_y,
        "frame_height": frame_height,
        "wave_y": wave_y,
        "waveform_height": waveform_height,
        "ruler_y": ruler_y,
        "label_y": label_y,
        "canvas_height": canvas_height,
    }


def _time_to_x(t: float, start: float, end: float, x0: int, span: int) -> int:
    """Map a timestamp *t* to a horizontal pixel position."""
    frac = (t - start) / max(1e-6, end - start)
    return int(x0 + frac * span)


def _cap_n_frames(n_frames: int, strip_width: int) -> int:
    """Cap *n_frames* so each frame is at least MIN_FRAME_WIDTH pixels wide."""
    gap = 4
    max_n = strip_width // (MIN_FRAME_WIDTH + gap)
    return min(n_frames, max(1, max_n))


def _render_filmstrip(
    canvas: Image.Image,
    frame_paths: list[Path],
    n_frames: int,
    layout: dict[str, int],
    strip_x0: int,
    strip_width: int,
) -> tuple[int, int]:
    """Render filmstrip frames onto *canvas*. Returns (strip_x1, strip_span)."""
    frame_height = layout["frame_height"]
    gap = 4
    frame_w = (strip_width - (n_frames - 1) * gap) // n_frames
    filmstrip_y = layout["filmstrip_y"]

    placed = min(len(frame_paths), n_frames)
    cursor = strip_x0
    for fp in frame_paths[:placed]:
        with Image.open(fp) as img:
            resized = img.convert("RGB").resize((frame_w, frame_height), _RESAMPLING)
        canvas.paste(resized, (cursor, filmstrip_y))
        cursor += frame_w + gap

    if placed > 0:
        strip_x1 = cursor - gap  # last frame has no trailing gap
    else:
        strip_x1 = strip_x0
    return strip_x1, strip_x1 - strip_x0


def _render_waveform(
    draw: ImageDraw.ImageDraw,
    envelope: np.ndarray[tuple[int], np.dtype[np.float32]],
    layout: dict[str, int],
    strip_x0: int,
    strip_x1: int,
    silences: list[tuple[float, float]],
    words: list[dict[str, Any]],
    start: float,
    end: float,
    small_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    """Render waveform area: background, silence shading, envelope, and word labels."""
    wave_y = layout["wave_y"]
    waveform_height = layout["waveform_height"]
    strip_span = strip_x1 - strip_x0

    # Background
    draw.rectangle(
        (strip_x0, wave_y, strip_x1, wave_y + waveform_height),
        fill=(28, 28, 34),
    )

    # Silence shading
    for gap_start, gap_end in silences:
        xa = _time_to_x(gap_start, start, end, strip_x0, strip_span)
        xb = _time_to_x(gap_end, start, end, strip_x0, strip_span)
        draw.rectangle((xa, wave_y, xb, wave_y + waveform_height), fill=SILENCE_FILL)

    # Envelope
    mid_y = wave_y + waveform_height // 2
    max_amp = waveform_height // 2 - 8
    points_top: list[tuple[int, int]] = []
    points_bot: list[tuple[int, int]] = []
    for i, v in enumerate(envelope):
        xi = strip_x0 + int(i * strip_span / max(1, len(envelope) - 1))
        a = int(v * max_amp)
        points_top.append((xi, mid_y - a))
        points_bot.append((xi, mid_y + a))
    if points_top:
        draw.line(points_top, fill=WAVE_COLOUR, width=1, joint="curve")
        draw.line(points_bot, fill=WAVE_COLOUR, width=1, joint="curve")
        poly = points_top + list(reversed(points_bot))
        draw.polygon(poly, fill=(*WAVE_COLOUR, 60))

    # Word labels
    last_label_x = -9999
    for w in words:
        word_text = (w.get("word") or w.get("text") or "").strip()
        ws = float(w.get("start", 0))
        we = float(w.get("end", ws))
        if not word_text:
            continue
        if (we - ws) < 0.05:
            continue
        cx = (_time_to_x(ws, start, end, strip_x0, strip_span)
              + _time_to_x(we, start, end, strip_x0, strip_span)) // 2
        if cx - last_label_x < 28:
            continue
        draw.line((cx, wave_y - 4, cx, wave_y), fill=DIM, width=1)
        draw.text((cx + 2, wave_y - 18), word_text, fill=FG, font=small_font)
        last_label_x = cx


def _render_ruler(
    draw: ImageDraw.ImageDraw,
    layout: dict[str, int],
    start: float,
    end: float,
    strip_x0: int,
    strip_span: int,
    label_font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    silences: list[tuple[float, float]],
) -> None:
    """Render time ruler and silence legend."""
    ruler_y = layout["ruler_y"]
    n_ticks = 6
    for i in range(n_ticks + 1):
        frac = i / n_ticks
        t = start + frac * (end - start)
        xi = strip_x0 + int(frac * strip_span)
        draw.line((xi, ruler_y, xi, ruler_y + 6), fill=DIM, width=1)
        draw.text((xi - 20, ruler_y + 8), f"{t:.2f}s", fill=DIM, font=label_font)

    # Silence legend
    label_y = layout["label_y"]
    if silences:
        txt = f"shaded bands = silences ≥ 400ms ({len(silences)} gap(s))"
        draw.text((strip_x0, label_y), txt, fill=DIM, font=label_font)


def generate_timeline(
    *,
    input_path: Path,
    output_path: Path,
    start: float,
    end: float,
    n_frames: int,
    transcript_path: Path | None,
    ffmpeg_bin: str,
) -> None:
    """Produce the composite PNG and save to *output_path*."""
    n_frames = max(1, n_frames)

    strip_x0 = 50
    strip_width = CANVAS_MIN_WIDTH - 100

    # Cap n_frames so each frame is at least MIN_FRAME_WIDTH pixels;
    # this must happen before timestamp computation and frame extraction
    # to keep filmstrip, waveform, and ruler aligned.
    n_frames = _cap_n_frames(n_frames, strip_width)

    timestamps = compute_frame_timestamps(start, end, n_frames)
    layout = compute_layout()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        frame_paths = extract_frames(input_path, timestamps, ffmpeg_bin, tmp_dir)

        canvas = Image.new("RGB", (CANVAS_MIN_WIDTH, layout["canvas_height"]), BG)
        draw = ImageDraw.Draw(canvas, "RGBA")

        header_font = load_font(22)
        label_font = load_font(14)
        small_font = load_font(12)

        # Header (ACCENT highlights the time range for quick scanning)
        draw.text(
            (50, 12),
            f"{input_path.name}   ",
            fill=FG,
            font=header_font,
        )
        header_name_w = int(draw.textlength(f"{input_path.name}   ", font=header_font))
        draw.text(
            (50 + header_name_w, 12),
            f"{start:.2f}s → {end:.2f}s   ({(end - start):.2f}s, {n_frames} frames)",
            fill=ACCENT,
            font=header_font,
        )

        # Filmstrip
        strip_x1, strip_span = _render_filmstrip(
            canvas, frame_paths, n_frames, layout, strip_x0, strip_width,
        )

        # Transcript / silence data
        words = load_words(transcript_path, start, end)
        silences = find_silences(words, start, end) if words else []

        # Waveform + word labels
        env = compute_envelope(input_path, start, end, ffmpeg_bin, samples=max(strip_span, 200))
        _render_waveform(
            draw, env, layout, strip_x0, strip_x1,
            silences, words, start, end, small_font,
        )

        # Time ruler + legend
        _render_ruler(draw, layout, start, end, strip_x0, strip_span, label_font, silences)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(str(output_path), "PNG", optimize=True)


if __name__ == "__main__":
    raise SystemExit(main())
