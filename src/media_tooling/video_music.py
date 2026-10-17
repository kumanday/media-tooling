"""Optional score and sound effects for a finished video (ElevenLabs video-to-music).

Use only when the user wants background music and/or sound effects. Two steps:

``generate VIDEO --out-dir DIR``
    Sends the picture-locked video to ``POST /v1/music/video-to-music``. The
    model scores the video's own cuts and motion, so generate from the final edit.
    With ``--separate-tracks`` (the default) the response is a ZIP holding
    ``music.mp3`` and ``sfx.mp3`` (with ``--sfx``), each matched to the video's
    length, so music and effects get separate levels. Writes ``request.json``
    for provenance.

``mix VIDEO --music DIR/music.mp3 [--sfx DIR/sfx.mp3] -o OUT.mp4``
    Lays the stems under the video's existing audio (the narration). It measures
    the narration and the stems (EBU R128 momentary loudness) and sets the music
    gain so the ducked bed sits 20 dB under the voice while it speaks (at least
    12 dB at the 10th percentile), and the SFX gain so the loudest effect sits
    8 dB under speech level. Narrated renders and video-to-music stems arrive at
    very different levels, so fixed gains do not carry from one film to the
    next. The narration keys a sidechain compressor that ducks the music; its
    threshold follows the narration's loudness. One linear gain then brings the
    mix to the loudness target and a 4x-oversampled limiter holds the true-peak
    ceiling, so pauses keep their level relative to speech. Prints the measured
    margins. ``--music-db`` and ``--sfx-db`` set fixed gains instead. Video is
    stream-copied.

Reads ELEVENLABS_API_KEY from the environment.
"""

from __future__ import annotations

import argparse
import io
import json
import math
import re
import statistics
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

from media_tooling import tts

VIDEO_TO_MUSIC_URL = "https://api.elevenlabs.io/v1/music/video-to-music"
MAX_BYTES = 200 * 1024 * 1024

SILENCE = -120.0  # LUFS recorded for silent, -inf and nan frames
AUDIBLE = -70.0  # momentary frames at or below this count as silent
SPEECH_GATE = 15.0  # narration frames within this many LU of its integrated loudness count as speech
PAUSE_GATE = 30.0  # narration frames more than this many LU below it count as pauses
STEM_GATE = 30.0  # stem frames within this many LU of the stem's integrated loudness have sound
DUCK = "ratio=6:attack=25:release=350"
FIXED_DUCK_THRESHOLD = 0.03  # used when the video has no narration to measure
FRAME_RE = re.compile(r"\bt:\s*[\d.]+\s+TARGET:\S+\s+LUFS\s+M:\s*(\S+)")


def generate(video: Path, out_dir: Path, *, description: str | None, tags: list[str], model: str, sfx: bool,
             separate_tracks: bool, use_audio_as_reference: bool) -> list[Path]:
    if video.stat().st_size > MAX_BYTES:
        raise ValueError("video-to-music accepts at most 200 MB of video; export a lighter proxy of the final edit")
    api_key = tts.resolve_api_key()
    requests = tts._requests_module
    assert requests is not None  # guarded by resolve_api_key
    form: list[tuple[str, str]] = [("model_id", model), ("add_sfx", str(sfx).lower()),
                                   ("separate_tracks", str(separate_tracks).lower()),
                                   ("use_audio_as_reference", str(use_audio_as_reference).lower())]
    if description:
        form.append(("description", description))
    form += [("tags", t) for t in tags]
    with video.open("rb") as fh:
        try:
            response = requests.post(VIDEO_TO_MUSIC_URL, headers={"xi-api-key": api_key}, data=form,
                                     files=[("videos", (video.name, fh, "video/mp4"))], timeout=1200)
        except requests.exceptions.RequestException:
            raise RuntimeError("Could not reach ElevenLabs. Check your connection and retry.") from None
    if not response.ok:
        raise RuntimeError(f"video-to-music failed: HTTP {response.status_code} {response.text[:300]}")
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    content = bytes(response.content)
    if content[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                target = out_dir / Path(name).name
                target.write_bytes(zf.read(name))
                written.append(target)
    else:
        target = out_dir / "music.mp3"
        target.write_bytes(content)
        written.append(target)
    record: dict[str, Any] = {"endpoint": "POST /v1/music/video-to-music", "video": str(video), "model_id": model,
                              "description": description, "tags": tags, "add_sfx": sfx, "separate_tracks": separate_tracks,
                              "use_audio_as_reference": use_audio_as_reference, "outputs": [p.name for p in written]}
    (out_dir / "request.json").write_text(json.dumps(record, indent=1), encoding="utf-8")
    return written


@dataclass(frozen=True)
class Loudness:
    """ebur128 measurement: momentary loudness (400 ms windows every 100 ms), integrated loudness, true peak."""

    momentary: list[float]
    integrated: float
    true_peak: float | None = None


def _level(text: str) -> float:
    value = float(text)
    return max(value, SILENCE) if math.isfinite(value) else SILENCE


def parse_ebur128(log: str) -> Loudness:
    if "Summary:" not in log:
        raise RuntimeError("ffmpeg ebur128 printed no loudness summary")
    summary = log[log.rindex("Summary:"):]
    integrated = re.search(r"I:\s*(\S+) LUFS", summary)
    if integrated is None:
        raise RuntimeError("ffmpeg ebur128 summary has no integrated loudness")
    peak = re.search(r"Peak:\s*(\S+) dBFS", summary)
    return Loudness([_level(m) for m in FRAME_RE.findall(log)], _level(integrated.group(1)),
                    _level(peak.group(1)) if peak else None)


def measure(inputs: list[Path], graph: str, *, true_peak: bool = False) -> Loudness:
    """Loudness of the ``[a]`` output of GRAPH, a filter_complex over INPUTS."""
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-nostats", "-loglevel", "info"]
    for path in inputs:
        cmd += ["-i", str(path)]
    cmd += ["-filter_complex", f"{graph};[a]ebur128=peak={'true' if true_peak else 'none'}[meter]",
            "-map", "[meter]", "-f", "null", "-"]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"loudness measurement failed: {proc.stderr.strip()[-500:]}")
    return parse_ebur128(proc.stderr)


