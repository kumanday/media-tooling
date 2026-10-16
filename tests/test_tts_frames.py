from __future__ import annotations

import base64
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.tts_frames import (
    Line,
    cues_from_starts,
    main,
    parse_script,
    prepare,
    words_from_alignment,
)

SCRIPT = """# SCRIPT — demo

**Voice:** narrator (ElevenLabs)

## Line 1 — Hook (Frame 1)

**Time:** 0.0 – 3.0s
**Delivery:** calm

    Ship a video
    in an afternoon.

## Line 2 — Close (Frame 2)

    [warm] Built in Rust.
"""


def alignment_for(text: str, step: float = 0.05) -> dict:
    return {"characters": list(text),
            "character_start_times_seconds": [round(i * step, 3) for i in range(len(text))],
            "character_end_times_seconds": [round((i + 1) * step, 3) for i in range(len(text))]}


class TtsFramesTests(unittest.TestCase):
    def test_parse_script_reads_frames_and_indented_text_only(self) -> None:
        lines = parse_script(SCRIPT)
        self.assertEqual([(ln.frame, ln.text) for ln in lines], [(1, "Ship a video in an afternoon."), (2, "[warm] Built in Rust.")])

    def test_audio_tags_are_spoken_but_not_in_words(self) -> None:
        p = prepare(Line(2, "[warm] Built in Rust."), {})
        self.assertEqual(p.spoken, "[warm] Built in Rust.")
        words = words_from_alignment(p, alignment_for(p.spoken), 2)
        self.assertEqual([w["text"] for w in words], ["Built", "in", "Rust."])
        self.assertEqual(words[0]["id"], "w02-000")
        self.assertAlmostEqual(words[0]["start"], 7 * 0.05, places=3)

    def test_multiword_audio_tag_is_removed(self) -> None:
        p = prepare(Line(1, "[slightly wry] It worked."), {})
        self.assertEqual([w["text"] for w in words_from_alignment(p, alignment_for(p.spoken), 1)], ["It", "worked."])

    def test_pronunciation_changes_speech_but_keeps_written_word(self) -> None:
        p = prepare(Line(2, "Built in Rust, then Rusty."), {"Rust": "rast"})
        self.assertEqual(p.spoken, "Built in rast, then Rusty.")
        words = words_from_alignment(p, alignment_for(p.spoken), 2)
        self.assertEqual([w["text"] for w in words], ["Built", "in", "Rust,", "then", "Rusty."])

    def test_inline_pronunciation_shows_display_form(self) -> None:
        p = prepare(Line(1, "Call the [API|A-P-I] now."), {})
        self.assertEqual(p.spoken, "Call the A-P-I now.")
        words = words_from_alignment(p, alignment_for(p.spoken), 1)
        self.assertEqual([w["text"] for w in words], ["Call", "the", "API", "now."])

    def test_cues_are_silent_and_timed_to_the_next_word(self) -> None:
        p = prepare(Line(3, "{@open} [curious] First the graph, {@edge} then the edge. {@end}"), {})
        self.assertEqual(p.spoken, "[curious] First the graph, then the edge.")
        starts = alignment_for(p.spoken)["character_start_times_seconds"]
        cues = {c["name"]: c for c in cues_from_starts(p, starts)}
        self.assertEqual(cues["open"]["t"], 0.0)
        self.assertEqual(cues["open"]["following"], "First the graph, then the edge.")
        self.assertAlmostEqual(cues["edge"]["t"], p.spoken.index("then") * 0.05, places=3)
        self.assertEqual(cues["edge"]["following"], "then the edge.")
        self.assertEqual(cues["end"]["following"], "")
        words = words_from_alignment(p, alignment_for(p.spoken), 3)
        self.assertEqual([w["text"] for w in words], ["First", "the", "graph,", "then", "the", "edge."])

    def test_main_writes_clips_and_audio_meta_and_preserves_other_audio(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            script = root / "SCRIPT.md"
            script.write_text(SCRIPT.replace("Built in", "Built {@lang} in"), encoding="utf-8")
            (root / "audio_meta.json").write_text(json.dumps({"bgm": {"path": "assets/bed.mp3", "source": "host"}, "bgm_pending": False,
                                                              "voices": [], "sfx": [{"frame": 1, "file": "assets/sfx.mp3", "source": "host"}]}))
            calls: list[dict] = []

            def fake_post(url: str, params: dict, headers: dict, json: dict, timeout: int) -> MagicMock:  # noqa: A002 - mirrors requests.post
                calls.append({"url": url, "payload": json})
                r = MagicMock(ok=True)
                r.json.return_value = {"audio_base64": base64.b64encode(b"mp3").decode(), "alignment": alignment_for(json["text"])}
                return r

            requests = MagicMock()
            requests.post.side_effect = fake_post
            env = {"ELEVENLABS_API_KEY": "k", "ELEVENLABS_VOICE_ID_EN": "voice"}
            with patch("media_tooling.tts._requests_module", requests), patch.dict(os.environ, env), \
                    patch("media_tooling.tts_frames.audio_duration", return_value=2.0), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main([str(script), "--hyperframes", d, "--language", "en"]), 0)
                meta = json.loads((root / "audio_meta.json").read_text())
                self.assertEqual(meta["bgm"]["path"], "assets/bed.mp3")
                self.assertEqual(len(meta["sfx"]), 1)
                self.assertEqual([v["frame"] for v in meta["voices"]], [1, 2])
                self.assertEqual(meta["voices"][0]["path"], "assets/voice/01.mp3")
                self.assertEqual(meta["voices"][0]["duration_s"], 2.6)
                self.assertEqual(meta["voices"][1]["duration_s"], 3.6)
                self.assertEqual(meta["voices"][1]["source"], "host")
                self.assertTrue(calls[0]["url"].endswith("/voice/with-timestamps"))
                self.assertEqual(calls[0]["payload"]["model_id"], "eleven_v4")
                self.assertEqual(calls[0]["payload"]["language_code"], "en")
                self.assertEqual(calls[0]["payload"]["next_text"], "[warm] Built in Rust.")
                self.assertEqual(calls[1]["payload"]["previous_text"], "Ship a video in an afternoon.")
                self.assertEqual(meta["voices"][1]["cues"], [{"name": "lang", "t": 0.65, "following": "in Rust."}])
                self.assertNotIn("cues", meta["voices"][0])
                # moving a cue reuses the cached clip and re-times the cue
                script.write_text(SCRIPT.replace("Rust.", "{@lang} Rust."), encoding="utf-8")
                self.assertEqual(main([str(script), "--hyperframes", d, "--language", "en"]), 0)
                self.assertEqual(len(calls), 2)
                meta = json.loads((root / "audio_meta.json").read_text())
                self.assertEqual(meta["voices"][1]["cues"][0]["following"], "Rust.")

    def test_dry_run_makes_no_calls(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "SCRIPT.md"
            script.write_text(SCRIPT, encoding="utf-8")
            requests = MagicMock()
            with patch("media_tooling.tts._requests_module", requests), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main([str(script), "--hyperframes", d, "--dry-run"]), 0)
            requests.post.assert_not_called()
            self.assertFalse((Path(d) / "audio_meta.json").exists())

    def test_script_without_frames_fails(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "SCRIPT.md"
            script.write_text("# nothing here\n", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(main([str(script), "--hyperframes", d, "--dry-run"]), 1)


if __name__ == "__main__":
    unittest.main()
