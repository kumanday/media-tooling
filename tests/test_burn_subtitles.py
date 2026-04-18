from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_tooling.burn_subtitles import (
    BOLD_OVERLAY_FORCE_STYLE,
    NATURAL_SENTENCE_FORCE_STYLE,
    NATURAL_SENTENCE_MAX_WORDS,
    _sentence_case,
    build_video_filter,
    rechunk_bold_overlay,
    rechunk_natural_sentence,
)
from media_tooling.subtitle import build_srt
from media_tooling.subtitle_translate import SubtitleCue, parse_srt_file


class SRTParsingTests(unittest.TestCase):
    def test_parse_srt_file_reads_valid_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "test.srt"
            srt_path.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:00,000 --> 00:00:03,000",
                        "Hello world",
                        "",
                        "2",
                        "00:00:03,000 --> 00:00:06,000",
                        "This is a test",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            cues = parse_srt_file(srt_path)

            self.assertEqual(len(cues), 2)
            self.assertEqual(cues[0].text, "Hello world")
            self.assertAlmostEqual(cues[0].start, 0.0)
            self.assertAlmostEqual(cues[0].end, 3.0)
            self.assertEqual(cues[1].text, "This is a test")

    def test_parse_srt_file_raises_on_invalid_srt(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "bad.srt"
            srt_path.write_text("not valid srt content", encoding="utf-8")

            with self.assertRaises(ValueError):
                parse_srt_file(srt_path)


class BoldOverlayChunkingTests(unittest.TestCase):
    def _make_cues(self, *texts: str) -> list[SubtitleCue]:
        cues = []
        for i, text in enumerate(texts):
            cues.append(
                SubtitleCue(
                    index=i + 1,
                    start=i * 3.0,
                    end=(i + 1) * 3.0,
                    text=text,
                )
            )
        return cues

    def test_two_word_chunks_uppercase(self) -> None:
        cues = self._make_cues("Hello world this is a test")
        result = rechunk_bold_overlay(cues)

        self.assertTrue(len(result) > 1)
        for cue in result:
            words = cue["text"].split()
            self.assertLessEqual(len(words), 2)
            self.assertEqual(cue["text"], cue["text"].upper())

    def test_breaks_on_punctuation(self) -> None:
        cues = self._make_cues("Hello. World test")
        result = rechunk_bold_overlay(cues)

        # "Hello." should be its own chunk (punctuation break)
        # "World test" should be the next 2-word chunk
        self.assertTrue(any("HELLO" in c["text"] for c in result))

    def test_preserves_timing_range(self) -> None:
        cues = self._make_cues("one two three four five six")
        result = rechunk_bold_overlay(cues)

        self.assertAlmostEqual(result[0]["start"], 0.0)
        self.assertAlmostEqual(result[-1]["end"], 3.0)

    def test_single_word_cue(self) -> None:
        cues = self._make_cues("Hello")
        result = rechunk_bold_overlay(cues)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["text"], "HELLO")

    def test_empty_cue_skipped(self) -> None:
        cues = [SubtitleCue(index=1, start=0.0, end=3.0, text="")]
        result = rechunk_bold_overlay(cues)

        self.assertEqual(len(result), 0)

    def test_strips_trailing_comma_semicolon_colon(self) -> None:
        cues = self._make_cues("Hello, world;")
        result = rechunk_bold_overlay(cues)

        for cue in result:
            self.assertFalse(cue["text"].endswith(","))
            self.assertFalse(cue["text"].endswith(";"))
            self.assertFalse(cue["text"].endswith(":"))

    def test_periods_preserved_in_bold_overlay(self) -> None:
        cues = self._make_cues("Hello. World end.")
        result = rechunk_bold_overlay(cues)

        # Period-ending words should keep the period after uppercasing
        self.assertTrue(any(c["text"].endswith(".") for c in result))


class SentenceCaseTests(unittest.TestCase):
    def test_capitalizes_first_letter(self) -> None:
        self.assertEqual(_sentence_case("hello world"), "Hello world")

    def test_preserves_proper_nouns(self) -> None:
        self.assertEqual(_sentence_case("NASA launches rocket"), "NASA launches rocket")

    def test_preserves_acronyms(self) -> None:
        self.assertEqual(_sentence_case("the API response"), "The API response")

    def test_empty_string(self) -> None:
        self.assertEqual(_sentence_case(""), "")

    def test_single_char(self) -> None:
        self.assertEqual(_sentence_case("a"), "A")


