from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from media_tooling.pack_transcript import (
    extract_words,
    group_into_phrases,
    main,
    render_markdown,
)


class ExtractWordsTests(unittest.TestCase):
    def test_dict_based_segments(self) -> None:
        segments = [
            {
                "start": 0.0,
                "end": 5.0,
                "text": "Hello world",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 1.0},
                    {"word": " world", "start": 1.0, "end": 2.0},
                ],
            },
        ]
        words = extract_words(segments)
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0]["word"], "Hello")
        self.assertAlmostEqual(words[0]["start"], 0.0)
        self.assertAlmostEqual(words[0]["end"], 1.0)
        self.assertIsNone(words[0]["speaker"])

    def test_object_based_segments(self) -> None:
        class Word:
            def __init__(self, word: str, start: float, end: float) -> None:
                self.word = word
                self.start = start
                self.end = end

        class Segment:
            def __init__(self, words: list[Word]) -> None:
                self.words = words
                self.start = 0.0
                self.end = 2.0
                self.text = "Hello world"

        segments = [Segment([Word("Hello", 0.0, 1.0), Word(" world", 1.0, 2.0)])]
        words = extract_words(segments)
        self.assertEqual(len(words), 2)
        self.assertEqual(words[0]["word"], "Hello")

    def test_skips_words_without_timestamps(self) -> None:
        segments = [
            {
                "start": 0.0,
                "end": 5.0,
                "text": "Hello",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 1.0},
                    {"word": "unknown"},
                ],
            },
        ]
        words = extract_words(segments)
        self.assertEqual(len(words), 1)

    def test_preserves_speaker_field(self) -> None:
        segments = [
            {
                "start": 0.0,
                "end": 5.0,
                "text": "Hello",
                "words": [
                    {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "spk_1"},
                ],
            },
        ]
        words = extract_words(segments)
        self.assertEqual(words[0]["speaker"], "spk_1")

    def test_empty_segments(self) -> None:
        words = extract_words([])
        self.assertEqual(words, [])


