from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from media_tooling.raea_timing import (
    TimingError,
    from_audio_meta,
    from_narration_timing,
    main,
    write,
)


def audio_meta(root: Path) -> Path:
    (root / "assets" / "voice").mkdir(parents=True)
    for n in (1, 2):
        (root / "assets" / "voice" / f"0{n}.mp3").write_bytes(b"mp3-%d" % n)
    meta = {
        "bgm": None,
        "voices": [
            # out of order on purpose: scenes follow frame numbers
            {"frame": 2, "path": "assets/voice/02.mp3", "duration_s": 3.0, "source": "host",
             "words": [{"id": "w02-000", "text": "Second", "start": 0.1, "end": 0.5}],
             "cues": [{"name": "two", "t": 0.1, "following": "Second"}]},
            {"frame": 1, "path": "assets/voice/01.mp3", "duration_s": 2.5, "source": "host",
             "words": [{"id": "w01-000", "text": "First", "start": 0.2, "end": 0.6},
                       {"id": "w01-001", "text": "line.", "start": 0.7, "end": 1.0}],
             "cues": [{"name": "open", "t": 0.2, "following": "First line."}]},
        ],
    }
    p = root / "audio_meta.json"
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p


def narration_timing(root: Path) -> Path:
    (root / "assets" / "audio").mkdir(parents=True)
    for i in range(2):
        (root / "assets" / "audio" / f"vo-00{i}.wav").write_bytes(b"wav")
    data = {
        "total": 6.0,
        "scenes": [{"id": "hook", "start": 0.0, "end": 2.9, "duration": 2.9},
                   {"id": "close", "start": 2.9, "end": 6.0, "duration": 3.1}],
        "vo": [{"id": "vo000", "src": "assets/audio/vo-000.wav", "start": 0.45, "duration": 2.0},
               {"id": "vo001", "src": "assets/audio/vo-001.wav", "start": 3.35, "duration": 2.0}],
        "words": [{"w": "Hello", "p": 0, "s": 0.5, "e": 0.9}, {"w": "again.", "p": 1, "s": 3.4, "e": 3.8}],
        "captions": [{"start": 0.5, "end": 0.9, "text": "Hello"}, {"start": 3.4, "end": 3.8, "text": "again."}],
    }
    p = root / "timing.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


class AudioMetaTest(unittest.TestCase):
    def test_scenes_laid_end_to_end_with_lead_and_hold(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tl = from_audio_meta(audio_meta(Path(d)), lead=1.5, hold=0.25)
        self.assertEqual([(s.id, s.start, s.dur) for s in tl.scenes], [("f01", 0.0, 4.25), ("f02", 4.25, 3.25)])
        # cues are scene-local and include the lead; words sit on the film clock
        self.assertEqual(tl.scenes[0].cues, {"open": 1.7})
        self.assertEqual(tl.scenes[1].cues, {"two": 0.1})
        self.assertEqual([(w["text"], w["start"]) for w in tl.words], [("First", 1.7), ("line.", 2.2), ("Second", 4.35)])
        self.assertEqual([(v.path.name, v.start) for v in tl.voices], [("01.mp3", 1.5), ("02.mp3", 4.25)])
        self.assertEqual(tl.total, 7.5)

    def test_scene_ids_must_match_scene_count(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            meta = audio_meta(Path(d))
            self.assertEqual([s.id for s in from_audio_meta(meta, scene_ids=["hook", "close"]).scenes], ["hook", "close"])
            with self.assertRaises(TimingError):
                from_audio_meta(meta, scene_ids=["only-one"])


class NarrationTimingTest(unittest.TestCase):
    def test_keeps_windows_words_voices_and_captions(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            tl = from_narration_timing(narration_timing(Path(d)))
        self.assertEqual([(s.id, s.start, s.dur) for s in tl.scenes], [("hook", 0.0, 2.9), ("close", 2.9, 3.1)])
        self.assertEqual(tl.words[1], {"text": "again.", "start": 3.4, "end": 3.8})
        self.assertEqual([(v.scene, v.start) for v in tl.voices], [("hook", 0.45), ("close", 3.35)])
        self.assertEqual(len(tl.captions), 2)


class WriteTest(unittest.TestCase):
    def test_writes_film_and_scene_words_and_copies_voices(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "edit" / "raea" / "slot"
            tl = from_audio_meta(audio_meta(Path(d)), lead=1.5)
            write(tl, root, fps=30)
            self.assertEqual(read(root / "words.json")[0], {"text": "First", "start": 1.7, "end": 2.1})
            self.assertEqual(read(root / "words-f02.json"), [{"text": "Second", "start": 0.1, "end": 0.5}])
            scenes = read(root / "scenes.json")
            self.assertEqual((scenes["fps"], scenes["total"], scenes["frames"]), (30, 7.0, 210))
            # frames are rounded once so scene windows tile the film exactly
            self.assertEqual([(s["from"], s["frames"]) for s in scenes["scenes"]], [(0, 120), (120, 90)])
            self.assertEqual(scenes["voices"], [{"src": "voice/01.mp3", "start": 1.5, "scene": "f01"},
                                                {"src": "voice/02.mp3", "start": 4.0, "scene": "f02"}])
            self.assertEqual((root / "media" / "voice" / "02.mp3").read_bytes(), b"mp3-2")
            self.assertNotIn("captions", scenes)

    def test_voice_already_in_media_is_not_copied(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "media" / "vo").mkdir(parents=True)
            (root / "media" / "vo" / "a.wav").write_bytes(b"x")
            data = {"scenes": [{"id": "s", "start": 0, "duration": 2}], "vo": [{"src": "media/vo/a.wav", "start": 0.2}],
                    "words": [{"w": "hi", "s": 0.3, "e": 0.5}]}
            (root / "timing.json").write_text(json.dumps(data), encoding="utf-8")
            write(from_narration_timing(root / "timing.json"), root, copy=False)
            self.assertEqual(read(root / "scenes.json")["voices"][0]["src"], "vo/a.wav")
            self.assertFalse((root / "media" / "voice").exists())

    def test_no_copy_refuses_voice_outside_media(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(TimingError):
                write(from_audio_meta(audio_meta(Path(d))), Path(d) / "raea", copy=False)

    def test_no_words_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "timing.json").write_text(json.dumps({"scenes": [{"id": "s", "start": 0, "duration": 1}]}), encoding="utf-8")
            with self.assertRaises(TimingError):
                write(from_narration_timing(root / "timing.json"), root)


class MainTest(unittest.TestCase):
    def test_cli_round_trip_and_error_exit(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            meta = audio_meta(Path(d))
            root = Path(d) / "raea"
            self.assertEqual(main(["--audio-meta", str(meta), "--root", str(root), "--lead", "1", "--scene-ids", "a,b"]), 0)
            self.assertTrue((root / "words-a.json").is_file())
            self.assertEqual(main(["--timing", str(Path(d) / "missing.json"), "--root", str(root)]), 1)


if __name__ == "__main__":
    unittest.main()
