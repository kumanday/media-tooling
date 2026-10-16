"""Per-frame ElevenLabs narration for HyperFrames workflows.

Reads the HyperFrames ``SCRIPT.md`` shape (one ``## ... (Frame N)`` section per
spoken line, the spoken text in an indented block) and writes:

- ``<voice-dir>/NN.mp3``: one clip per frame;
- ``audio_meta.json``: the frame-keyed shape HyperFrames workflows consume
  (``faceless-explainer``, ``product-launch-video`` and others): ``voices[]``
  with ``frame``, ``path``, ``duration_s``, ``source: "host"`` and frame-relative
  ``words[]`` (``id``, ``text``, ``start``, ``end``). Existing ``bgm``,
  ``bgm_pending`` and ``sfx`` entries are preserved.

Word timings come from ElevenLabs ``/with-timestamps`` character alignment, so no
separate transcription pass is needed. Neighbouring lines are sent as
``previous_text``/``next_text`` so delivery stays continuous across clips.

Markup in the spoken text:

- lowercase audio tags such as ``[thoughtful]`` are sent to the voice and kept
  out of ``words[]`` (and therefore out of captions);
- ``[Display|spoken]`` makes the voice say ``spoken`` while ``words[]`` shows
  ``Display``; a map (``--pronunciations map.json``, ``{"Rust": "rast"}``) does
  the same for every occurrence of a word;
- ``{@name}`` marks a cue: it is not spoken, and the voice entry gets
  ``cues[]`` with ``name``, ``t`` (frame-relative start of the next word) and
  ``following`` (the next few words), so frame builders can time reveals to the
  narration. Cues are computed from the cached alignment, so moving a cue does
  not re-voice the line.

Clips are cached by a hash of their spoken text and voice settings; re-running
only re-voices lines that changed. Afterwards run the workflow's duration sync
(for example ``node <skill>/scripts/audio.mjs sync-durations``).
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from media_tooling import tts

FRAME_HEADING = re.compile(r"^#{2,3}\s+.*?\(frame\s+(\d+)\)", re.IGNORECASE)
INDENTED = re.compile(r"^(?: {4,}|\t)(.+)$")
AUDIO_TAG = re.compile(r"\[([a-z][a-z ]{1,30})\]")
INLINE_SAY = re.compile(r"\[([^\]|]+)\|([^\]]+)\]")
CUE = re.compile(r"\{@([\w-]+)\}")
CACHE_NAME = ".media-tts-frames.json"


@dataclass
class Line:
    frame: int
    text: str


@dataclass
class Prepared:
    frame: int
    spoken: str
    # character ranges of `spoken` and the text to show for them ("" hides an audio tag)
    displays: list[tuple[int, int, str]] = field(default_factory=list)
    # cue name and the offset in `spoken` where it falls
    cues: list[tuple[str, int]] = field(default_factory=list)


def parse_script(markdown: str) -> list[Line]:
    """HyperFrames SCRIPT.md -> spoken lines keyed by frame (same rules as the upstream audio adapter)."""
    out: list[Line] = []
    cur: Line | None = None
    for raw in markdown.splitlines():
        heading = FRAME_HEADING.match(raw)
        if heading:
            if cur and cur.text.strip():
                out.append(Line(cur.frame, cur.text.strip()))
            cur = Line(int(heading.group(1)), "")
            continue
        if cur is None or re.match(r"^\s*\*\*", raw):
            continue
        indented = INDENTED.match(raw)
        if indented:
            cur.text += (" " if cur.text else "") + indented.group(1).strip()
    if cur and cur.text.strip():
        out.append(Line(cur.frame, cur.text.strip()))
    return out


def prepare(line: Line, pronunciations: dict[str, str]) -> Prepared:
    """Apply pronunciations, locate audio tags and cues; returns the spoken text, display overrides and cues."""
    text = re.sub(r"\s+", " ", line.text).strip()
    cues: list[tuple[str, int]] = []
    tokens: list[tuple[re.Pattern[str], str | None]] = [(AUDIO_TAG, None)]
    for written, spoken_form in sorted(pronunciations.items(), key=lambda kv: -len(kv[0])):
        tokens.append((re.compile(rf"(?<![\w-]){re.escape(written)}(?![\w-])"), spoken_form))
    spoken, i = "", 0
    displays: list[tuple[int, int, str]] = []
    while i < len(text):
        cue = CUE.match(text, i)
        if cue:
            i = cue.end()
            if (not spoken or spoken.endswith(" ")) and text[i:i + 1] == " ":
                i += 1  # "word {@cue} word" speaks as "word word"
            cues.append((cue.group(1), len(spoken)))
            continue
        say = INLINE_SAY.match(text, i)
        if say:
            start = len(spoken)
            spoken += say.group(2)
            displays.append((start, len(spoken), say.group(1)))
            i = say.end()
            continue
        best: tuple[re.Match[str], str | None] | None = None
        for pattern, replacement in tokens:
            m = pattern.match(text, i)
            if m and (best is None or len(m.group(0)) > len(best[0].group(0))):
                best = (m, replacement)
        if best is None:
            spoken += text[i]
            i += 1
            continue
        m, said = best
        start = len(spoken)
        if said is None:  # audio tag: spoken as-is, never shown
            spoken += m.group(0)
            displays.append((start, len(spoken), ""))
        else:
            spoken += said
            displays.append((start, len(spoken), m.group(0)))
        i = m.end()
    return Prepared(line.frame, spoken.rstrip(), displays, cues)


def cues_from_starts(prepared: Prepared, char_starts: list[float]) -> list[dict[str, Any]]:
    """Cue offsets -> frame-relative times (start of the next spoken character) and the words that follow."""
    out: list[dict[str, Any]] = []
    spoken = prepared.spoken
    for name, at in prepared.cues:
        k = at
        while k < len(spoken) and spoken[k] == " ":
            k += 1
        t = float(char_starts[min(k, len(char_starts) - 1)]) if char_starts else 0.0
        following = " ".join(AUDIO_TAG.sub("", spoken[k:]).split()[:6])
        out.append({"name": name, "t": round(t, 3), "following": following})
    return out


def words_from_alignment(prepared: Prepared, alignment: dict[str, Any], frame: int) -> list[dict[str, Any]]:
    """Character alignment -> frame-relative words, with display overrides applied and audio tags removed."""
    spoken = prepared.spoken
    starts = alignment.get("character_start_times_seconds") or []
    ends = alignment.get("character_end_times_seconds") or []
    if not starts or not ends:
        return []

    def at(seq: list[float], k: int) -> float:
        return float(seq[min(k, len(seq) - 1)])

    toks = [(m.start(), m.end()) for m in re.finditer(r"\S+", spoken)]
    words: list[dict[str, Any]] = []
    k = 0
    while k < len(toks):
        s, e = toks[k]
        override = next((d for d in prepared.displays if s < d[1] and e > d[0]), None)
        if override is None:
            text, last = spoken[s:e], k
        else:
            last = k
            while last + 1 < len(toks) and toks[last + 1][0] < override[1]:
                last += 1
            text = spoken[s:override[0]] + override[2] + spoken[override[1]:toks[last][1]]
        text = text.strip()
        if text:
            words.append({"id": f"w{frame:02d}-{len(words):03d}", "text": text,
                          "start": round(at(starts, s), 3), "end": round(at(ends, toks[last][1] - 1), 3)})
        k = last + 1
    return words


def audio_duration(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def synthesize_with_timestamps(*, text: str, voice_id: str, model_id: str, language: str | None, previous: str | None,
                               following: str | None, settings: dict[str, Any], output_format: str) -> dict[str, Any]:
    api_key = tts.resolve_api_key()
    requests = tts._requests_module
    assert requests is not None  # guarded by resolve_api_key
    payload: dict[str, Any] = {"text": text, "model_id": model_id, "voice_settings": settings}
    if language:
        payload["language_code"] = language
    if previous:
        payload["previous_text"] = previous
    if following:
        payload["next_text"] = following
    url = f"{tts.ELEVENLABS_TTS_URL}/{voice_id}/with-timestamps"
    last_error = ""
    for attempt in range(1, 5):
        try:
            response = requests.post(url, params={"output_format": output_format},
                                     headers={"Content-Type": "application/json", "xi-api-key": api_key}, json=payload, timeout=180)
        except requests.exceptions.RequestException:
            raise RuntimeError("Could not reach ElevenLabs. Check your connection and retry.") from None
        if response.ok:
            body = response.json()
            if not body.get("audio_base64"):
                raise RuntimeError("ElevenLabs returned no audio.")
            return dict(body)
        last_error = f"HTTP {response.status_code}"
        if response.status_code not in tts.RETRYABLE_STATUS_CODES:
            break
        if attempt < 4:
            time.sleep(0.75 * attempt)
    raise RuntimeError(f"ElevenLabs generation failed after {attempt} attempts. {last_error}")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Per-frame ElevenLabs narration and audio_meta.json for HyperFrames workflows.")
    p.add_argument("script", help="HyperFrames SCRIPT.md (## ... (Frame N) sections, spoken text indented)")
    p.add_argument("--hyperframes", default=".", help="composition root; paths in audio_meta.json are relative to it")
    p.add_argument("--out", default=None, help="audio_meta.json path (default <hyperframes>/audio_meta.json)")
    p.add_argument("--voice-dir", default="assets/voice", help="clip directory, relative to --hyperframes")
    p.add_argument("--voice-id", default=None, help="ElevenLabs voice ID (falls back to ELEVENLABS_VOICE_ID_EN, then ELEVENLABS_VOICE_ID)")
    p.add_argument("--model", default=os.environ.get("ELEVENLABS_MODEL_ID", tts.DEFAULT_MODEL), help=f"default {tts.DEFAULT_MODEL}")
    p.add_argument("--language", default=None, help="ISO language code sent to ElevenLabs, e.g. es")
    p.add_argument("--pronunciations", default=None, help='JSON map of written form -> spoken form, e.g. {"Rust": "rast"}')
    p.add_argument("--tail", type=float, default=0.6, help="hold after each clip, added to duration_s (s)")
    p.add_argument("--last-tail", type=float, default=1.6, help="hold after the final clip (s)")
    p.add_argument("--stability", type=float, default=0.5)
    p.add_argument("--similarity-boost", type=float, default=0.8)
    p.add_argument("--style", type=float, default=0.15)
    p.add_argument("--speed", type=float, default=1.0, help="ignored by eleven_v4; pace with the script instead")
    p.add_argument("--no-speaker-boost", action="store_true")
    p.add_argument("--output-format", default=tts.DEFAULT_OUTPUT_FORMAT)
    p.add_argument("--only", default=None, help="comma-separated frame numbers to (re)voice; others keep their cache")
    p.add_argument("--force", action="store_true", help="re-voice even when the cache matches")
    p.add_argument("--dry-run", action="store_true", help="parse and report what would be voiced; no API calls, no writes")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    a = parse_args(argv)
    root = Path(a.hyperframes).expanduser().resolve()
    out = Path(a.out).expanduser().resolve() if a.out else root / "audio_meta.json"
    voice_dir = root / a.voice_dir
    try:
        lines = parse_script(Path(a.script).expanduser().read_text(encoding="utf-8"))
        if not lines:
            raise ValueError(f"No '## ... (Frame N)' lines with indented spoken text in {a.script}")
        frames = [ln.frame for ln in lines]
        if len(set(frames)) != len(frames):
            raise ValueError("Each frame may have only one spoken line in SCRIPT.md")
        pron = json.loads(Path(a.pronunciations).read_text(encoding="utf-8")) if a.pronunciations else {}
        prepared = [prepare(ln, pron) for ln in lines]
        only = {int(x) for x in a.only.split(",")} if a.only else None
        if a.model.startswith("eleven_v4") and a.speed != 1.0:
            print(f"warning: {a.model} ignores --speed {a.speed}", file=sys.stderr)
        voice_id = None if a.dry_run else tts.resolve_voice_id(a.voice_id)
        settings = {"stability": a.stability, "similarity_boost": a.similarity_boost, "style": a.style,
                    "speed": a.speed, "use_speaker_boost": not a.no_speaker_boost}
        cache_path = voice_dir / CACHE_NAME
        cache: dict[str, Any] = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        voices: list[dict[str, Any]] = []
        for i, p in enumerate(prepared):
            key = hashlib.sha256(json.dumps([p.spoken, voice_id, a.model, a.language, settings], sort_keys=True).encode()).hexdigest()[:16]
            clip = voice_dir / f"{p.frame:02d}.mp3"
            rec = cache.get(str(p.frame))
            wanted = only is None or p.frame in only
            fresh = rec and rec.get("hash") == key and clip.exists() and not a.force
            if a.dry_run:
                print(f"frame {p.frame:02d}: {'cached' if fresh else 'would voice'} ({len(p.spoken)} chars) {p.spoken[:70]!r}")
                continue
            if not fresh and wanted:
                body = synthesize_with_timestamps(text=p.spoken, voice_id=voice_id or "", model_id=a.model, language=a.language,
                                                  previous=prepared[i - 1].spoken if i else None,
                                                  following=prepared[i + 1].spoken if i + 1 < len(prepared) else None,
                                                  settings=settings, output_format=a.output_format)
                voice_dir.mkdir(parents=True, exist_ok=True)
                clip.write_bytes(base64.b64decode(body["audio_base64"]))
                alignment = body.get("alignment") or {}
                rec = {"hash": key, "model": a.model, "audio_s": round(audio_duration(clip), 3),
                       "words": words_from_alignment(p, alignment, p.frame),
                       "char_starts": [round(float(x), 3) for x in alignment.get("character_start_times_seconds") or []]}
                cache[str(p.frame)] = rec
                cache_path.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
                print(f"frame {p.frame:02d}: voiced {rec['audio_s']} s with {a.model}")
            elif rec:
                print(f"frame {p.frame:02d}: cached {rec['audio_s']} s ({rec.get('model', 'unknown model')})")
            else:
                print(f"frame {p.frame:02d}: not voiced (excluded by --only)")
                continue
            tail = a.last_tail if i + 1 == len(prepared) else a.tail
            entry: dict[str, Any] = {"frame": p.frame, "path": str(clip.relative_to(root)),
                                     "duration_s": round(rec["audio_s"] + tail, 2), "source": "host", "words": rec["words"]}
            if p.cues:
                if not rec.get("char_starts"):
                    print(f"warning: frame {p.frame:02d} cache predates cues; re-voice it with --only {p.frame} --force",
                          file=sys.stderr)
                entry["cues"] = cues_from_starts(p, rec.get("char_starts") or [])
                for c in entry["cues"]:
                    print(f"  @{c['name']} t={c['t']:.2f}s  {c['following']!r}")
            voices.append(entry)
        if a.dry_run:
            return 0
        meta: dict[str, Any] = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        kept = [v for v in meta.get("voices", []) if v.get("frame") not in {v2["frame"] for v2 in voices}]
        meta = {"bgm": meta.get("bgm"), "bgm_pending": bool(meta.get("bgm_pending", False)),
                "voices": sorted(kept + voices, key=lambda v: v["frame"]), "sfx": meta.get("sfx", [])}
        out.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    total = sum(v["duration_s"] for v in meta["voices"])
    print(f"wrote {out} · {len(meta['voices'])} voices · {total:.2f} s; next: sync the storyboard durations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
