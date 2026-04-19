"""Render a video from an EDL (Edit Decision List) JSON spec.

Pipeline (obeys Hard Rules 1–7):

  1. Validate EDL JSON schema
  2. Per-segment extract with:
     - Word-boundary padding (30–200 ms working window, Rule 7)
     - Per-segment color grade (Rule 2)
     - 30 ms audio fades at both edges (Rule 3)
  3. Lossless concat via ffmpeg concat demuxer (Rule 2)
  4. Build master SRT with output-timeline offsets (Rule 5)
  5. Burn subtitles LAST in filter chain (Rule 1)
  6. Two-pass loudness normalization (−14 LUFS / −1 dBTP / LRA 11)

Usage::

    media-edl-render edl.json -o final.mp4
    media-edl-render edl.json -o preview.mp4 --preview
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from media_tooling.burn_subtitles import burn_subtitles
from media_tooling.ffprobe_utils import probe_duration
from media_tooling.grade import PRESETS, auto_grade_for_clip, get_preset
from media_tooling.loudnorm import apply_loudnorm_preview, apply_loudnorm_two_pass
from media_tooling.rough_cut import quote_concat_path, validate_concat_demuxer_usage

# ── Constants ────────────────────────────────────────────────────────────────

FADE_DURATION = 0.03  # 30 ms — Hard Rule 3

MIN_PAD = 0.03  # 30 ms minimum working window (Hard Rule 7)
MAX_PAD = 0.20  # 200 ms maximum working window (Hard Rule 7)

EDL_VERSION = 1

PUNCT_BREAK = set(".,!?;:")

# ── EDL schema validation ───────────────────────────────────────────────────


class EDLSchemaError(ValueError):
    """Raised when an EDL JSON document fails schema validation."""


def validate_edl(edl: dict[str, Any]) -> None:
    """Validate that *edl* conforms to the required EDL JSON schema.

    Required top-level keys: ``version``, ``sources``, ``ranges``.
    Each range must have ``source``, ``start``, ``end``.
    Optional range keys: ``beat``, ``quote``, ``reason``, ``grade``.
    """
    for key in ("version", "sources", "ranges"):
        if key not in edl:
            raise EDLSchemaError(f"missing required key '{key}' in EDL")

    if edl["version"] != EDL_VERSION:
        raise EDLSchemaError(
            f"unsupported EDL version {edl['version']!r}; expected {EDL_VERSION}"
        )

    sources = edl["sources"]
    if not isinstance(sources, (list, dict)):
        raise EDLSchemaError("'sources' must be a list or dict")

    source_names: set[str]
    if isinstance(sources, dict):
        for key, val in sources.items():
            if not isinstance(val, str):
                raise EDLSchemaError(
                    f"sources[{key!r}] value must be a string, got {type(val).__name__}"
                )
        source_names = set(sources.keys())
    else:
        # List sources: match by basename but reject duplicates
        for i, s in enumerate(sources):
            if not isinstance(s, str):
                raise EDLSchemaError(
                    f"sources[{i}] must be a string, got {type(s).__name__}"
                )
        basenames = [Path(s).name for s in sources]
        seen: dict[str, int] = {}
        for name in basenames:
            seen[name] = seen.get(name, 0) + 1
        dupes = {n for n, c in seen.items() if c > 1}
        if dupes:
            raise EDLSchemaError(
                f"Duplicate basenames in sources list: {dupes}. "
                "Use a dict sources mapping to disambiguate."
            )
        source_names = set(basenames)

    ranges = edl["ranges"]
    if not isinstance(ranges, list) or len(ranges) == 0:
        raise EDLSchemaError("'ranges' must be a non-empty list")

    for i, r in enumerate(ranges):
        for key in ("source", "start", "end"):
            if key not in r:
                raise EDLSchemaError(f"range[{i}] missing required key '{key}'")

        if r["source"] not in source_names:
            raise EDLSchemaError(
                f"range[{i}] source '{r['source']}' not found in sources"
            )

        try:
            start = float(r["start"])
            end = float(r["end"])
        except (ValueError, TypeError) as exc:
            raise EDLSchemaError(
                f"range[{i}] start/end must be numeric: {exc}"
            ) from exc
        if not math.isfinite(start) or not math.isfinite(end):
            raise EDLSchemaError(
                f"range[{i}] start/end must be finite numbers, "
                f"got start={start!r} end={end!r}"
            )
        if end <= start:
            raise EDLSchemaError(
                f"range[{i}] end ({end}) must be greater than start ({start})"
            )

        grade = r.get("grade")
        if grade is not None:
            if grade != "auto" and grade not in PRESETS:
                # Could be a raw ffmpeg filter string (contains = or ,)
                if not re.search(r"[=,]", grade):
                    raise EDLSchemaError(
                        f"range[{i}] grade '{grade}' is not a known preset, "
                        f"'auto', or a raw ffmpeg filter string"
                    )

    # Validate top-level grade (fallback for ranges without a per-range grade)
    top_grade = edl.get("grade")
    if top_grade is not None:
        if top_grade != "auto" and top_grade not in PRESETS:
            if not re.search(r"[=,]", top_grade):
                raise EDLSchemaError(
                    f"top-level grade '{top_grade}' is not a known preset, "
                    f"'auto', or a raw ffmpeg filter string"
                )

    # Validate subtitles field if present
    subtitles = edl.get("subtitles")
    if subtitles is not None:
        if isinstance(subtitles, str):
            pass  # path string — valid
        elif isinstance(subtitles, dict):
            allowed = {"style", "path", "force_style"}
            invalid = set(subtitles.keys()) - allowed
            if invalid:
                raise EDLSchemaError(
                    f"subtitles dict contains unknown keys: {invalid}. "
                    f"Allowed: {allowed}"
                )
        else:
            raise EDLSchemaError(
                f"subtitles must be a string path or dict, got {type(subtitles).__name__}"
            )


# ── Path / source resolution ────────────────────────────────────────────────


def resolve_source_path(source_name: str, edl: dict[str, Any], base: Path) -> Path:
    """Resolve a source name from the EDL to an absolute file path.

    If ``sources`` is a dict, the value is the path; otherwise the matching
    list entry (matched by basename) is used as the path.
    """
    sources = edl["sources"]
    if isinstance(sources, dict):
        raw = sources[source_name]
    else:
        # Find the list entry whose basename matches source_name
        raw = source_name
        for entry in sources:
            if Path(entry).name == source_name:
                raw = entry
                break
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p
    return (base / p).resolve()


def resolve_path(value: str | Path, base: Path | None = None) -> Path:
    """Resolve a path that may be absolute or relative to *base*."""
    p = Path(value).expanduser()
    if p.is_absolute():
        return p
    if base is not None:
        return (base / p).resolve()
    return p.resolve()


# ── Grade resolution ────────────────────────────────────────────────────────


def resolve_grade_filter(grade_field: str | None) -> str:
    """Resolve the EDL ``grade`` field to an ffmpeg filter string.

    Returns the filter string to embed in the per-segment ``-vf`` chain.
    For ``"auto"``, returns the sentinel ``"__AUTO__"`` which is resolved
    per-segment during extraction.

    Raises ``ValueError`` for unknown preset names — callers (validate_edl)
    must validate before this function is reached.
    """
    if not grade_field:
        return ""
    if grade_field == "auto":
        return "__AUTO__"
    if re.fullmatch(r"[a-zA-Z0-9_\-]+", grade_field):
        try:
            return get_preset(grade_field)
        except KeyError:
            raise ValueError(
                f"unknown grade preset '{grade_field}'; "
                f"known presets: {', '.join(sorted(PRESETS))}"
            ) from None
    return grade_field


# ── Padding (Hard Rule 7) ───────────────────────────────────────────────────


def apply_padding(
    start: float,
    end: float,
    *,
    source_duration: float | None = None,
    min_pad: float = MIN_PAD,
    max_pad: float = MAX_PAD,
) -> tuple[float, float]:
    """Apply a working-window pad around cut edges.

    Pads *start* backward and *end* forward by *min_pad* (default 30 ms),
    absorbing 50–100 ms of ASR timestamp drift.  Pads are clamped to ``0``
    on the left and *source_duration* on the right when available.

    Returns ``(padded_start, padded_end)``.

    Raises ``ValueError`` if *min_pad* > *max_pad*.
    """
    if min_pad > max_pad:
        raise ValueError(f"min_pad ({min_pad}) must not exceed max_pad ({max_pad})")
    padded_start = max(0.0, start - min_pad)
    padded_end = end + min_pad

    # Clamp to source bounds if known
    if source_duration is not None:
        padded_end = min(padded_end, source_duration)
    padded_end = max(padded_end, padded_start)

    return (padded_start, padded_end)


# ── Word-boundary alignment (Hard Rule 6) ───────────────────────────────────


def snap_to_word_boundary(
    start: float,
    end: float,
    words: list[dict[str, Any]],
) -> tuple[float, float]:
    """Snap *start* and *end* to the nearest word boundaries.

    If word-level timestamps are available, move *start* backward to the
    beginning of the earliest word that overlaps the range, and move *end*
    forward to the end of the latest overlapping word.  This ensures cuts
    never land inside a spoken word (Hard Rule 6).
    """
    if not words:
        return (start, end)

    # Find the first word that ends after our start
    new_start = start
    for w in words:
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if we > start:
            new_start = min(start, ws)
            break

    # Find the last word that starts before our end
    new_end = end
    for w in reversed(words):
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if ws < end:
            new_end = max(end, we)
            break

    return (new_start, new_end)


# ── Audio fades (Hard Rule 3) ───────────────────────────────────────────────


def build_afade_filter(duration: float) -> str:
    """Build an ffmpeg ``afade`` chain for 30 ms in/out fades.

    Returns an empty string when the segment is too short for fades
    (less than twice the fade duration, i.e. under 60 ms).
    """
    if duration < FADE_DURATION * 2:
        return ""
    fade_out_start = duration - FADE_DURATION
    return (
        f"afade=t=in:st=0:d={FADE_DURATION},"
        f"afade=t=out:st={fade_out_start:.3f}:d={FADE_DURATION}"
    )


# ── Per-segment extraction ──────────────────────────────────────────────────


def _words_in_range(
    transcript: dict[str, Any],
    t_start: float,
    t_end: float,
) -> list[dict[str, Any]]:
    """Return word-level entries from *transcript* that overlap [t_start, t_end]."""
    out: list[dict[str, Any]] = []
    for w in transcript.get("words", []):
        if w.get("type") != "word":
            continue
        ws = w.get("start")
        we = w.get("end")
        if ws is None or we is None:
            continue
        if we <= t_start or ws >= t_end:
            continue
        out.append(w)
    return out


def _source_has_audio(source: Path, ffprobe_bin: str = "ffprobe") -> bool:
    """Return True if *source* has at least one audio stream."""
    try:
        result = subprocess.run(
            [ffprobe_bin, "-v", "error",
             "-select_streams", "a", "-show_entries", "stream=codec_type",
             "-of", "csv=p=0", str(source)],
            capture_output=True, text=True, timeout=10,
        )
        return bool(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # If ffprobe is unavailable, assume audio is present to avoid
        # silently dropping fades on normal sources.
        return True


def extract_segment(
    source: Path,
    seg_start: float,
    duration: float,
    grade_filter: str,
    out_path: Path,
    *,
    preview: bool = False,
    draft: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> None:
    """Extract a cut range as its own MP4 with grade + 30 ms audio fades.

    ``-ss`` before ``-i`` for fast seeking (keyframe-approximate, compensated by
    padding window).  Scale to 1080p.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if draft:
        scale = "scale=1280:-2"
    else:
        scale = "scale=1920:-2"

    vf_parts: list[str] = [scale]
    if grade_filter:
        vf_parts.append(grade_filter)
    vf = ",".join(vf_parts)

    afade = build_afade_filter(duration)
    has_audio = _source_has_audio(source, ffprobe_bin)

    if draft:
        preset, crf = "ultrafast", "28"
    elif preview:
        preset, crf = "medium", "22"
    else:
        preset, crf = "fast", "20"

    cmd: list[str] = [
        ffmpeg_bin, "-y",
        "-ss", f"{seg_start:.3f}",
        "-i", str(source),
        "-t", f"{duration:.3f}",
        "-vf", vf,
    ]
    if afade and has_audio:
        cmd.extend(["-af", afade])
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "192k", "-ar", "48000"])
    else:
        cmd.extend(["-an"])
    cmd.extend([
        "-c:v", "libx264", "-preset", preset, "-crf", crf,
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_path),
    ])
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError(f"{ffmpeg_bin} not found — ensure ffmpeg is installed and on PATH")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace")[:500]
        raise RuntimeError(f"ffmpeg extract failed for {source}: {detail}") from exc