class NaturalSentenceChunkingTests(unittest.TestCase):
    def _make_cues(self, *texts: str) -> list[SubtitleCue]:
        cues = []
        for i, text in enumerate(texts):
            cues.append(
                SubtitleCue(
                    index=i + 1,
                    start=i * 3.0,
                    end=(i + 1) * 3.0,
                    text=text,
                )
            )
        return cues

    def test_four_to_seven_word_chunks(self) -> None:
        cues = self._make_cues(
            "One two three four five six seven eight nine ten eleven twelve"
        )
        result = rechunk_natural_sentence(cues)

        for cue in result:
            word_count = len(cue["text"].split())
            # Bounds-check in _group_words_natural_sentence guarantees no chunk exceeds max
            self.assertLessEqual(word_count, NATURAL_SENTENCE_MAX_WORDS)
            self.assertGreaterEqual(word_count, 2)

    def test_sentence_case(self) -> None:
        cues = self._make_cues("Hello world this is a test sentence here")
        result = rechunk_natural_sentence(cues)

        for cue in result:
            self.assertTrue(cue["text"][0].isupper())

    def test_breaks_on_punctuation(self) -> None:
        cues = self._make_cues("First sentence here. Second part now continues on")
        result = rechunk_natural_sentence(cues)

        # Should break at punctuation within 4-7 word range
        self.assertTrue(len(result) > 1)

    def test_preserves_timing_range(self) -> None:
        cues = self._make_cues("One two three four five six seven eight")
        result = rechunk_natural_sentence(cues)

        self.assertAlmostEqual(result[0]["start"], 0.0)
        self.assertAlmostEqual(result[-1]["end"], 3.0)

    def test_short_cue_merged_with_adjacent(self) -> None:
        # Two cues close together should be merged for chunking
        cues = [
            SubtitleCue(index=1, start=0.0, end=1.0, text="Hello"),
            SubtitleCue(index=2, start=1.1, end=2.0, text="world this is a test"),
        ]
        result = rechunk_natural_sentence(cues)

        # Should produce chunks from the merged text
        self.assertTrue(len(result) >= 1)

    def test_gap_creates_new_segment(self) -> None:
        # Large gap between cues should create separate segments
        cues = [
            SubtitleCue(index=1, start=0.0, end=2.0, text="First segment here"),
            SubtitleCue(index=2, start=5.0, end=7.0, text="Second segment here"),
        ]
        result = rechunk_natural_sentence(cues)

        # First segment's last cue end should be before second segment's start
        self.assertTrue(len(result) >= 2)


class FilterChainOrderingTests(unittest.TestCase):
    def test_subtitles_filter_always_last(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "subs.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            vf = build_video_filter(
                srt_path=srt_path,
                force_style=BOLD_OVERLAY_FORCE_STYLE,
                pre_filters="scale=1920:-2",
            )

            # Subtitles filter must come after the pre-filters
            self.assertIn("scale=1920:-2,", vf)
            self.assertTrue(vf.endswith(f"':force_style='{BOLD_OVERLAY_FORCE_STYLE}'"))
            # Verify subtitles is after the comma that separates pre-filters
            comma_idx = vf.index(",")
            self.assertIn("subtitles=", vf[comma_idx:])

    def test_no_pre_filters_subtitles_still_last(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "subs.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            vf = build_video_filter(
                srt_path=srt_path,
                force_style=BOLD_OVERLAY_FORCE_STYLE,
                pre_filters=None,
            )

            self.assertTrue(vf.startswith("subtitles="))

    def test_custom_style_args_passthrough(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "subs.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            custom_style = "FontName=Arial,FontSize=24,PrimaryColour=&H00FFFF00"
            vf = build_video_filter(
                srt_path=srt_path,
                force_style=custom_style,
                pre_filters=None,
            )

            self.assertIn(custom_style, vf)
            self.assertNotIn(BOLD_OVERLAY_FORCE_STYLE, vf)


class BuildSRTTests(unittest.TestCase):
    def test_produces_valid_srt(self) -> None:
        cues = [
            {"start": 0.0, "end": 3.0, "text": "HELLO WORLD"},
            {"start": 3.0, "end": 6.0, "text": "THIS IS"},
        ]
        srt_text = build_srt(cues)

        lines = srt_text.strip().split("\n")
        self.assertEqual(lines[0], "1")
        self.assertIn("-->", lines[1])
        self.assertEqual(lines[2], "HELLO WORLD")

    def test_empty_cues_produce_empty_srt(self) -> None:
        srt_text = build_srt([])
        self.assertEqual(srt_text.strip(), "")


class PathEscapingTests(unittest.TestCase):
    def test_escapes_special_characters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "video [1].srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            vf = build_video_filter(
                srt_path=srt_path,
                force_style=BOLD_OVERLAY_FORCE_STYLE,
                pre_filters=None,
            )

            self.assertIn("\\[", vf)
            self.assertIn("\\]", vf)

    def test_escapes_percent_sign(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "100%.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            vf = build_video_filter(
                srt_path=srt_path,
                force_style=BOLD_OVERLAY_FORCE_STYLE,
                pre_filters=None,
            )

            self.assertIn("\\%", vf)

    def test_escapes_single_quotes_in_force_style(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "subs.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            custom_style = "FontName=O'Brien,FontSize=24"
            vf = build_video_filter(
                srt_path=srt_path,
                force_style=custom_style,
                pre_filters=None,
            )

            self.assertIn("O\\'Brien", vf)


class StyleConstantsTests(unittest.TestCase):
    def test_bold_overlay_has_required_properties(self) -> None:
        self.assertIn("FontSize=18", BOLD_OVERLAY_FORCE_STYLE)
        self.assertIn("Bold=1", BOLD_OVERLAY_FORCE_STYLE)
        self.assertIn("MarginV=35", BOLD_OVERLAY_FORCE_STYLE)
        self.assertIn("Outline=2", BOLD_OVERLAY_FORCE_STYLE)
        self.assertIn("Alignment=2", BOLD_OVERLAY_FORCE_STYLE)

    def test_natural_sentence_has_larger_font(self) -> None:
        self.assertIn("FontSize=22", NATURAL_SENTENCE_FORCE_STYLE)
        self.assertIn("Bold=1", NATURAL_SENTENCE_FORCE_STYLE)
        self.assertIn("MarginV=35", NATURAL_SENTENCE_FORCE_STYLE)


if __name__ == "__main__":
    unittest.main()