class GroupIntoPhrasesTests(unittest.TestCase):
    def test_basic_grouping(self) -> None:
        words = [
            {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": None},
            {"word": "world", "start": 1.2, "end": 2.0, "speaker": None},
            {"word": "this", "start": 2.2, "end": 3.0, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        # All gaps < 0.5s, so one phrase
        self.assertEqual(len(phrases), 1)
        self.assertEqual(phrases[0]["text"], "Hello world this")

    def test_silence_breaks_phrases(self) -> None:
        words = [
            {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": None},
            {"word": "world", "start": 1.2, "end": 2.0, "speaker": None},
            # gap >= 0.5s
            {"word": "Goodbye", "start": 2.7, "end": 3.5, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 2)
        self.assertIn("Hello world", phrases[0]["text"])
        self.assertIn("Goodbye", phrases[1]["text"])

    def test_speaker_change_breaks_phrases(self) -> None:
        words = [
            {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "A"},
            {"word": "there", "start": 1.1, "end": 2.0, "speaker": "A"},
            {"word": "Hi", "start": 2.1, "end": 3.0, "speaker": "B"},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 2)
        self.assertIn("Hello there", phrases[0]["text"])
        self.assertIn("Hi", phrases[1]["text"])

    def test_empty_input(self) -> None:
        phrases = group_into_phrases([], silence_threshold=0.5)
        self.assertEqual(phrases, [])

    def test_single_word_phrase(self) -> None:
        words = [
            {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 1)
        self.assertEqual(phrases[0]["text"], "Hello")
        self.assertAlmostEqual(phrases[0]["start"], 0.0)
        self.assertAlmostEqual(phrases[0]["end"], 1.0)

    def test_timestamps_span_full_phrase(self) -> None:
        words = [
            {"word": "Hello", "start": 1.5, "end": 2.0, "speaker": None},
            {"word": "world", "start": 2.1, "end": 3.0, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 1)
        self.assertAlmostEqual(phrases[0]["start"], 1.5)
        self.assertAlmostEqual(phrases[0]["end"], 3.0)

    def test_multiple_silence_gaps(self) -> None:
        words = [
            {"word": "One", "start": 0.0, "end": 1.0, "speaker": None},
            # gap 0.6s
            {"word": "Two", "start": 1.6, "end": 2.5, "speaker": None},
            # gap 0.8s
            {"word": "Three", "start": 3.3, "end": 4.0, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 3)

    def test_silence_threshold_boundary(self) -> None:
        words = [
            {"word": "One", "start": 0.0, "end": 1.0, "speaker": None},
            # gap exactly 0.5s
            {"word": "Two", "start": 1.5, "end": 2.0, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 2)

    def test_speaker_none_does_not_break(self) -> None:
        words = [
            {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": None},
            {"word": "world", "start": 1.1, "end": 2.0, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        self.assertEqual(len(phrases), 1)

    def test_mixed_speaker_and_none(self) -> None:
        words = [
            {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": "A"},
            {"word": "world", "start": 1.1, "end": 2.0, "speaker": None},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        # None speaker should not trigger a break with "A"
        self.assertEqual(len(phrases), 1)

    def test_speaker_change_after_none_preserves_break(self) -> None:
        words = [
            {"word": "Hello", "start": 0.0, "end": 1.0, "speaker": None},
            {"word": "there", "start": 1.1, "end": 2.0, "speaker": "A"},
            {"word": "Hi", "start": 2.1, "end": 3.0, "speaker": "B"},
        ]
        phrases = group_into_phrases(words, silence_threshold=0.5)
        # A and B are different known speakers → must break
        self.assertGreaterEqual(len(phrases), 2)


class RenderMarkdownTests(unittest.TestCase):
    def test_render_with_phrases(self) -> None:
        phrases = [
            {"start": 0.0, "end": 1.5, "text": "Hello world", "speaker": None},
        ]
        md = render_markdown(phrases, silence_threshold=0.5)
        self.assertIn("[0.000-1.500] Hello world", md)
        self.assertIn("silences ≥ 0.5s", md)

    def test_render_empty(self) -> None:
        md = render_markdown([], silence_threshold=0.5)
        self.assertIn("no speech detected", md)

    def test_speaker_tag_in_output(self) -> None:
        phrases = [
            {"start": 0.0, "end": 1.5, "text": "Hello", "speaker": "speaker_0"},
        ]
        md = render_markdown(phrases, silence_threshold=0.5)
        self.assertIn("S0", md)
        self.assertIn("[0.000-1.500] S0 Hello", md)

    def test_timestamp_format_three_decimal_places(self) -> None:
        phrases = [
            {"start": 1.123456, "end": 5.6789, "text": "Test", "speaker": None},
        ]
        md = render_markdown(phrases, silence_threshold=0.5)
        self.assertIn("[1.123-5.679]", md)


class MainEndToEndTests(unittest.TestCase):
    def _make_json(self, payload: dict) -> Path:
        tmpdir = Path(tempfile.mkdtemp())
        json_path = tmpdir / "transcript.json"
        json_path.write_text(json.dumps(payload), encoding="utf-8")
        return json_path

    def test_produces_markdown(self) -> None:
        json_path = self._make_json(
            {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 5.0,
                        "text": "Hello world",
                        "words": [
                            {"word": "Hello", "start": 0.0, "end": 1.0},
                            {"word": " world", "start": 1.1, "end": 2.0},
                        ],
                    },
                ],
            }
        )
        out_path = json_path.parent / "takes_packed.md"
        rc = main([str(json_path), "-o", str(out_path)])
        self.assertEqual(rc, 0)
        content = out_path.read_text(encoding="utf-8")
        self.assertIn("Hello world", content)
        self.assertIn("[0.000-", content)

    def test_missing_input_file(self) -> None:
        rc = main(["/nonexistent/transcript.json"])
        self.assertEqual(rc, 1)

    def test_default_output_path(self) -> None:
        json_path = self._make_json(
            {
                "segments": [
                    {
                        "start": 0.0,
                        "end": 2.0,
                        "text": "Hi",
                        "words": [{"word": "Hi", "start": 0.0, "end": 2.0}],
                    },
                ],
            }
        )
        rc = main([str(json_path)])
        self.assertEqual(rc, 0)
        default_out = json_path.with_name("takes_packed.md")
        self.assertTrue(default_out.exists())

    def test_empty_transcript(self) -> None:
        json_path = self._make_json({"segments": []})
        out_path = json_path.parent / "empty.md"
        rc = main([str(json_path), "-o", str(out_path)])
        self.assertEqual(rc, 0)
        content = out_path.read_text(encoding="utf-8")
        self.assertIn("no speech detected", content)

    def test_size_order_of_magnitude(self) -> None:
        """A 1-hour transcript (~3600s) should produce output on the order of ~12KB."""
        import random

        random.seed(42)
        # Simulate ~150 words/minute for 60 minutes = 9000 words
        # Add realistic pauses: every ~8-12 words, insert a gap ≥0.5s
        words_list: list[dict] = []
        t = 0.0
        words_in_phrase = 0
        phrase_length = random.randint(8, 12)
        for i in range(9000):
            dur = random.uniform(0.15, 0.4)
            words_list.append(
                {"word": f"word{i}", "start": round(t, 3), "end": round(t + dur, 3)},
            )
            words_in_phrase += 1
            if words_in_phrase >= phrase_length:
                # Sentence/topic break: longer pause
                t += dur + random.uniform(0.5, 1.5)
                words_in_phrase = 0
                phrase_length = random.randint(8, 12)
            else:
                t += dur + random.uniform(0.05, 0.25)

        json_path = self._make_json(
            {
                "segments": [
                    {
                        "start": 0.0,
                        "end": t,
                        "text": "simulated",
                        "words": words_list,
                    },
                ],
            }
        )
        out_path = json_path.parent / "size_test.md"
        rc = main([str(json_path), "-o", str(out_path)])
        self.assertEqual(rc, 0)
        size_kb = out_path.stat().st_size / 1024
        # Should be in the ballpark of 12KB (order of magnitude: between 5KB and 100KB)
        self.assertLess(size_kb, 100, f"Output too large: {size_kb:.1f}KB")
        self.assertGreater(size_kb, 3, f"Output surprisingly small: {size_kb:.1f}KB")


if __name__ == "__main__":
    unittest.main()