def _resolve_segment_bounds(
    start: float,
    end: float,
    src_name: str,
    edit_dir: Path,
    source_durations: dict[str, float],
    warn_label: str = "using raw cut points",
) -> tuple[float, float, list[dict[str, Any]]]:
    """Load transcript, snap to word boundary, apply padding.

    Shared by ``extract_all_segments`` and ``build_master_srt`` so that
    cut-point resolution stays in sync and SRT drift cannot re-occur.

    Returns ``(padded_start, padded_end, words)``.
    """
    tr_path = edit_dir / "transcripts" / f"{src_name}.json"
    words: list[dict[str, Any]] = []
    if tr_path.exists():
        try:
            transcript = json.loads(tr_path.read_text(encoding="utf-8"))
            words = _words_in_range(transcript, start, end)
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            print(
                f"  corrupt/unreadable transcript for {src_name}, "
                f"{warn_label}",
                file=sys.stderr,
            )
        else:
            start, end = snap_to_word_boundary(start, end, words)

    src_dur = source_durations.get(src_name)
    padded_start, padded_end = apply_padding(
        start, end,
        source_duration=src_dur if src_dur is not None and src_dur != float("inf") else None,
    )
    return padded_start, padded_end, words


def _copy_to_output(
    src: Path,
    dst: Path,
    ffmpeg_bin: str = "ffmpeg",
) -> int:
    """Copy *src* to *dst* via ffmpeg stream copy (preserves faststart).  Returns 0 on success, 1 on failure."""
    if src.resolve() == dst.resolve():
        return 0
    cmd = [ffmpeg_bin, "-y", "-i", str(src), "-c", "copy"]
    if dst.suffix.lower() == ".mp4":
        cmd.extend(["-movflags", "+faststart"])
    cmd.append(str(dst))
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        print("ffmpeg not found — ensure ffmpeg is installed and on PATH", file=sys.stderr)
        return 1
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace")[:500]
        print(f"copy-to-output failed: {detail}", file=sys.stderr)
        return 1
    return 0


