"""Narration timing for raea compositions (pilot backend for motion graphics).

``media-raea-timing`` turns the narration timing media-tooling already writes
into the files a raea composition reads, so cues, captions and voice placement
follow the spoken words instead of hand-typed frame numbers:

- ``words.json``: every spoken word on the film clock, ``[{text, start, end}]``
  in seconds (the shape ``raea render --words`` and ``raea check --words`` read);
- ``words-<scene>.json``: the same words on each scene's own clock, for
  rendering one scene as its own composition (fast stills and drafts);
- ``scenes.json``: ``fps``, ``total``, ``frames`` and per scene ``id``,
  ``start``, ``dur``, ``from`` and ``frames`` (frame numbers rounded once, so
  neighbouring scenes never overlap or leave a gap) and named ``cues`` in
  scene-local seconds; ``voices`` (``src`` relative to ``media/`` for
  ``staticFile``, ``start``, ``scene``); and ``captions`` when the input has
  them.

Inputs, one of:

- ``--audio-meta``: a ``media-tts-frames`` ``audio_meta.json``. One scene per
  voice frame, laid end to end in frame order: ``--lead`` seconds of silence
  open the first scene, each scene lasts its clip's ``duration_s`` (which
  already includes the clip's tail) plus ``--hold``. ``{@name}`` cues become
  scene cues.
- ``--timing``: a ``timing.json`` from the motion-graphics skill's
  ``narration_timing.py`` (single-take narration cut into segments), whose
  scene windows, word clocks, voice segments and caption groups are kept.

Voice files are copied into ``<root>/media/voice/`` (raea serves only the
project's ``media/`` folder) unless they are already inside it or
``--no-copy`` is given.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Scene:
    id: str
    start: float
    dur: float
    cues: dict[str, float] = field(default_factory=dict)


@dataclass
class Voice:
    path: Path
    start: float
    scene: str


@dataclass
class Timeline:
    scenes: list[Scene]
    words: list[dict[str, Any]]  # text, start, end on the film clock
    voices: list[Voice]
    captions: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(max(s.start + s.dur for s in self.scenes), 3)


class TimingError(ValueError):
    pass


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise TimingError(f"{path}: not found") from None
    except json.JSONDecodeError as exc:
        raise TimingError(f"{path}: not JSON ({exc})") from None


def _scene_ids(given: list[str] | None, defaults: list[str]) -> list[str]:
    if not given:
        return defaults
    if len(given) != len(defaults):
        raise TimingError(f"--scene-ids names {len(given)} scenes; the input has {len(defaults)}")
    if len(set(given)) != len(given):
        raise TimingError("--scene-ids repeats a name")
    return given


def from_audio_meta(path: Path, *, lead: float = 0.0, hold: float = 0.0, scene_ids: list[str] | None = None,
                    audio_base: Path | None = None) -> Timeline:
    """media-tts-frames audio_meta.json: one scene per voice frame, end to end in frame order."""
    meta = _read_json(path)
    voices = sorted(meta.get("voices") or [], key=lambda v: v["frame"])
    if not voices:
        raise TimingError(f"{path}: no voices[] (run media-tts-frames first)")
    base = audio_base or path.parent
    ids = _scene_ids(scene_ids, [f"f{int(v['frame']):02d}" for v in voices])
    scenes: list[Scene] = []
    words: list[dict[str, Any]] = []
    out_voices: list[Voice] = []
    t = 0.0
    for k, (v, sid) in enumerate(zip(voices, ids)):
        offset = lead if k == 0 else 0.0
        voice_at = round(t + offset, 3)
        dur = round(offset + float(v["duration_s"]) + hold, 3)
        cues = {c["name"]: round(offset + float(c["t"]), 3) for c in v.get("cues") or []}
        scenes.append(Scene(sid, round(t, 3), dur, cues))
        out_voices.append(Voice(base / v["path"], voice_at, sid))
        for w in v.get("words") or []:
            words.append({"text": w["text"], "start": round(voice_at + float(w["start"]), 3),
                          "end": round(voice_at + float(w["end"]), 3)})
        t += dur
    return Timeline(scenes, words, out_voices)


def from_narration_timing(path: Path, *, scene_ids: list[str] | None = None, audio_base: Path | None = None) -> Timeline:
    """narration_timing.py timing.json: scene windows, output-time words, voice segments and captions."""
    data = _read_json(path)
    raw_scenes = data.get("scenes") or []
    if not raw_scenes:
        raise TimingError(f"{path}: no scenes[] (is this a narration_timing.py timing.json?)")
    base = audio_base or path.parent
    ids = _scene_ids(scene_ids, [str(s["id"]) for s in raw_scenes])
    scenes = [Scene(sid, round(float(s["start"]), 3), round(float(s["duration"]), 3)) for s, sid in zip(raw_scenes, ids)]
    words = [{"text": w["w"], "start": round(float(w["s"]), 3), "end": round(float(w["e"]), 3)} for w in data.get("words") or []]

    def scene_at(t: float) -> str:
        for s in scenes:
            if s.start <= t < s.start + s.dur:
                return s.id
        return scenes[-1].id

    voices = [Voice(base / v["src"], round(float(v["start"]), 3), scene_at(float(v["start"]))) for v in data.get("vo") or []]
    captions = [{"text": c["text"], "start": round(float(c["start"]), 3), "end": round(float(c["end"]), 3)}
                for c in data.get("captions") or []]
    return Timeline(scenes, words, voices, captions)


def _media_path(src: Path, root: Path, copy: bool) -> str:
    """The voice's path relative to <root>/media (what staticFile takes), copying it there when needed."""
    media = (root / "media").resolve()
    src = src.resolve()
    if src.is_relative_to(media):
        return src.relative_to(media).as_posix()
    if not copy:
        raise TimingError(f"{src} is outside {media}; raea serves only media/ (drop --no-copy to copy it there)")
    if not src.is_file():
        raise TimingError(f"voice file not found: {src}")
    dest = media / "voice" / src.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.exists() or dest.stat().st_size != src.stat().st_size or dest.read_bytes() != src.read_bytes():
        shutil.copy2(src, dest)
    return dest.relative_to(media).as_posix()