def speech_frames(voice: Loudness) -> list[int]:
    gate = max(voice.integrated - SPEECH_GATE, AUDIBLE)
    return [i for i, v in enumerate(voice.momentary) if v >= gate]


def pause_frames(voice: Loudness) -> list[int]:
    gate = voice.integrated - PAUSE_GATE
    return [i for i, v in enumerate(voice.momentary) if v < gate]


def speech_level(voice: Loudness) -> float | None:
    """Median momentary loudness of the narration while it speaks."""
    frames = speech_frames(voice)
    return statistics.median(voice.momentary[i] for i in frames) if frames else None


def with_sound(frames: list[int], *stems: Loudness | None) -> list[int]:
    """The FRAMES where any of STEMS (measured at 0 dB) has sound: within STEM_GATE LU of its integrated loudness."""
    def sounds(stem: Loudness | None, i: int) -> bool:
        return stem is not None and i < len(stem.momentary) and \
            stem.momentary[i] > max(stem.integrated - STEM_GATE, AUDIBLE)

    return [i for i in frames if any(sounds(stem, i) for stem in stems)]


def _at(levels: list[float], i: int) -> float:
    return levels[i] if i < len(levels) else SILENCE


def under_voice(voice: Loudness, bed: list[float], frames: list[int]) -> list[float]:
    """How far the bed sits under the voice in each of FRAMES (dB), sorted."""
    return sorted(voice.momentary[i] - _at(bed, i) for i in frames)


def bed_momentary(ducked: Loudness, music_db: float, fx: Loudness | None = None, sfx_db: float = 0.0) -> list[float]:
    """Momentary loudness of the bed at the given gains, predicted from stems measured at 0 dB.

    Loudness of uncorrelated signals adds as power, so each frame is the power sum of the two stems."""
    def power(levels: list[float], i: int, gain: float) -> float:
        return 0.0 if _at(levels, i) <= SILENCE else 10 ** ((levels[i] + gain) / 10)

    stems = [(ducked.momentary, music_db)] + ([(fx.momentary, sfx_db)] if fx is not None else [])
    out = []
    for i in range(max(len(levels) for levels, _ in stems)):
        total = sum(power(levels, i, gain) for levels, gain in stems)
        out.append(10 * math.log10(total) if total > 0 else SILENCE)
    return out