def _probe_source_durations(
    edl: dict[str, Any],
    edit_dir: Path,
    ffprobe_bin: str = "ffprobe",
) -> dict[str, float]:
    """Probe durations for all unique sources in the EDL.

    Returns a dict mapping source name → duration in seconds.
    If probing fails for a source, its duration is set to ``float("inf")``
    so that padding clamping will not restrict the right edge.
    """
    source_durations: dict[str, float] = {}
    seen: set[str] = set()
    for r in edl["ranges"]:
        src_name = r["source"]
        if src_name in seen:
            continue
        seen.add(src_name)
        src_path = resolve_source_path(src_name, edl, edit_dir)
        try:
            source_durations[src_name] = probe_duration(src_path, ffprobe_bin)
        except (RuntimeError, FileNotFoundError, subprocess.CalledProcessError):
            print(
                f"  warning: could not probe duration for {src_name}, "
                "padding may overshoot source end",
                file=sys.stderr,
            )
            source_durations[src_name] = float("inf")
    return source_durations


def extract_all_segments(
    edl: dict[str, Any],
    edit_dir: Path,
    *,
    preview: bool = False,
    draft: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    source_durations: dict[str, float] | None = None,
) -> list[Path]:
    """Extract every EDL range into *edit_dir*/clips_graded/seg_NN.mp4.

    Returns the ordered list of segment paths.

    Grade resolution priority:
      1. Per-range ``grade`` field (highest priority)
      2. Top-level ``grade`` field (fallback)

    If the resolved grade is ``"auto"``, analyze each segment range with
    ``auto_grade_for_clip`` and apply a per-segment subtle correction.
    Otherwise, apply the resolved preset/raw filter.

    Padding (30–200 ms working window) is applied to each cut edge.
    If word-level transcript data is available, cut points are snapped to
    word boundaries (Hard Rule 6).

    Source duration is probed via ffprobe so that padding is clamped to
    the actual source bounds, preventing overshoot at the right edge.
    If *source_durations* is provided, it is used directly instead of
    probing again (avoids divergence between extraction and SRT building).
    """
    default_resolved = resolve_grade_filter(edl.get("grade"))

    clips_subdir = (
        "clips_draft" if draft else ("clips_preview" if preview else "clips_graded")
    )
    clips_dir = edit_dir / clips_subdir
    clips_dir.mkdir(parents=True, exist_ok=True)

    # Use pre-probed durations if provided, otherwise probe here
    if source_durations is None:
        source_durations = _probe_source_durations(edl, edit_dir, ffprobe_bin)

    ranges = edl["ranges"]
    seg_paths: list[Path] = []

    for i, r in enumerate(ranges):
        src_name = r["source"]
        src_path = resolve_source_path(src_name, edl, edit_dir)
        start = float(r["start"])
        end = float(r["end"])

        # Resolve grade: per-range overrides top-level
        range_grade = r.get("grade")
        if range_grade is not None:
            resolved = resolve_grade_filter(range_grade)
        else:
            resolved = default_resolved
        is_auto = resolved == "__AUTO__"

        padded_start, padded_end, _ = _resolve_segment_bounds(
            start, end, src_name, edit_dir, source_durations,
        )
        duration = padded_end - padded_start

        if duration <= 0:
            raise RuntimeError(
                f"segment {i} has zero/negative duration ({duration:.3f}s) "
                f"after padding — check EDL range and source duration"
            )

        # Resolve grade filter for this segment
        if is_auto:
            seg_filter, _stats = auto_grade_for_clip(
                src_path, start=padded_start, duration=duration, verbose=False
            )
        else:
            seg_filter = resolved

        out_path = clips_dir / f"seg_{i:02d}_{Path(src_name).stem}.mp4"

        note = r.get("beat") or r.get("note") or ""
        print(
            f"  [{i:02d}] {src_name}  "
            f"{padded_start:7.2f}-{padded_end:7.2f}  "
            f"({duration:5.2f}s)  {note}"
        )

        extract_segment(
            src_path, padded_start, duration, seg_filter, out_path,
            preview=preview, draft=draft, ffmpeg_bin=ffmpeg_bin,
            ffprobe_bin=ffprobe_bin,
        )
        seg_paths.append(out_path)

    return seg_paths


