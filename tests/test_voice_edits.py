from __future__ import annotations

import importlib.util
import io
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest import mock

import numpy as np

from media_tooling import tts_frames as tf

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "media-motion-graphics" / "scripts"
FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
VOICE = "voice-test"
TTS_ARGS = f"--voice-id {VOICE}"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


holds = load("insert_holds")
splice = load("splice_takes")
storyboard = load("storyboard_from_source")

SR = holds.SR


def tone(spans: list[tuple[float, float]], total: float) -> np.ndarray:
    """A 440 Hz tone during each (start, end) "word", silence elsewhere."""
    x = np.zeros(int(total * SR), dtype=np.float32)
    for s, e in spans:
        t = np.arange(int(s * SR), int(e * SR))
        x[t] = 0.3 * np.sin(2 * np.pi * 440 * t / SR)
    return x


def word_spans(n: int, start: float = 0.2, length: float = 0.3, gap: float = 0.25) -> list[tuple[float, float]]:
    return [(round(start + i * (length + gap), 3), round(start + i * (length + gap) + length, 3)) for i in range(n)]


def alignment(prepared: Any, spans: list[tuple[float, float]]) -> tuple[list[float], list[float]]:
    """Character start/end times that put the k-th spoken token on spans[k]."""
    starts = [0.0] * len(prepared.spoken)
    ends = [0.0] * len(prepared.spoken)
    toks = list(re.finditer(r"\S+", prepared.spoken))
    assert len(toks) == len(spans), (len(toks), len(spans))
    for m, (s, e) in zip(toks, spans):
        step = (e - s) / (m.end() - m.start())
        for j, k in enumerate(range(m.start(), m.end())):
            starts[k], ends[k] = round(s + j * step, 3), round(s + (j + 1) * step, 3)
        if m.end() < len(prepared.spoken):
            starts[m.end()] = ends[m.end()] = e
    return starts, ends


def script_md(*frames: tuple[int, str]) -> str:
    return "\n".join(f"## Line {n} (Frame {n})\n\n    {text}\n" for n, text in frames)


def write_mp3(x: np.ndarray, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "libmp3lame", "-b:a", "192k", str(path)], input=x.tobytes(), check=True)