def write(timeline: Timeline, root: Path, *, fps: int = 30, copy: bool = True) -> list[Path]:
    """Write words.json, words-<scene>.json and scenes.json into root; returns the files written."""
    if not timeline.words:
        raise TimingError("the input has no word timings; cues and captions need them")
    root.mkdir(parents=True, exist_ok=True)

    def frame(t: float) -> int:
        return round(t * fps)

    written: list[Path] = []

    def dump(name: str, data: Any) -> None:
        p = root / name
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        written.append(p)

    dump("words.json", timeline.words)
    scenes_out = []
    for s in timeline.scenes:
        end = s.start + s.dur
        local = [{**w, "start": round(w["start"] - s.start, 3), "end": round(w["end"] - s.start, 3)}
                 for w in timeline.words if s.start <= w["start"] < end]
        dump(f"words-{s.id}.json", local)
        scenes_out.append({"id": s.id, "start": s.start, "dur": s.dur, "from": frame(s.start),
                           "frames": frame(end) - frame(s.start), "cues": s.cues})
    voices = [{"src": _media_path(v.path, root, copy), "start": v.start, "scene": v.scene} for v in timeline.voices]
    out: dict[str, Any] = {"fps": fps, "total": timeline.total, "frames": frame(timeline.total),
                           "scenes": scenes_out, "voices": voices}
    if timeline.captions:
        out["captions"] = timeline.captions
    dump("scenes.json", out)
    return written


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Narration timing (words, scenes, voices) for a raea composition.")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--audio-meta", type=Path, help="media-tts-frames audio_meta.json")
    src.add_argument("--timing", type=Path, help="narration_timing.py timing.json")
    p.add_argument("--root", type=Path, default=Path("."), help="raea project root (the folder with edit.tsx); default .")
    p.add_argument("--fps", type=int, default=30, help="composition frame rate for from/frames (default 30)")
    p.add_argument("--lead", type=float, default=0.0, help="audio-meta: seconds of silence before the first voice")
    p.add_argument("--hold", type=float, default=0.0, help="audio-meta: extra seconds after each voice clip")
    p.add_argument("--scene-ids", help="comma-separated scene ids, one per scene (default f01, f02, ... or the timing ids)")
    p.add_argument("--audio-base", type=Path, help="folder the input's voice paths are relative to (default: the input's folder)")
    p.add_argument("--no-copy", action="store_true", help="fail instead of copying voice files into <root>/media/voice")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    ids = [x.strip() for x in a.scene_ids.split(",")] if a.scene_ids else None
    try:
        if a.audio_meta:
            timeline = from_audio_meta(a.audio_meta, lead=a.lead, hold=a.hold, scene_ids=ids, audio_base=a.audio_base)
        else:
            timeline = from_narration_timing(a.timing, scene_ids=ids, audio_base=a.audio_base)
        written = write(timeline, a.root, fps=a.fps, copy=not a.no_copy)
    except TimingError as exc:
        print(f"media-raea-timing: {exc}", file=sys.stderr)
        return 1
    print(f"{len(timeline.scenes)} scenes, {len(timeline.words)} words, {timeline.total:.2f} s at {a.fps} fps")
    for s in timeline.scenes:
        print(f"  {s.id:14s} {s.start:8.2f} {s.dur:7.2f}  cues: {', '.join(s.cues) or '-'}")
    print("wrote " + ", ".join(p.name for p in written[:3]) + (f" and {len(written) - 3} more" if len(written) > 3 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
