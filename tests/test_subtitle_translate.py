from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from media_tooling.subtitle_translate import (
    build_translated_segments,
    build_translation_template_payload,
    build_translation_windows,
    parse_srt_file,
    resegment_translated_window,
)


class SubtitleTranslationTests(unittest.TestCase):
    def test_build_translation_windows_merges_source_cues_into_sentence_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_srt = Path(temp_dir) / "source.srt"
            source_srt.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:00,000 --> 00:00:03,000",
                        "Planning happens in one",
                        "",
                        "2",
                        "00:00:03,000 --> 00:00:06,000",
                        "place, execution in another.",
                        "",
                        "3",
                        "00:00:06,000 --> 00:00:09,000",
                        "Review happens later.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            cues = parse_srt_file(source_srt)
            windows = build_translation_windows(cues)

            self.assertEqual(len(windows), 2)
            self.assertEqual(windows[0].source_cue_indices, [1, 2])
            self.assertEqual(
                windows[0].source_text,
                "Planning happens in one place, execution in another.",
            )

    def test_build_translated_segments_does_not_inherit_source_cue_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_srt = Path(temp_dir) / "source.srt"
            source_srt.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:00,000 --> 00:00:03,000",
                        "Planning happens in one",
                        "",
                        "2",
                        "00:00:03,000 --> 00:00:06,000",
                        "place, execution in another.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            cues = parse_srt_file(source_srt)
            windows = build_translation_windows(cues)
            payload = build_translation_template_payload(
                source_srt=source_srt,
                source_language="English",
                target_language="Spanish",
                windows=windows,
            )
            payload["windows"][0]["translated_text"] = (
                "La planificacion ocurre en un lugar y la ejecucion en otro."
            )

            segments = build_translated_segments(
                source_srt=source_srt,
                source_language="English",
                target_language="Spanish",
                expected_windows=windows,
                payload=payload,
            )

            self.assertEqual(len(segments), 1)
            self.assertEqual(segments[0]["start"], 0.0)
            self.assertEqual(segments[0]["end"], 6.0)
            self.assertEqual(
                segments[0]["text"],
                "La planificacion ocurre en un lugar y la ejecucion en otro.",
            )

    def test_resegment_translated_window_splits_unspaced_text(self) -> None:
        segments = resegment_translated_window(
            start=0.0,
            end=8.0,
            translated_text="规划发生在一个地方执行发生在另一个地方审查则在之后进行这样工作流才是连贯的",
        )

        self.assertGreater(len(segments), 1)
        self.assertEqual(segments[0]["start"], 0.0)
        self.assertEqual(segments[-1]["end"], 8.0)
        self.assertTrue(all(segment["text"] for segment in segments))

    def test_build_translated_segments_rejects_mismatched_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_srt = Path(temp_dir) / "source.srt"
            source_srt.write_text(
                "\n".join(
                    [
                        "1",
                        "00:00:00,000 --> 00:00:04,000",
                        "Structured work keeps the agent grounded.",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            cues = parse_srt_file(source_srt)
            windows = build_translation_windows(cues)
            payload = build_translation_template_payload(
                source_srt=source_srt,
                source_language="English",
                target_language="Spanish",
                windows=windows,
            )
            payload["windows"][0]["source_text"] = "Different source text"
            payload["windows"][0]["translated_text"] = "Texto diferente"

            with self.assertRaises(ValueError):
                build_translated_segments(
                    source_srt=source_srt,
                    source_language="English",
                    target_language="Spanish",
                    expected_windows=windows,
                    payload=payload,
                )


if __name__ == "__main__":
    unittest.main()