def make_root(root: Path, frames: list[tuple[int, str]], *, audio: bool = True) -> dict[str, Any]:
    """A composition root as media-tts-frames leaves it: SCRIPT.md, clips, audio_meta.json and the cache."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "SCRIPT.md").write_text(script_md(*frames), encoding="utf-8")
    a = tf.parse_args(["SCRIPT.md", "--voice-id", VOICE])
    settings = tf.voice_settings(a)
    cache: dict[str, Any] = {}
    voices = []
    for i, (n, text) in enumerate(frames):
        p = tf.prepare(tf.Line(n, text), {})
        spans = word_spans(len(p.spoken.split()))
        starts, ends = alignment(p, spans)
        total = round(spans[-1][1] + 0.4, 3)
        clip = root / "assets" / "voice" / f"{n:02d}.mp3"
        if audio:
            write_mp3(tone(spans, total), clip)
            total = tf.audio_duration(clip)
        al = {"character_start_times_seconds": starts, "character_end_times_seconds": ends}
        words = tf.words_from_alignment(p, al, n)
        cache[str(n)] = {"hash": tf.cache_key(p.spoken, VOICE, a.model, a.language, settings), "model": a.model,
                         "audio_s": round(total, 3), "words": words, "char_starts": starts}
        tail = a.last_tail if i + 1 == len(frames) else a.tail
        entry = {"frame": n, "path": f"assets/voice/{n:02d}.mp3", "duration_s": round(total + tail, 2),
                 "source": "host", "words": json.loads(json.dumps(words))}
        if p.cues:
            entry["cues"] = tf.cues_from_starts(p, starts)
        voices.append(entry)
    (root / "assets" / "voice").mkdir(parents=True, exist_ok=True)
    (root / "assets" / "voice" / tf.CACHE_NAME).write_text(json.dumps(cache), encoding="utf-8")
    meta = {"bgm": None, "bgm_pending": False, "voices": voices, "sfx": []}
    (root / "audio_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def quiet(fn: Any, *args: Any) -> tuple[int, str]:
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = fn(*args)
    return code, out.getvalue() + err.getvalue()


def revoice_is_cache_hit(test: unittest.TestCase, root: Path) -> None:
    """media-tts-frames on the edited root must not call ElevenLabs and must write the same timings back."""
    before = read_json(root / "audio_meta.json")
    with mock.patch.object(tf, "synthesize_with_timestamps", side_effect=AssertionError("re-voiced")):
        code, out = quiet(tf.main, [str(root / "SCRIPT.md"), "--hyperframes", str(root), "--voice-id", VOICE])
    test.assertEqual(code, 0, out)
    after = read_json(root / "audio_meta.json")
    for v0, v1 in zip(before["voices"], after["voices"]):
        test.assertEqual((v0["words"], v0.get("cues"), v0["duration_s"]), (v1["words"], v1.get("cues"), v1["duration_s"]))


class HoldPlanTests(unittest.TestCase):
    WORDS: list[dict[str, Any]] = [{"text": t, "start": s, "end": e} for t, (s, e) in zip(["One,", "two", "one."], word_spans(3))]

    def test_find_word_ignores_case_and_punctuation_and_counts_occurrences(self) -> None:
        self.assertEqual(holds.find_word(self.WORDS, "one"), 0)
        self.assertEqual(holds.find_word(self.WORDS, "ONE#2"), 2)
        self.assertEqual(holds.find_word(self.WORDS, "one", after=0), 2)
        with self.assertRaises(ValueError):
            holds.find_word(self.WORDS, "three")

    def test_cut_lands_in_the_silence_between_words(self) -> None:
        x = tone(word_spans(3), 2.0)
        (at, sec, i), = holds.plan_holds(self.WORDS, [("one", 1.5)], x)
        self.assertEqual((sec, i), (1.5, 0))
        self.assertGreater(at, self.WORDS[0]["end"])
        self.assertLess(at, self.WORDS[1]["start"])

    def test_apply_holds_shifts_everything_after_the_cut(self) -> None:
        voice: dict[str, Any] = {"duration_s": 2.0, "words": [dict(w) for w in self.WORDS], "cues": [{"name": "b", "t": 0.75}]}
        rec: dict[str, Any] = {"audio_s": 1.4, "char_starts": [0.2, 0.75, 1.3]}
        added = holds.apply_holds(voice, rec, [(0.62, 1.5, 0)])
        self.assertEqual(added, 1.5)
        self.assertEqual(voice["words"][0]["end"], 0.5)
        self.assertEqual(voice["words"][1]["start"], 2.25)
        self.assertEqual(voice["cues"][0]["t"], 2.25)
        self.assertEqual(rec["char_starts"], [0.2, 2.25, 2.8])
        self.assertEqual((voice["duration_s"], rec["audio_s"]), (3.5, 2.9))
        self.assertEqual(rec["edits"][-1]["holds"][0]["after_word"], "One,")


class SplicePlanTests(unittest.TestCase):
    def test_remap_char_starts_drops_cut_characters_and_shifts_the_rest(self) -> None:
        old = "Hi there. Well, today."
        cs = [float(i) for i in range(len(old))]
        shift = splice.cut_shifter(9.5, 15.5)  # removes "Well, " (6 s)
        new = "Hi there. Today."
        out = splice.remap_char_starts(old, cs, new, shift)
        self.assertEqual(len(out), len(new))
        self.assertEqual(out[:10], cs[:10])
        self.assertEqual(out[new.index("T")], 10.0)  # the re-capitalised letter takes the kept "t"'s time
        self.assertEqual(out[new.index("oday")], 11.0)

    def test_remap_rejects_a_cache_that_does_not_fit_the_old_text(self) -> None:
        with self.assertRaises(ValueError):
            splice.remap_char_starts("abc", [0.0, 1.0], "ab", lambda t: t)


@unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe required")
class VoiceEditEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "film"
        self.backup = Path(self.tmp.name) / "backup"
        make_root(self.root, [(1, "Hello there. {@reveal}Well, today we ship."), (2, "Thanks for watching.")])

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_insert_holds_lengthens_the_clip_and_keeps_the_cache_coherent(self) -> None:
        cache0 = read_json(self.root / "assets" / "voice" / tf.CACHE_NAME)
        dur0 = tf.audio_duration(self.root / "assets" / "voice" / "01.mp3")
        code, out = quiet(holds.main, ["--root", str(self.root), "--backup", str(self.backup), "1:there:1.0"])
        self.assertEqual(code, 0, out)
        meta = read_json(self.root / "audio_meta.json")
        cache = read_json(self.root / "assets" / "voice" / tf.CACHE_NAME)
        v = meta["voices"][0]
        self.assertAlmostEqual(tf.audio_duration(self.root / "assets" / "voice" / "01.mp3"), dur0 + 1.0, delta=0.06)
        self.assertEqual(cache["1"]["hash"], cache0["1"]["hash"])
        self.assertEqual(v["words"][2]["start"], round(cache0["1"]["words"][2]["start"] + 1.0, 3))
        self.assertEqual(v["cues"][0]["t"], v["words"][2]["start"])
        self.assertTrue((self.backup / "01.mp3").is_file() and (self.backup / "audio_meta.json").is_file())
        revoice_is_cache_hit(self, self.root)

    def test_cut_removes_words_and_rebuilds_hash_words_and_cues(self) -> None:
        old_script = Path(self.tmp.name) / "SCRIPT.before.md"
        shutil.copy(self.root / "SCRIPT.md", old_script)
        (self.root / "SCRIPT.md").write_text(script_md((1, "Hello there. {@reveal}Today we ship."),
                                                       (2, "Thanks for watching.")), encoding="utf-8")
        cache0 = read_json(self.root / "assets" / "voice" / tf.CACHE_NAME)
        code, out = quiet(splice.main, ["--root", str(self.root), "--backup", str(self.backup), "--tts-args", TTS_ARGS,
                                        "cut", "1", "well", "today", "--old-script", str(old_script)])
        self.assertEqual(code, 0, out)
        report = json.loads(out)
        self.assertEqual(report["removed"], ["Well,"])
        v = read_json(self.root / "audio_meta.json")["voices"][0]
        self.assertEqual([w["text"] for w in v["words"]], ["Hello", "there.", "Today", "we", "ship."])
        self.assertEqual([w["id"] for w in v["words"]][-1], "w01-004")
        self.assertEqual(v["cues"][0]["t"], v["words"][2]["start"])
        self.assertLess(v["words"][2]["start"], cache0["1"]["words"][3]["start"])
        self.assertNotEqual(read_json(self.root / "assets" / "voice" / tf.CACHE_NAME)["1"]["hash"], cache0["1"]["hash"])
        revoice_is_cache_hit(self, self.root)

    def test_cut_refuses_when_the_options_do_not_match_the_cached_take(self) -> None:
        old_script = Path(self.tmp.name) / "SCRIPT.before.md"
        shutil.copy(self.root / "SCRIPT.md", old_script)
        meta0 = (self.root / "audio_meta.json").read_text(encoding="utf-8")
        code, out = quiet(splice.main, ["--root", str(self.root), "--backup", str(self.backup),
                                        "--tts-args", "--voice-id other", "cut", "1", "well", "today",
                                        "--old-script", str(old_script)])
        self.assertEqual(code, 1)
        self.assertIn("--tts-args", out)
        self.assertEqual((self.root / "audio_meta.json").read_text(encoding="utf-8"), meta0)
        self.assertFalse(self.backup.exists())

    def test_append_adds_a_scratch_clip_after_the_last_word(self) -> None:
        scratch = Path(self.tmp.name) / "scratch"
        make_root(scratch, [(2, "See you soon.")])
        (self.root / "SCRIPT.md").write_text(script_md((1, "Hello there. {@reveal}Well, today we ship."),
                                                       (2, "Thanks for watching. See you soon.")), encoding="utf-8")
        old = read_json(self.root / "audio_meta.json")["voices"][1]
        code, out = quiet(splice.main, ["--root", str(self.root), "--backup", str(self.backup), "--tts-args", TTS_ARGS,
                                        "append", "2", str(scratch), "--gap", "0.75"])
        self.assertEqual(code, 0, out)
        v = read_json(self.root / "audio_meta.json")["voices"][1]
        self.assertEqual([w["text"] for w in v["words"]], ["Thanks", "for", "watching.", "See", "you", "soon."])
        gap = v["words"][3]["start"] - old["words"][-1]["end"]
        self.assertAlmostEqual(gap, 0.75, delta=0.06)
        clip_s = tf.audio_duration(self.root / "assets" / "voice" / "02.mp3")
        self.assertAlmostEqual(v["duration_s"], round(clip_s + 1.6, 2), delta=0.011)  # last frame: --last-tail
        revoice_is_cache_hit(self, self.root)


class StoryboardTests(unittest.TestCase):
    SOURCE = """# Source

