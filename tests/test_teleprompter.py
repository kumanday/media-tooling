from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from media_tooling.teleprompter import (
    TimedWord,
    align,
    build_data,
    load_timed_words,
    main,
    number_units,
    parse_script,
    render_page,
)


def texts(tokens: str, language: str | None = "en", **kw: Any) -> list[str]:
    return [u.text for u in number_units(tokens.split(), language, **kw)]


def timed(text: str, start: float = 0.0, step: float = 0.5) -> list[TimedWord]:
    return [TimedWord(w, round(start + i * step, 3), round(start + i * step + step * 0.8, 3)) for i, w in enumerate(text.split())]


def page_data(page: str) -> dict[str, Any]:
    match = re.search(r"const DATA = (\{.*?\});\n", page, re.S)
    assert match is not None
    data: dict[str, Any] = json.loads(match.group(1))
    return data


class EnglishNumeralTest(unittest.TestCase):
    def test_spoken_numbers_become_digits(self) -> None:
        self.assertEqual(texts("six hundred seats"), ["600", "seats"])
        self.assertEqual(texts("and twenty-two hundred for"), ["and", "2,200", "for"])
        self.assertEqual(texts("two hundred twenty-six users"), ["226", "users"])
        self.assertEqual(texts("around a hundred and eighty-four hours."), ["around", "184", "hours."])
        self.assertEqual(texts("of a hundred and seventy-five thousand."), ["of", "175,000."])
        self.assertEqual(texts("up to three hundred thousand seats."), ["up", "to", "300,000", "seats."])

    def test_hyphenated_suffix_and_article_stay(self) -> None:
        self.assertEqual(texts("a five-thousand-person pilot"), ["a", "5,000-person", "pilot"])

    def test_half_a_million_stays_in_words(self) -> None:
        self.assertEqual(texts("for half a million more."), ["for", "half", "a", "million", "more."])

    def test_separate_numbers_are_not_merged(self) -> None:
        self.assertEqual(texts("one two three"), ["1", "2", "3"])
        self.assertEqual(texts("thirty years, two sales"), ["30", "years,", "2", "sales"])

    def test_scale_words_alone_and_plurals_stay(self) -> None:
        self.assertEqual(texts("hundreds of thousands"), ["hundreds", "of", "thousands"])
        self.assertEqual(texts("a thousand"), ["1,000"])

    def test_keep_words_and_separator(self) -> None:
        self.assertEqual(texts("one hour", keep=["one hour"]), ["one", "hour"])
        self.assertEqual(texts("two thousand", thousands=""), ["2000"])

    def test_no_language_keeps_every_token(self) -> None:
        self.assertEqual(texts("six hundred seats", None), ["six", "hundred", "seats"])


class SpanishNumeralTest(unittest.TestCase):
    def test_spoken_numbers_become_digits(self) -> None:
        self.assertEqual(texts("hasta trescientos mil cupos.", "es"), ["hasta", "300.000", "cupos."])
        self.assertEqual(texts("doscientos veintiséis usuarios", "es"), ["226", "usuarios"])
        self.assertEqual(texts("treinta y cinco años", "es"), ["35", "años"])
        self.assertEqual(texts("dos mil trescientos", "es"), ["2.300"])
        self.assertEqual(texts("un millón de personas", "es"), ["1.000.000", "de", "personas"])
        self.assertEqual(texts("mil personas", "es"), ["1.000", "personas"])

    def test_articles_and_medio_millon_stay(self) -> None:
        self.assertEqual(texts("una idea y un plan", "es"), ["una", "idea", "y", "un", "plan"])
        self.assertEqual(texts("medio millón más", "es"), ["medio", "millón", "más"])


class ScriptTest(unittest.TestCase):
    def test_headings_are_beats_and_notes_are_not_spoken(self) -> None:
        script = (
            "# Title\n\nIntro that is not spoken.\n\n"
            "### 1 · hello\nHi, I'm **Ada**.\n\n> smile\n\n"
            "### 2 · ask\nWe want `**six hundred**` seats.\n<!-- hidden -->\n"
        )
        tokens, labels = parse_script(script)
        self.assertEqual(labels, ["1 · hello", "2 · ask"])
        self.assertEqual([t.text for t in tokens], ["Hi,", "I'm", "Ada.", "We", "want", "six", "hundred", "seats."])
        self.assertEqual([t.beat for t in tokens], [0, 0, 0, 1, 1, 1, 1, 1])
        self.assertEqual([t.text for t in tokens if t.cue], ["Ada.", "six", "hundred"])

    def test_paragraphs_are_beats_without_headings(self) -> None:
        tokens, labels = parse_script("First line\ncontinues.\n\n- Second *beat*.\n")
        self.assertEqual(labels, ["1", "2"])
        self.assertEqual([(t.text, t.beat) for t in tokens], [("First", 0), ("line", 0), ("continues.", 0), ("Second", 1), ("beat.", 1)])