def derive_music_db(voice: Loudness, ducked: Loudness, *, under: float, min_under: float, fx: Loudness | None = None,
                    sfx_db: float = 0.0) -> float:
    """Music gain that puts the bed UNDER dB below the voice while it speaks (median), and at least MIN_UNDER dB
    below at the 10th percentile. DUCKED is the ducked music measured at 0 dB; the duck's gain reduction depends
    only on the narration, so the music level moves dB for dB with its gain. FX (the SFX measured at 0 dB, to be
    played at SFX_DB) counts toward the bed."""
    speaking = speech_frames(voice)
    if not with_sound(speaking, ducked):  # silent stem, or music only where nobody speaks
        level = speech_level(voice)
        audible = [m for m in ducked.momentary if m > AUDIBLE]
        return round(level - under - statistics.median(audible), 1) if level is not None and audible else 0.0

    def meets(music_db: float, fx: Loudness | None) -> bool:
        diffs = under_voice(voice, bed_momentary(ducked, music_db, fx, sfx_db), with_sound(speaking, ducked, fx))
        return statistics.median(diffs) >= under and diffs[len(diffs) // 10] >= min_under

    low, high = -90.0, 40.0
    if fx is not None and not meets(low, fx):  # the SFX alone break the targets; set the music on its own
        fx = None
    for _ in range(40):
        mid = (low + high) / 2
        low, high = (mid, high) if meets(mid, fx) else (low, mid)
    return math.floor(low * 10) / 10


def derive_sfx_db(voice: Loudness, sfx: Loudness, *, under: float) -> float:
    """SFX gain that puts the loudest effect (momentary) UNDER dB below speech level."""
    level = speech_level(voice)
    loudest = max(sfx.momentary, default=SILENCE)
    if level is None or loudest <= AUDIBLE:
        return 0.0
    return round(level - under - loudest, 1)


def mix_graph(*, has_sfx: bool, music_db: float, sfx_db: float, duck: bool, threshold: float = FIXED_DUCK_THRESHOLD,
              voice: bool = True, out: str = "mix") -> str:
    """Static mix ending in ``[OUT]``: narration (input 0), music (input 1) and SFX (input 2) at fixed gains.

    The narration keys a sidechain compressor that ducks the music. With voice=False the graph renders the
    bed alone (music and SFX) for measurement."""
    parts: list[str] = []
    if duck:  # the narration keys the compressor; the music dips while the voice speaks
        parts += ["[0:a]asplit=2[voice][key]" if voice else "[0:a]anull[key]", f"[1:a]volume={music_db:.2f}dB[m0]",
                  f"[m0][key]sidechaincompress=threshold={threshold:.5f}:{DUCK}[music]"]
    else:
        parts += ["[0:a]anull[voice]"] if voice else []
        parts.append(f"[1:a]volume={music_db:.2f}dB[music]")
    streams = (["[voice]"] if voice else []) + ["[music]"]
    if has_sfx:
        parts.append(f"[2:a]volume={sfx_db:.2f}dB[fx]")
        streams.append("[fx]")
    if len(streams) == 1:
        parts.append(f"[music]anull[{out}]")
    else:
        parts.append(f"{''.join(streams)}amix=inputs={len(streams)}:duration={'first' if voice else 'longest'}"
                     f":normalize=0[{out}]")
    return ";".join(parts)


def mix_filter(*, has_sfx: bool, music_db: float, sfx_db: float, duck: bool, threshold: float, gain_db: float,
               limit_db: float) -> str:
    """The encode graph: static mix, one linear gain to the loudness target, then a 4x-oversampled peak limiter."""
    limit = min(1.0, max(0.0625, 10 ** (limit_db / 20)))
    return (mix_graph(has_sfx=has_sfx, music_db=music_db, sfx_db=sfx_db, duck=duck, threshold=threshold)
            + f";[mix]volume={gain_db:.2f}dB,aresample=192000,alimiter=limit={limit:.4f}:level=disabled,"
              "aresample=48000[out]")


@dataclass(frozen=True)
class MixReport:
    narration_lufs: float
    speech_lufs: float | None
    music_db: float
    music_derived: bool
    sfx_db: float | None
    sfx_derived: bool
    music_under: float
    music_min_under: float
    sfx_under: float
    bed_under: float | None
    bed_under_p10: float | None
    bed_pause_under: float | None
    sfx_loudest_under: float | None
    gain_db: float
    limit_db: float
    peak_reduction_db: float
    output_lufs: float
    output_true_peak: float

    def summary(self) -> list[str]:
        def db(x: float | None) -> str:
            return "n/a" if x is None else f"{x:.1f} dB"

        speech = "" if self.speech_lufs is None else f", {self.speech_lufs:.1f} LUFS while speaking (momentary median)"
        lines = [f"narration: {self.narration_lufs:.1f} LUFS integrated{speech}"]
        gains = f"gains: music {self.music_db:+.1f} dB ({'derived' if self.music_derived else 'given'})"
        if self.sfx_db is not None:
            gains += f", SFX {self.sfx_db:+.1f} dB ({'derived' if self.sfx_derived else 'given'})"
        lines.append(gains)
        lines.append(f"bed under the voice while speaking: {db(self.bed_under)} median (target {self.music_under:g}), "
                     f"{db(self.bed_under_p10)} at the 10th percentile (floor {self.music_min_under:g})")
        lines.append(f"bed in narration pauses: {db(self.bed_pause_under)} under speech level")
        if self.sfx_db is not None:
            lines.append(f"loudest SFX: {db(self.sfx_loudest_under)} under speech level (target {self.sfx_under:g})")
        limiter = f", limiter took up to {self.peak_reduction_db:.1f} dB off peaks" if self.peak_reduction_db > 0.05 else ""
        lines.append(f"output: {self.output_lufs:.1f} LUFS integrated, {self.output_true_peak:.1f} dBTP "
                     f"(gain {self.gain_db:+.1f} dB{limiter})")
        return lines


def _encode(inputs: list[Path], graph: str, out: Path) -> None:
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y"]
    for path in inputs:
        cmd += ["-i", str(path)]
    cmd += ["-filter_complex", graph, "-map", "0:v", "-map", "[out]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-ar", "48000", "-movflags", "+faststart", str(out)]
    subprocess.run(cmd, check=True)


def mix(video: Path, music: Path, sfx: Path | None, out: Path, *, music_db: float | None = None,
        sfx_db: float | None = None, duck: bool = True, lufs: float = -14.0, true_peak: float = -1.0,
        music_under: float = 20.0, music_min_under: float = 12.0, sfx_under: float = 8.0,
        duck_threshold_db: float = -5.0) -> MixReport:
    voice = measure([video], "[0:a]anull[a]")
    level = speech_level(voice)
    if level is None and (music_db is None or (sfx is not None and sfx_db is None)):
        raise ValueError(f"no narration found in {video.name}; pass --music-db (and --sfx-db) to mix at fixed gains")
    threshold = FIXED_DUCK_THRESHOLD if level is None else \
        min(1.0, max(0.001, 10 ** ((voice.integrated + duck_threshold_db) / 20)))
    ducked = measure([video, music], mix_graph(has_sfx=False, music_db=0.0, sfx_db=0.0, duck=duck, threshold=threshold,
                                               voice=False, out="a"))
    fx = measure([sfx], "[0:a]anull[a]") if sfx else None
    sfx_derived = fx is not None and sfx_db is None
    if fx is not None and sfx_db is None:
        sfx_db = derive_sfx_db(voice, fx, under=sfx_under)
    fx_db = 0.0 if sfx_db is None else sfx_db
    music_derived = music_db is None
    if music_db is None:
        music_db = derive_music_db(voice, ducked, under=music_under, min_under=music_min_under, fx=fx, sfx_db=fx_db)
    stems = [video, music] + ([sfx] if sfx else [])
    graph = partial(mix_graph, has_sfx=sfx is not None, music_db=music_db, sfx_db=fx_db, duck=duck,
                    threshold=threshold)
    bed = measure(stems, graph(voice=False, out="a"))
    premix = measure(stems, graph(out="a"), true_peak=True)
    if premix.integrated <= AUDIBLE:
        raise ValueError("the mix is silent; check the video's audio and the stems")
    margins = under_voice(voice, bed.momentary, with_sound(speech_frames(voice), ducked, fx))
    pauses = [_at(bed.momentary, i) for i in with_sound(pause_frames(voice), ducked, fx)]
    loudest = max(fx.momentary, default=SILENCE) + fx_db if fx is not None else SILENCE

    # One linear gain to the loudness target keeps pauses at their level relative to speech (a dynamic
    # loudnorm lifts them). The limiter holds the ceiling; the encode is re-measured and corrected.
    gain, limit = lufs - premix.integrated, true_peak - 0.5
    pending = out.with_name(f"{out.stem}.partial{out.suffix}")
    out.parent.mkdir(parents=True, exist_ok=True)
    attempts = 4
    for attempt in range(attempts):
        _encode(stems, mix_filter(has_sfx=sfx is not None, music_db=music_db, sfx_db=fx_db, duck=duck,
                                  threshold=threshold, gain_db=gain, limit_db=limit), pending)
        result = measure([pending], "[0:a]anull[a]", true_peak=True)
        peak = SILENCE if result.true_peak is None else result.true_peak
        if attempt == attempts - 1:
            break
        if peak > true_peak:
            limit -= peak - true_peak + 0.2
        elif abs(result.integrated - lufs) > 0.1:
            gain += lufs - result.integrated
        else:
            break
    if peak > true_peak:
        pending.unlink(missing_ok=True)
        raise RuntimeError(f"true peak {peak:.1f} dBTP stays above the {true_peak:g} dBTP ceiling")
    pending.replace(out)
    premix_peak = SILENCE if premix.true_peak is None else premix.true_peak
    return MixReport(
        narration_lufs=voice.integrated, speech_lufs=level, music_db=music_db, music_derived=music_derived,
        sfx_db=sfx_db if sfx else None, sfx_derived=sfx_derived, music_under=music_under,
        music_min_under=music_min_under, sfx_under=sfx_under,
        bed_under=statistics.median(margins) if margins else None,
        bed_under_p10=margins[len(margins) // 10] if margins else None,
        bed_pause_under=level - statistics.median(pauses) if level is not None and pauses else None,
        sfx_loudest_under=level - loudest if level is not None and loudest > AUDIBLE else None,
        gain_db=gain, limit_db=limit, peak_reduction_db=max(0.0, premix_peak + gain - limit),
        output_lufs=result.integrated, output_true_peak=peak)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Optional score and SFX for a finished video (ElevenLabs video-to-music).")
    sub = p.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("generate", help="score a picture-locked video; writes music.mp3 (and sfx.mp3)")
    g.add_argument("video")
    g.add_argument("--out-dir", required=True)
    g.add_argument("--description", default=None, help="what the music should be (max 4100 characters)")
    g.add_argument("--tag", action="append", default=[], help="style tag, repeatable (max 10)")
    g.add_argument("--model", default="music_v2_5", help="music_v1, music_v2 or music_v2_5 (default)")
    g.add_argument("--sfx", action="store_true", help="also generate sound effects from the video")
    g.add_argument("--mixed", action="store_true", help="one mixed file instead of separate music and SFX tracks")
    g.add_argument("--use-audio-as-reference", action="store_true",
                   help="let the video's own audio guide genre, BPM and mood (off for narrated videos)")
    m = sub.add_parser("mix", help="lay music (and SFX) under the video's narration")
    m.add_argument("video")
    m.add_argument("--music", required=True)
    m.add_argument("--sfx", default=None)
    m.add_argument("-o", "--output", required=True)
    m.add_argument("--music-under-db", type=float, default=20.0,
                   help="target: music bed this many dB under the voice while it speaks, median (default 20)")
    m.add_argument("--music-min-under-db", type=float, default=12.0,
                   help="and at least this many dB under it at the 10th percentile (default 12)")
    m.add_argument("--sfx-under-db", type=float, default=8.0,
                   help="target: loudest SFX this many dB under speech level (default 8)")
    m.add_argument("--music-db", type=float, default=None, help="fixed music gain before ducking (dB) instead of the target")
    m.add_argument("--sfx-db", type=float, default=None, help="fixed SFX gain (dB) instead of the target")
    m.add_argument("--duck-threshold-db", type=float, default=-5.0,
                   help="duck threshold relative to the narration's integrated loudness (dB, default -5)")
    m.add_argument("--no-duck", action="store_true", help="do not duck the music under the voice")
    m.add_argument("--lufs", type=float, default=-14.0, help="integrated loudness target")
    m.add_argument("--true-peak", type=float, default=-1.0, help="true-peak ceiling (dBTP)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    try:
        if a.cmd == "generate":
            if len(a.tag) > 10:
                raise ValueError("at most 10 tags")
            files = generate(Path(a.video), Path(a.out_dir), description=a.description, tags=a.tag, model=a.model, sfx=a.sfx,
                             separate_tracks=not a.mixed, use_audio_as_reference=a.use_audio_as_reference)
            print("wrote " + ", ".join(str(f) for f in files))
        else:
            out = Path(a.output)
            if out.resolve() == Path(a.video).resolve():
                raise ValueError("output must differ from the input video")
            report = mix(Path(a.video), Path(a.music), Path(a.sfx) if a.sfx else None, out, music_db=a.music_db,
                         sfx_db=a.sfx_db, duck=not a.no_duck, lufs=a.lufs, true_peak=a.true_peak,
                         music_under=a.music_under_db, music_min_under=a.music_min_under_db, sfx_under=a.sfx_under_db,
                         duck_threshold_db=a.duck_threshold_db)
            print("\n".join(report.summary()))
            print(f"wrote {out}")
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