## Scene 01 — Opening

- transition_in: cut
- type: hook
- focal: the title
- roles: title = foreground

### Visual

The title fades in. At @reveal the chart
draws its first bar.

### Narration

Welcome. {@reveal}Here is the [API|A-P-I] chart.

## Scene 02 — Close

- transition_in: crossfade
- type: outro

### Visual

Logo.

### Narration

Thanks.
"""
    STORYBOARD = """---
format: 1920x1080
duration: 10.00s
---

## Video direction

Calm and clear.

## Frame 1 — Old title

- status: animated
- src: compositions/frames/01-opening.html

## Frame 2 — Close

- src: compositions/frames/02-close.html
"""
    META = {"voices": [
        {"frame": 1, "duration_s": 6.5, "words": [{"text": "Welcome.", "start": 0.1, "end": 0.6},
                                                  {"text": "chart.", "start": 3.0, "end": 5.9}],
         "cues": [{"name": "reveal", "t": 1.25, "following": "Here is the A-P-I chart."}]},
        {"frame": 2, "duration_s": 3.0, "words": [{"text": "Thanks.", "start": 0.2, "end": 1.4}]},
    ]}

    def test_rebuild_keeps_the_head_and_writes_timed_frame_blocks(self) -> None:
        text, frames, total = storyboard.rebuild(self.SOURCE, self.STORYBOARD, self.META, status={2: "built"})
        self.assertEqual((frames, total), (2, 9.5))
        self.assertIn("duration: 9.50s\n", text)
        self.assertIn("## Video direction\n\nCalm and clear.", text)
        self.assertIn("## Frame 1 — Opening\n", text)
        self.assertIn("- duration: 6.5s\n- status: animated\n- src: compositions/frames/01-opening.html", text)
        self.assertIn('- voiceover: "Welcome. Here is the API chart."', text)
        self.assertIn("At @reveal [t=1.25s] the chart draws its first bar.", text)
        self.assertIn('- t=1.25s · @reveal · narration: "Here is the A-P-I chart.…"', text)
        self.assertIn("- t=5.90s · narration ends; hold the resolved state until frame end t=6.50s", text)
        self.assertIn("- status: built\n- src: compositions/frames/02-close.html", text)
        self.assertNotIn("Old title", text)

    def test_rebuild_is_stable_and_src_can_be_overridden(self) -> None:
        once, _, _ = storyboard.rebuild(self.SOURCE, self.STORYBOARD, self.META)
        twice, _, _ = storyboard.rebuild(self.SOURCE, once, self.META)
        self.assertEqual(once, twice)
        moved, _, _ = storyboard.rebuild(self.SOURCE, once, self.META, src={2: "compositions/frames/02-end.html"})
        self.assertIn("- src: compositions/frames/02-end.html", moved)

    def test_rebuild_reports_frames_without_src(self) -> None:
        bare = self.STORYBOARD.split("## Frame 2")[0]
        with self.assertRaisesRegex(ValueError, r"\[2\].*--src"):
            storyboard.rebuild(self.SOURCE, bare, self.META)


if __name__ == "__main__":
    unittest.main()