class LoadTest(unittest.TestCase):
    def _write(self, obj: Any) -> Path:
        tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(obj, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_media_subtitle_transcript(self) -> None:
        path = self._write({"audio_duration": 3.0, "segments": [{"words": [
            {"word": "Hi", "start": 0.1, "end": 0.3}, {"word": " ", "start": 0.3, "end": 0.4, "type": "spacing"},
            {"word": "there", "start": 0.4, "end": 0.8}]}]})
        words, scenes, total = load_timed_words(path)
        self.assertEqual([w.text for w in words], ["Hi", "there"])
        self.assertEqual((scenes, total), ([], 3.0))

    def test_narration_timing_file(self) -> None:
        path = self._write({"total": 9.5, "scenes": [{"id": "a", "start": 0.0}, {"id": "b", "start": 4.0}],
                            "words": [{"w": "One", "p": 0, "s": 0.5, "e": 0.9}, {"w": "Two", "p": 1, "s": 4.5, "e": 4.9}]})
        words, scenes, total = load_timed_words(path)
        self.assertEqual([(w.text, w.group) for w in words], [("One", 0), ("Two", 1)])
        self.assertEqual((scenes, total), ([0.0, 4.0], 9.5))

    def test_audio_meta_frames_play_back_to_back(self) -> None:
        path = self._write({"voices": [
            {"frame": 2, "duration_s": 3.0, "words": [{"text": "second", "start": 0.2, "end": 0.6}]},
            {"frame": 1, "duration_s": 2.5, "words": [{"text": "first", "start": 0.1, "end": 0.4}]}]})
        words, _, total = load_timed_words(path)
        self.assertEqual([(w.text, w.start, w.group) for w in words], [("first", 0.1, 0), ("second", 2.7, 1)])
        self.assertEqual(total, 5.5)

    def test_unknown_shape_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_timed_words(self._write({"foo": 1}))


class AlignTest(unittest.TestCase):
    def test_numbers_match_by_value_and_renamed_words_map_one_to_one(self) -> None:
        tw = timed("we sold 600 seats to Ludvig")
        script = number_units("we sold six hundred seats to Ludwig".split(), "en")
        spans, ratio = align(script, number_units([w.text for w in tw], "en"), tw)
        self.assertEqual([u.text for u in script], ["we", "sold", "600", "seats", "to", "Ludwig"])
        self.assertEqual(spans[2], (tw[2].start, tw[2].end))
        self.assertEqual(spans[5], (tw[5].start, tw[5].end))
        self.assertAlmostEqual(ratio, 5 / 6)

    def test_unmatched_words_share_the_gap(self) -> None:
        tw = timed("one two five")
        units = number_units("alpha beta gamma delta five".split(), None)
        spans, _ = align(units, number_units([w.text for w in tw], None), tw)
        self.assertEqual(len(spans), 5)
        self.assertEqual(spans[4], (tw[2].start, tw[2].end))
        self.assertTrue(all(spans[k][0] <= spans[k + 1][0] for k in range(4)))


class PageTest(unittest.TestCase):
    def test_build_data_with_script_beats_and_cues(self) -> None:
        tw = timed("hi there we sold six hundred seats", step=1.0)
        data = build_data(tw, script="## open\nHi **there**.\n\n## sales\nWe sold six hundred seats.", title="T")
        self.assertEqual([w["w"] for w in data["words"]], ["Hi", "there.", "We", "sold", "600", "seats."])
        self.assertEqual([b["label"] for b in data["beats"]], ["open", "sales"])
        self.assertEqual(data["beats"][1]["start"], round(2.0 - 0.6, 3))
        self.assertEqual([w["c"] for w in data["words"]], [False, True, False, False, False, False])
        self.assertEqual(data["match"], 1.0)
        self.assertGreaterEqual(data["total"], data["words"][-1]["e"])

    def test_without_script_beats_follow_pauses(self) -> None:
        tw = timed("one more") + timed("and again", start=5.0)
        data = build_data(tw, title="T", beat_gap=1.5, language=None)
        self.assertEqual([w["b"] for w in data["words"]], [0, 0, 1, 1])

    def test_page_escapes_title_and_data(self) -> None:
        data = build_data(timed("hello </script> world"), title="<Pitch & Co>")
        page = render_page(data)
        self.assertIn("<title>&lt;Pitch &amp; Co&gt;</title>", page)
        self.assertNotIn("</script> world", page)
        self.assertEqual(page_data(page)["words"][1]["w"], "</script>")


class MainTest(unittest.TestCase):
    def test_writes_page_and_voice(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "words.json").write_text(json.dumps({"segments": [{"words": [
                {"word": "Six", "start": 0.0, "end": 0.3}, {"word": "hundred", "start": 0.3, "end": 0.7},
                {"word": "seats.", "start": 0.7, "end": 1.2}]}]}))
            (root / "take.wav").write_bytes(b"RIFF")
            out = root / "prompter"

            def fake_run(cmd: list[str], **_: Any) -> mock.MagicMock:
                result = mock.MagicMock(returncode=0, stdout="4.0\n", stderr="")
                if cmd[0] == "ffmpeg":
                    Path(cmd[-1]).write_bytes(b"ID3")
                return result

            with mock.patch("media_tooling.teleprompter.subprocess.run", side_effect=fake_run) as run, \
                    mock.patch("media_tooling.teleprompter.shutil.which", return_value="/usr/bin/ffmpeg"), \
                    mock.patch("sys.stdout"):
                code = main([str(root / "words.json"), "--audio", str(root / "take.wav"), "--out", str(out), "--title", "Pitch"])
            self.assertEqual(code, 0)
            self.assertTrue((out / "voice.mp3").is_file())
            self.assertIn("libmp3lame", run.call_args_list[0].args[0])
            data = page_data((out / "index.html").read_text())
            self.assertEqual([w["w"] for w in data["words"]], ["600", "seats."])
            self.assertTrue(data["voice"])
            self.assertEqual(data["total"], 4.0)

    def test_bad_input_returns_error(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "x.json"
            bad.write_text("{}")
            with mock.patch("sys.stderr"):
                self.assertEqual(main([str(bad), "--out", str(Path(d) / "o")]), 1)


if __name__ == "__main__":
    unittest.main()