# ── Lossless concat (Hard Rule 2) ───────────────────────────────────────────


def concat_segments(
    segment_paths: list[Path],
    out_path: Path,
    edit_dir: Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    """Lossless concat via the concat demuxer.  Stream copy, no re-encode."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    concat_list = edit_dir / "_concat.txt"
    # Escape paths for ffmpeg concat demuxer format
    # Use single quotes with backslash-escaped inner single quotes (same as rough_cut.py)
    lines: list[str] = []
    for p in segment_paths:
        lines.append(f"file {quote_concat_path(p.resolve())}\n")
    concat_list.write_text("".join(lines), encoding="utf-8")

    cmd: list[str] = [
        ffmpeg_bin, "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c", "copy",
        "-movflags", "+faststart",
        str(out_path),
    ]
    validate_concat_demuxer_usage(cmd)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError:
        raise RuntimeError(f"{ffmpeg_bin} not found — ensure ffmpeg is installed and on PATH")
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or b"").decode(errors="replace")[:500]
        raise RuntimeError(f"ffmpeg concat failed: {detail}") from exc
    finally:
        concat_list.unlink(missing_ok=True)


# ── Master SRT (Hard Rule 5) ────────────────────────────────────────────────


def _srt_timestamp(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    h, rem = divmod(total_ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def build_master_srt(
    edl: dict[str, Any],
    edit_dir: Path,
    out_path: Path,
    *,
    ffprobe_bin: str = "ffprobe",
    source_durations: dict[str, float] | None = None,
) -> None:
    """Build an output-timeline SRT from per-source transcripts.

    - 2-word chunks (break on punctuation)
    - UPPERCASE text
    - Output times: ``output_time = word.start − padded_start + segment_offset``

    **Hard Rule 5**: segment offsets must use padded durations that match
    the actual extracted segment timeline, not the raw EDL range durations.
    Uses ``_resolve_segment_bounds`` so cut-point resolution stays in sync
    with ``extract_all_segments`` and SRT timestamps never drift.

    If *source_durations* is provided, it is used directly instead of
    probing again (ensures same durations as extraction phase).
    """
    ranges = edl["ranges"]

    # Use pre-probed durations if provided, otherwise probe here
    if source_durations is None:
        source_durations = _probe_source_durations(edl, edit_dir, ffprobe_bin)

    entries: list[tuple[float, float, str]] = []
    seg_offset = 0.0

    for r in ranges:
        src_name = r["source"]
        seg_start = float(r["start"])
        seg_end = float(r["end"])

        padded_start, padded_end, words_in_seg = _resolve_segment_bounds(
            seg_start, seg_end, src_name, edit_dir, source_durations,
            warn_label="skipping captions for this segment",
        )
        seg_duration = padded_end - padded_start
        if seg_duration <= 0:
            continue

        if not words_in_seg:
            print(
                f"  no transcript for {src_name}, "
                "skipping captions for this segment"
            )
            seg_offset += seg_duration
            continue

        # Group into 2-word chunks, break on punctuation
        chunks: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        for w in words_in_seg:
            text = (w.get("text") or "").strip()
            if not text:
                continue
            current.append(w)
            ends_in_punct = bool(text) and text[-1] in PUNCT_BREAK
            if len(current) >= 2 or ends_in_punct:
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)

        for chunk in chunks:
            # In the output video, this segment starts at padded_start in
            # source timeline, so the offset within the segment is relative
            # to padded_start, not the original seg_start.
            local_start = max(padded_start, chunk[0].get("start", padded_start))
            local_end = min(padded_end, chunk[-1].get("end", padded_end))
            out_start = max(0.0, local_start - padded_start) + seg_offset
            out_end = max(0.0, local_end - padded_start) + seg_offset
            if out_end <= out_start:
                out_end = out_start + 0.4
            text = " ".join((w.get("text") or "").strip() for w in chunk)
            text = re.sub(r"\s+", " ", text).strip()
            text = text.rstrip(",;:")
            text = text.upper()
            entries.append((out_start, out_end, text))

        seg_offset += seg_duration

    # Sort and write as SRT
    entries.sort(key=lambda e: e[0])
    lines: list[str] = []
    for idx, (a, b, t) in enumerate(entries, start=1):
        lines.append(str(idx))
        lines.append(f"{_srt_timestamp(a)} --> {_srt_timestamp(b)}")
        lines.append(t)
        lines.append("")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"master SRT → {out_path.name} ({len(entries)} cues)")


# ── Subtitle burning (Hard Rule 1) ──────────────────────────────────────────


def burn_subtitles_last(
    base_path: Path,
    srt_path: Path,
    out_path: Path,
    *,
    style: str = "bold-overlay",
    style_args: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    """Burn subtitles into *base_path* with subtitles applied LAST.

    Hard Rule 1: subtitles are always the terminal filter in the chain.

    The actual enforcement of this rule is in ``burn_subtitles`` which
    calls ``validate_subtitles_last`` and ``build_video_filter`` to
    guarantee subtitle filters are terminal.  This wrapper preserves
    the architectural boundary so callers always go through the
    "subtitles-last" entry point.
    """
    burn_subtitles(
        input_path=base_path,
        srt_path=srt_path,
        output_path=out_path,
        style=style,
        style_args=style_args,
        ffmpeg_bin=ffmpeg_bin,
    )


# ── CLI ─────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Render a final assembled video from an EDL JSON spec "
            "with per-segment grade, fades, subtitles, and loudnorm."
        ),
    )
    parser.add_argument(
        "edl",
        type=Path,
        help="Path to EDL JSON file.",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        required=True,
        help="Output video path.",
    )
    parser.add_argument(
        "--preview",
        action="store_true",
        help="Preview mode: 1080p, medium, CRF 22 — faster, evaluable for QC.",
    )
    parser.add_argument(
        "--draft",
        action="store_true",
        help="Draft mode: 720p, ultrafast, CRF 28 — cut-point verification only.",
    )
    parser.add_argument(
        "--build-subtitles",
        action="store_true",
        help="Build master.srt from transcripts + EDL offsets before compositing.",
    )
    parser.add_argument(
        "--no-subtitles",
        action="store_true",
        help="Skip subtitle burning even if the EDL references subtitles.",
    )
    parser.add_argument(
        "--no-loudnorm",
        action="store_true",
        help="Skip two-pass loudness normalization.",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        default="ffmpeg",
        help="Path to ffmpeg binary. Default: ffmpeg.",
    )
    parser.add_argument(
        "--ffprobe-bin",
        default="ffprobe",
        help="Path to ffprobe binary. Default: ffprobe.",
    )
    args = parser.parse_args(argv)
    if args.preview and args.draft:
        parser.error("--preview and --draft are mutually exclusive")
    if args.build_subtitles and args.no_subtitles:
        parser.error("--build-subtitles and --no-subtitles are mutually exclusive")
    return args


def render_edl(
    edl_path: Path,
    output_path: Path,
    *,
    preview: bool = False,
    draft: bool = False,
    build_subtitles: bool = False,
    no_subtitles: bool = False,
    no_loudnorm: bool = False,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> int:
    """Execute the full EDL render pipeline.  Returns 0 on success."""
    if not edl_path.exists():
        print(f"EDL file not found: {edl_path}", file=sys.stderr)
        return 1

    try:
        edl = json.loads(edl_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read EDL: {exc}", file=sys.stderr)
        return 1

    try:
        validate_edl(edl)
    except EDLSchemaError as exc:
        print(f"EDL schema error: {exc}", file=sys.stderr)
        return 1

    edit_dir = edl_path.parent

    # Probe source durations once — shared by extraction and SRT building
    # to prevent divergence if ffprobe fails intermittently
    source_durations = _probe_source_durations(edl, edit_dir, ffprobe_bin)

    # 1. Extract per-segment
    print(f"extracting {len(edl['ranges'])} segment(s)")
    try:
        segment_paths = extract_all_segments(
            edl, edit_dir,
            preview=preview, draft=draft, ffmpeg_bin=ffmpeg_bin,
            ffprobe_bin=ffprobe_bin,
            source_durations=source_durations,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"segment extraction failed: {exc}", file=sys.stderr)
        return 1

    # 2. Concat → base
    base_name = (
        "base_draft.mp4" if draft
        else ("base_preview.mp4" if preview else "base.mp4")
    )
    base_path = edit_dir / base_name
    print(f"concat → {base_path.name}")
    try:
        concat_segments(segment_paths, base_path, edit_dir, ffmpeg_bin=ffmpeg_bin)
    except RuntimeError as exc:
        print(f"concat failed: {exc}", file=sys.stderr)
        return 1

    # 3. Subtitles: build if requested, resolve final path
    subs_path: Path | None = None
    if not no_subtitles:
        if build_subtitles:
            subs_path = edit_dir / "master.srt"
            try:
                build_master_srt(
                    edl, edit_dir, subs_path,
                    ffprobe_bin=ffprobe_bin,
                    source_durations=source_durations,
                )
            except (OSError, RuntimeError) as exc:
                print(f"subtitle build failed: {exc}", file=sys.stderr)
                return 1
        elif edl.get("subtitles"):
            subs_val = edl["subtitles"]
            # subtitles can be a string path or a dict with style info + optional path
            if isinstance(subs_val, str):
                subs_path = resolve_path(subs_val, edit_dir)
                if not subs_path.exists():
                    print(
                        f"warning: subtitles path does not exist: {subs_path}",
                        file=sys.stderr,
                    )
                    subs_path = None
            elif isinstance(subs_val, dict):
                dict_path = subs_val.get("path")
                if dict_path:
                    subs_path = resolve_path(dict_path, edit_dir)
                    if not subs_path.exists():
                        print(
                            f"warning: subtitles path does not exist: {subs_path}",
                            file=sys.stderr,
                        )
                        subs_path = None

    # Determine subtitle style
    sub_style = "bold-overlay"
    sub_style_args: str | None = None
    sub_cfg = edl.get("subtitles")
    if isinstance(sub_cfg, dict):
        sub_style = sub_cfg.get("style", sub_style)
        sub_style_args = sub_cfg.get("force_style")

    # 4. Apply subtitles (last in filter chain — Hard Rule 1)
    current_path = base_path
    if subs_path is not None and subs_path.exists():
        sub_output = output_path.with_suffix(".subtitled.mp4")
        print(f"burning subtitles (style: {sub_style}) → {sub_output.name}")
        try:
            burn_subtitles_last(
                current_path, subs_path, sub_output,
                style=sub_style, style_args=sub_style_args,
                ffmpeg_bin=ffmpeg_bin,
            )
        except (ValueError, RuntimeError, FileNotFoundError) as exc:
            print(f"subtitle burning error: {exc}", file=sys.stderr)
            return 1
        current_path = sub_output

    # 5. Two-pass loudnorm
    if no_loudnorm:
        # Just copy/rename current to output
        if current_path != output_path:
            if _copy_to_output(current_path, output_path, ffmpeg_bin) != 0:
                return 1
    else:
        print("loudness normalization → social-ready (−14 LUFS / −1 dBTP / LRA 11)")
        try:
            success = apply_loudnorm_two_pass(
                current_path, output_path,
                ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
            )
        except FileNotFoundError:
            print("ffmpeg/ffprobe not found — ensure both are installed and on PATH", file=sys.stderr)
            return 1
        except subprocess.CalledProcessError as exc:
            print(f"loudnorm failed: {exc}", file=sys.stderr)
            return 1
        except RuntimeError as exc:
            print(f"loudnorm probe error: {exc}", file=sys.stderr)
            return 1

        if not success:
            print("loudnorm measurement failed, using preview mode", file=sys.stderr)
            try:
                apply_loudnorm_preview(
                    current_path, output_path,
                    ffmpeg_bin=ffmpeg_bin, ffprobe_bin=ffprobe_bin,
                )
            except (FileNotFoundError, subprocess.CalledProcessError, RuntimeError) as exc:
                print(f"loudnorm preview fallback failed: {exc}", file=sys.stderr)
                # Last resort: copy as-is
                if _copy_to_output(current_path, output_path, ffmpeg_bin) != 0:
                    return 1

    # Clean up intermediate files (never delete the final output)
    if current_path.resolve() != output_path.resolve():
        if current_path != base_path:
            current_path.unlink(missing_ok=True)
    if base_path.resolve() != output_path.resolve() and base_path.exists():
        base_path.unlink(missing_ok=True)

    # Clean up extracted clips
    clips_subdir = (
        "clips_draft" if draft else ("clips_preview" if preview else "clips_graded")
    )
    clips_dir = edit_dir / clips_subdir
    if clips_dir.is_dir():
        for clip in clips_dir.iterdir():
            clip.unlink(missing_ok=True)
        try:
            clips_dir.rmdir()
        except OSError:
            shutil.rmtree(clips_dir, ignore_errors=True)

    if output_path.exists():
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"\ndone: {output_path} ({size_mb:.1f} MB)")
        return 0
    else:
        print(f"\nerror: {output_path} (output file missing)", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return render_edl(
        edl_path=args.edl,
        output_path=args.output,
        preview=args.preview,
        draft=args.draft,
        build_subtitles=args.build_subtitles,
        no_subtitles=args.no_subtitles,
        no_loudnorm=args.no_loudnorm,
        ffmpeg_bin=args.ffmpeg_bin,
        ffprobe_bin=args.ffprobe_bin,
    )


if __name__ == "__main__":
    raise SystemExit(main())