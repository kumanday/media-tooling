from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_tooling.burn_subtitles import (
    BOLD_OVERLAY_FORCE_STYLE,
    NATURAL_SENTENCE_FORCE_STYLE,
    NATURAL_SENTENCE_MAX_WORDS,
    OVERLAY_FILTER_KEYWORDS,
    SUBTITLE_FILTER_KEYWORDS,
    _sentence_case,
    build_video_filter,
    main,
    rechunk_bold_overlay,
    rechunk_natural_sentence,
    validate_subtitles_last,
)
from media_tooling.subtitle import build_srt
from media_tooling.subtitle_translate import (
    HARD_SENTENCE_PUNCTUATION,
    SOFT_SENTENCE_PUNCTUATION,
    SubtitleCue,
    parse_srt_file,
)


class ValidateSubtitlesLastTests(unittest.TestCase):
    def test_clean_filter_string_passes(self) -> None:
        """Non-subtitle, non-overlay filters should pass validation."""
        validate_subtitles_last("scale=1920:1080,fps=30", context="test")

    def test_subtitles_filter_in_extras_raises(self) -> None:
        """A subtitles filter in user-supplied extras violates Hard Rule 1."""
        with self.assertRaises(ValueError) as ctx:
            validate_subtitles_last("subtitles=foo.srt", context="extra-filters")
        self.assertIn("Hard Rule 1", str(ctx.exception))
        self.assertIn("subtitles=", str(ctx.exception))

    def test_ass_filter_in_extras_raises(self) -> None:
        """An ass filter in user-supplied extras violates Hard Rule 1."""
        with self.assertRaises(ValueError) as ctx:
            validate_subtitles_last("ass=foo.ass", context="extra-filters")
        self.assertIn("Hard Rule 1", str(ctx.exception))

    def test_overlay_filter_in_extras_raises(self) -> None:
        """An overlay filter in user-supplied extras violates Hard Rule 1."""
        with self.assertRaises(ValueError) as ctx:
            validate_subtitles_last("overlay=0:0", context="extra-filters")
        self.assertIn("Hard Rule 1", str(ctx.exception))
        self.assertIn("overlay=", str(ctx.exception))

    def test_setpts_filter_in_extras_raises(self) -> None:
        """A setpts filter (overlay PTS shift) in extras violates Hard Rule 1."""
        with self.assertRaises(ValueError) as ctx:
            validate_subtitles_last("setpts=PTS-STARTPTS+T/TB", context="extra-filters")
        self.assertIn("Hard Rule 1", str(ctx.exception))

    def test_empty_filter_string_passes(self) -> None:
        """An empty filter string should pass validation."""
        validate_subtitles_last("", context="test")

    def test_unrelated_filter_passes(self) -> None:
        """Filters unrelated to subtitles or overlays should pass."""
        validate_subtitles_last("eq=brightness=0.1,fps=24", context="test")

    def test_class_filter_not_false_positive_on_ass(self) -> None:
        """'class=' should not trigger 'ass=' false positive."""
        validate_subtitles_last("class=somevalue,fps=24", context="test")

    def test_bass_filter_not_false_positive_on_ass(self) -> None:
        """'bass=' should not trigger 'ass=' false positive."""
        validate_subtitles_last("bass=5,fps=24", context="test")

    def test_overlay_in_word_not_false_positive(self) -> None:
        """'coloroverlay=' should not trigger 'overlay=' false positive."""
        validate_subtitles_last("coloroverlay=5,fps=24", context="test")


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

    def test_strips_trailing_soft_punctuation(self) -> None:
        cues = self._make_cues("Hello, world;")
        result = rechunk_bold_overlay(cues)

        for cue in result:
            for ch in SOFT_SENTENCE_PUNCTUATION:
                if ch not in HARD_SENTENCE_PUNCTUATION:
                    self.assertFalse(cue["text"].endswith(ch))

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

        # Merged text "Hello world this is a test" (6 words) -> single chunk
        self.assertEqual(len(result), 1)
        self.assertIn("Hello", result[0]["text"])
        self.assertIn("test", result[0]["text"])

    def test_gap_creates_new_segment(self) -> None:
        # Large gap between cues should create separate segments
        cues = [
            SubtitleCue(index=1, start=0.0, end=2.0, text="First segment here"),
            SubtitleCue(index=2, start=5.0, end=7.0, text="Second segment here"),
        ]
        result = rechunk_natural_sentence(cues)

        # Two separate segments due to gap; each produces one chunk
        self.assertEqual(len(result), 2)
        self.assertLess(result[0]["end"], result[1]["start"])


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

    def test_pre_filters_with_subtitle_filter_raises(self) -> None:
        """If pre-filters contain a subtitles filter, build_video_filter must raise."""
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "subs.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                build_video_filter(
                    srt_path=srt_path,
                    force_style=BOLD_OVERLAY_FORCE_STYLE,
                    pre_filters="subtitles=other.srt",
                )
            self.assertIn("Hard Rule 1", str(ctx.exception))

    def test_pre_filters_with_overlay_filter_raises(self) -> None:
        """If pre-filters contain an overlay filter, build_video_filter must raise."""
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "subs.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            with self.assertRaises(ValueError) as ctx:
                build_video_filter(
                    srt_path=srt_path,
                    force_style=BOLD_OVERLAY_FORCE_STYLE,
                    pre_filters="overlay=0:0",
                )
            self.assertIn("Hard Rule 1", str(ctx.exception))


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

    def test_comma_in_path_is_escaped(self) -> None:
        """Commas in SRT path must be escaped to avoid breaking the filter chain."""
        with tempfile.TemporaryDirectory() as temp_dir:
            srt_path = Path(temp_dir) / "my,file.srt"
            srt_path.write_text(
                "\n".join(["1", "00:00:00,000 --> 00:00:03,000", "Test", ""]),
                encoding="utf-8",
            )

            vf = build_video_filter(
                srt_path=srt_path,
                force_style=BOLD_OVERLAY_FORCE_STYLE,
                pre_filters=None,
            )

            self.assertIn("\\,", vf)


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


class GuardrailConstantsTests(unittest.TestCase):
    def test_subtitle_filter_keywords_include_subtitles(self) -> None:
        self.assertIn("subtitles=", SUBTITLE_FILTER_KEYWORDS)

    def test_subtitle_filter_keywords_include_ass(self) -> None:
        self.assertIn("ass=", SUBTITLE_FILTER_KEYWORDS)

    def test_overlay_filter_keywords_include_overlay(self) -> None:
        self.assertIn("overlay=", OVERLAY_FILTER_KEYWORDS)

    def test_overlay_filter_keywords_include_setpts(self) -> None:
        self.assertIn("setpts=", OVERLAY_FILTER_KEYWORDS)


class CLIValidationTests(unittest.TestCase):
    def test_overwrite_and_skip_existing_mutually_exclusive(self) -> None:
        """--overwrite and --skip-existing together must be rejected."""
        import sys
        from unittest.mock import patch

        with patch.object(
            sys, "argv", ["media-burn-subtitles", "input.mp4", "--srt", "subs.srt",
                          "-o", "output.mp4", "--overwrite", "--skip-existing"]
        ):
            result = main()
        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
