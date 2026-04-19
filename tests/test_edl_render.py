from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock, patch

from media_tooling.edl_render import (
    EDLSchemaError,
    _is_image_path,
    _resolve_segment_bounds,
    _sorted_overlay_indices,
    _source_has_audio,
    _srt_timestamp,
    _validate_overlay,
    _words_in_range,
    apply_padding,
    build_afade_filter,
    build_final_composite,
    build_master_srt,
    build_overlay_chain,
    build_overlay_filter_parts,
    concat_segments,
    extract_all_segments,
    extract_segment,
    generate_overlay_card,
    resolve_grade_filter,
    resolve_overlay_sources,
    resolve_path,
    resolve_source_path,
    snap_to_word_boundary,
    validate_edl,
)

# ── Minimal valid EDL fixture ────────────────────────────────────────────────


def _minimal_edl() -> dict:
    return {
        "version": 1,
        "sources": ["source1.mp4"],
        "ranges": [
            {
                "source": "source1.mp4",
                "start": 12.34,
                "end": 18.92,
                "beat": "opening hook",
                "quote": "the thing that changed everything",
                "reason": "strong opening statement",
                "grade": "neutral_punch",
            }
        ],
        "overlays": [],
        "subtitles": {"style": "bold-overlay"},
        "total_duration_s": 180.0,
    }


def _multi_range_edl() -> dict:
    return {
        "version": 1,
        "sources": {"src_a": "a.mp4", "src_b": "b.mp4"},
        "ranges": [
            {
                "source": "src_a",
                "start": 0.0,
                "end": 5.0,
                "grade": "subtle",
            },
            {
                "source": "src_b",
                "start": 10.0,
                "end": 20.0,
                "grade": "auto",
            },
            {
                "source": "src_a",
                "start": 30.0,
                "end": 40.0,
                "grade": "none",
            },
        ],
    }


# ── EDL schema validation tests ──────────────────────────────────────────────


class ValidateEDLTests(unittest.TestCase):
    def test_valid_minimal_edl(self) -> None:
        validate_edl(_minimal_edl())  # should not raise

    def test_valid_multi_range_edl(self) -> None:
        validate_edl(_multi_range_edl())  # should not raise

    def test_missing_version(self) -> None:
        edl = _minimal_edl()
        del edl["version"]
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("version", str(ctx.exception))

    def test_missing_sources(self) -> None:
        edl = _minimal_edl()
        del edl["sources"]
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("sources", str(ctx.exception))

    def test_missing_ranges(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"]
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("ranges", str(ctx.exception))

    def test_wrong_version(self) -> None:
        edl = _minimal_edl()
        edl["version"] = 2
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("version", str(ctx.exception))

    def test_empty_ranges(self) -> None:
        edl = _minimal_edl()
        edl["ranges"] = []
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("non-empty", str(ctx.exception))

    def test_range_missing_source(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"][0]["source"]
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("source", str(ctx.exception))

    def test_range_missing_start(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"][0]["start"]
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("start", str(ctx.exception))

    def test_range_missing_end(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"][0]["end"]
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("end", str(ctx.exception))

    def test_range_end_before_start(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["start"] = 20.0
        edl["ranges"][0]["end"] = 10.0
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("greater than", str(ctx.exception))

    def test_unknown_source_in_range(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["source"] = "nonexistent.mp4"
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("not found in sources", str(ctx.exception))

    def test_invalid_sources_type(self) -> None:
        edl = _minimal_edl()
        edl["sources"] = 42
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("list or dict", str(ctx.exception))

    def test_unknown_grade_preset(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["grade"] = "nonexistent_preset"
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("not a known preset", str(ctx.exception))

    def test_duplicate_basenames_in_list_sources(self) -> None:
        edl = {
            "version": 1,
            "sources": ["/a/interview.mp4", "/b/interview.mp4"],
            "ranges": [{"source": "interview.mp4", "start": 0.0, "end": 5.0}],
        }
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("Duplicate basenames", str(ctx.exception))

    def test_raw_filter_grade_passes(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["grade"] = "eq=contrast=1.1:brightness=0.05"
        validate_edl(edl)  # should not raise

    def test_auto_grade_passes(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["grade"] = "auto"
        validate_edl(edl)  # should not raise

    def test_top_level_grade_unknown_preset_rejected(self) -> None:
        edl = _minimal_edl()
        edl["grade"] = "bad_preset"
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("top-level grade", str(ctx.exception))

    def test_top_level_grade_known_preset_passes(self) -> None:
        edl = _minimal_edl()
        edl["grade"] = "subtle"
        validate_edl(edl)  # should not raise

    def test_top_level_grade_auto_passes(self) -> None:
        edl = _minimal_edl()
        edl["grade"] = "auto"
        validate_edl(edl)  # should not raise

    def test_top_level_grade_raw_filter_passes(self) -> None:
        edl = _minimal_edl()
        edl["grade"] = "eq=contrast=1.1:brightness=0.05"
        validate_edl(edl)  # should not raise

    def test_sources_as_dict(self) -> None:
        edl = _minimal_edl()
        edl["sources"] = {"source1.mp4": "/path/to/source1.mp4"}
        validate_edl(edl)  # should not raise

    def test_sources_list_with_path_normalizes_to_basename(self) -> None:
        edl = _minimal_edl()
        edl["sources"] = ["/videos/source1.mp4"]
        validate_edl(edl)  # should not raise: basename matches range source

    def test_sources_list_relative_path_normalizes_to_basename(self) -> None:
        edl = _minimal_edl()
        edl["sources"] = ["videos/source1.mp4"]
        validate_edl(edl)  # basename "source1.mp4" matches range source

    def test_top_level_unknown_grade_rejected(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"][0]["grade"]
        edl["grade"] = "bad_preset"
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("top-level grade", str(ctx.exception))
        self.assertIn("bad_preset", str(ctx.exception))

    def test_top_level_known_grade_passes(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"][0]["grade"]
        edl["grade"] = "subtle"
        validate_edl(edl)  # should not raise

    def test_top_level_auto_grade_passes(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"][0]["grade"]
        edl["grade"] = "auto"
        validate_edl(edl)  # should not raise

    def test_top_level_raw_filter_grade_passes(self) -> None:
        edl = _minimal_edl()
        del edl["ranges"][0]["grade"]
        edl["grade"] = "eq=contrast=1.1:brightness=0.05"
        validate_edl(edl)  # should not raise

    def test_non_numeric_start_raises_edl_schema_error(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["start"] = "hello"
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("numeric", str(ctx.exception))

    def test_non_numeric_end_raises_edl_schema_error(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["end"] = None
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("numeric", str(ctx.exception))

    def test_non_numeric_start_string_number_passes(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["start"] = "12.34"
        validate_edl(edl)  # float("12.34") works fine

    def test_nan_start_raises_edl_schema_error(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["start"] = float("nan")
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("finite", str(ctx.exception))

    def test_infinity_end_raises_edl_schema_error(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["end"] = float("inf")
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("finite", str(ctx.exception))

    def test_neg_infinity_start_raises_edl_schema_error(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["start"] = float("-inf")
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("finite", str(ctx.exception))

    def test_subtitles_string_path_passes(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = "/path/to/subs.srt"
        validate_edl(edl)

    def test_subtitles_dict_with_valid_keys_passes(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = {"style": "bold-overlay", "path": "subs.srt"}
        validate_edl(edl)

    def test_subtitles_list_raises_edl_schema_error(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = [1, 2, 3]
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("subtitles must be a string path or dict", str(ctx.exception))

    def test_subtitles_int_raises_edl_schema_error(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = 42
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("subtitles must be a string path or dict", str(ctx.exception))

    def test_subtitles_dict_with_invalid_keys_raises(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = {"style": "bold", "unknown_key": "x"}
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("unknown keys", str(ctx.exception))

    def test_subtitles_dict_path_non_string_raises(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = {"path": 42}
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("subtitles 'path' must be a string", str(ctx.exception))

    def test_subtitles_dict_style_non_string_raises(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = {"style": 42}
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("subtitles 'style' must be a string", str(ctx.exception))

    def test_subtitles_dict_force_style_non_string_raises(self) -> None:
        edl = _minimal_edl()
        edl["subtitles"] = {"force_style": [1, 2]}
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("subtitles 'force_style' must be a string", str(ctx.exception))


# ── Grade resolution tests ──────────────────────────────────────────────────


class ResolveGradeFilterTests(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(resolve_grade_filter(None), "")

    def test_empty_string_returns_empty(self) -> None:
        self.assertEqual(resolve_grade_filter(""), "")

    def test_auto_returns_sentinel(self) -> None:
        self.assertEqual(resolve_grade_filter("auto"), "__AUTO__")

    def test_known_preset(self) -> None:
        result = resolve_grade_filter("subtle")
        self.assertEqual(result, "eq=contrast=1.03:saturation=0.98")

    def test_raw_filter_passthrough(self) -> None:
        raw = "eq=contrast=1.1:brightness=0.05"
        self.assertEqual(resolve_grade_filter(raw), raw)

    def test_unknown_simple_name_raises_valueerror(self) -> None:
        # Unknown name without = or , raises ValueError (not passed through)
        with self.assertRaises(ValueError) as ctx:
            resolve_grade_filter("unknown_preset")
        self.assertIn("unknown grade preset", str(ctx.exception))


# ── Padding tests (Hard Rule 7) ─────────────────────────────────────────────


class ApplyPaddingTests(unittest.TestCase):
    def test_default_padding(self) -> None:
        start, end = apply_padding(10.0, 20.0)
        self.assertAlmostEqual(start, 9.97, places=3)
        self.assertAlmostEqual(end, 20.03, places=3)

    def test_padding_clamps_to_zero(self) -> None:
        start, end = apply_padding(0.01, 5.0)
        self.assertEqual(start, 0.0)
        self.assertGreater(end, 5.0)

    def test_padding_respects_source_duration(self) -> None:
        start, end = apply_padding(10.0, 59.98, source_duration=60.0)
        self.assertAlmostEqual(end, 60.0, places=2)

    def test_custom_min_pad(self) -> None:
        start, end = apply_padding(10.0, 20.0, min_pad=0.1)
        self.assertAlmostEqual(start, 9.9, places=2)
        self.assertAlmostEqual(end, 20.1, places=2)

    def test_min_pad_exceeds_max_pad_raises_value_error(self) -> None:
        """When min_pad > max_pad, raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            apply_padding(10.0, 20.0, min_pad=0.5, max_pad=0.2)
        self.assertIn("min_pad", str(ctx.exception))

    def test_max_pad_respected_when_equal(self) -> None:
        """When min_pad == max_pad, pad is exactly that amount."""
        start, end = apply_padding(10.0, 20.0, min_pad=0.2, max_pad=0.2)
        self.assertAlmostEqual(start, 9.8, places=2)
        self.assertAlmostEqual(end, 20.2, places=2)

    def test_right_edge_clamp_never_produces_negative_duration(self) -> None:
        """When source_duration < padded_start, padded_end clamped to padded_start."""
        start, end = apply_padding(0.04, 0.05, source_duration=0.005)
        self.assertGreaterEqual(end, start)
        self.assertEqual(end, start)  # both clamp to padded_start


# ── Word-boundary alignment tests (Hard Rule 6) ─────────────────────────────


class SnapToWordBoundaryTests(unittest.TestCase):
    def test_no_words_returns_unchanged(self) -> None:
        start, end = snap_to_word_boundary(10.0, 20.0, [])
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 20.0)

    def test_snap_start_to_word_beginning(self) -> None:
        words = [
            {"start": 9.8, "end": 10.5, "text": "hello"},
            {"start": 10.6, "end": 11.0, "text": "world"},
        ]
        start, end = snap_to_word_boundary(9.9, 11.0, words)
        self.assertAlmostEqual(start, 9.8, places=2)
        self.assertAlmostEqual(end, 11.0, places=2)

    def test_snap_end_to_word_end(self) -> None:
        words = [
            {"start": 10.0, "end": 10.5, "text": "hello"},
            {"start": 10.6, "end": 11.2, "text": "world"},
        ]
        start, end = snap_to_word_boundary(10.0, 11.1, words)
        self.assertAlmostEqual(start, 10.0, places=2)
        self.assertAlmostEqual(end, 11.2, places=2)

    def test_no_overlap_returns_unchanged(self) -> None:
        words = [
            {"start": 0.0, "end": 1.0, "text": "before"},
            {"start": 25.0, "end": 26.0, "text": "after"},
        ]
        start, end = snap_to_word_boundary(10.0, 20.0, words)
        self.assertEqual(start, 10.0)
        self.assertEqual(end, 20.0)


# ── Audio fade tests (Hard Rule 3) ──────────────────────────────────────────


class ResolveSegmentBoundsTests(unittest.TestCase):
    """Tests for _resolve_segment_bounds (shared snap→pad helper)."""

    def test_no_transcript_returns_padded_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            source_durations: dict[str, float] = {}
            padded_start, padded_end, words = _resolve_segment_bounds(
                10.0, 20.0, "src.mp4", edit_dir, source_durations,
            )
            self.assertEqual(words, [])
            # Padding applied to raw 10.0–20.0
            self.assertAlmostEqual(padded_start, 9.97, places=2)
            self.assertAlmostEqual(padded_end, 20.03, places=2)

    def test_corrupt_transcript_uses_raw_cut_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            tr_dir = edit_dir / "transcripts"
            tr_dir.mkdir()
            (tr_dir / "src.mp4.json").write_text("NOT JSON{{{", encoding="utf-8")
            source_durations: dict[str, float] = {}
            with patch("builtins.print"):
                padded_start, padded_end, words = _resolve_segment_bounds(
                    10.0, 20.0, "src.mp4", edit_dir, source_durations,
                )
            self.assertEqual(words, [])
            self.assertAlmostEqual(padded_start, 9.97, places=2)

    def test_valid_transcript_snaps_and_pads(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            tr_dir = edit_dir / "transcripts"
            tr_dir.mkdir()
            transcript = {
                "words": [
                    {"start": 9.8, "end": 10.5, "text": "hello", "type": "word"},
                    {"start": 19.6, "end": 20.2, "text": "world", "type": "word"},
                ]
            }
            (tr_dir / "src.mp4.json").write_text(
                json.dumps(transcript), encoding="utf-8"
            )
            source_durations: dict[str, float] = {"src.mp4": 9999.0}
            padded_start, padded_end, words = _resolve_segment_bounds(
                9.9, 20.1, "src.mp4", edit_dir, source_durations,
            )
            # Snapped: start→9.8, end→20.2, then padded
            self.assertAlmostEqual(padded_start, 9.77, places=2)
            self.assertAlmostEqual(padded_end, 20.23, places=2)
            self.assertEqual(len(words), 2)


# ── Audio fade tests (Hard Rule 3) ──────────────────────────────────────────


class BuildAfadeFilterTests(unittest.TestCase):
    def test_typical_duration(self) -> None:
        result = build_afade_filter(10.0)
        self.assertIn("afade=t=in:st=0:d=0.03", result)
        self.assertIn("afade=t=out:st=9.97", result)

    def test_short_duration_returns_empty(self) -> None:
        result = build_afade_filter(0.05)
        self.assertEqual(result, "")

    def test_exact_minimum_duration(self) -> None:
        result = build_afade_filter(0.06)
        self.assertIn("afade=t=in:st=0:d=0.03", result)
        self.assertIn("afade=t=out:st=0.03", result)


# ── Source path resolution tests ────────────────────────────────────────────


class ResolveSourcePathTests(unittest.TestCase):
    def test_list_sources(self) -> None:
        edl = {"sources": ["source1.mp4"]}
        result = resolve_source_path("source1.mp4", edl, Path("/base"))
        self.assertEqual(result, Path("/base/source1.mp4"))

    def test_list_sources_with_path_resolves_by_basename(self) -> None:
        edl = {"sources": ["/videos/source1.mp4"]}
        result = resolve_source_path("source1.mp4", edl, Path("/base"))
        self.assertEqual(result, Path("/videos/source1.mp4"))

    def test_list_sources_relative_path_resolves_by_basename(self) -> None:
        edl = {"sources": ["videos/source1.mp4"]}
        result = resolve_source_path("source1.mp4", edl, Path("/base"))
        self.assertEqual(result, Path("/base/videos/source1.mp4"))

    def test_dict_sources(self) -> None:
        edl = {"sources": {"src_a": "/absolute/path/a.mp4"}}
        result = resolve_source_path("src_a", edl, Path("/base"))
        self.assertEqual(result, Path("/absolute/path/a.mp4"))

    def test_dict_sources_relative(self) -> None:
        edl = {"sources": {"src_a": "relative/a.mp4"}}
        result = resolve_source_path("src_a", edl, Path("/base"))
        self.assertEqual(result, Path("/base/relative/a.mp4"))

    def test_dict_sources_tilde_expands(self) -> None:
        edl = {"sources": {"src_a": "~/videos/a.mp4"}}
        result = resolve_source_path("src_a", edl, Path("/base"))
        # Should NOT resolve to /base/~/videos/a.mp4
        self.assertNotIn("~", str(result))
        self.assertTrue(result.is_absolute())


class ResolvePathTests(unittest.TestCase):
    def test_absolute_path_unchanged(self) -> None:
        result = resolve_path("/abs/path.srt")
        self.assertEqual(result, Path("/abs/path.srt"))

    def test_relative_with_base(self) -> None:
        result = resolve_path("rel.srt", base=Path("/base"))
        self.assertEqual(result, Path("/base/rel.srt"))

    def test_tilde_expands(self) -> None:
        result = resolve_path("~/videos/subs.srt", base=Path("/base"))
        # Should NOT resolve to /base/~/videos/subs.srt
        self.assertNotIn("~", str(result))
        self.assertTrue(result.is_absolute())


# ── Words-in-range tests ────────────────────────────────────────────────────


class WordsInRangeTests(unittest.TestCase):
    def test_returns_overlapping_words(self) -> None:
        transcript = {
            "words": [
                {"type": "word", "start": 0.0, "end": 0.5, "text": "hello"},
                {"type": "word", "start": 0.6, "end": 1.0, "text": "world"},
                {"type": "word", "start": 1.1, "end": 1.5, "text": "foo"},
            ]
        }
        result = _words_in_range(transcript, 0.3, 1.2)
        # hello (0.0-0.5): 0.5 > 0.3 → included
        # world (0.6-1.0): 1.0 > 0.3 and 0.6 < 1.2 → included
        # foo (1.1-1.5): 1.5 > 0.3 and 1.1 < 1.2 → included
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["text"], "hello")
        self.assertEqual(result[1]["text"], "world")
        self.assertEqual(result[2]["text"], "foo")

    def test_skips_non_word_types(self) -> None:
        transcript = {
            "words": [
                {"type": "silence", "start": 0.0, "end": 0.5},
                {"type": "word", "start": 0.6, "end": 1.0, "text": "hello"},
            ]
        }
        result = _words_in_range(transcript, 0.0, 1.0)
        self.assertEqual(len(result), 1)

    def test_skips_words_without_timestamps(self) -> None:
        transcript = {
            "words": [
                {"type": "word", "text": "hello"},
                {"type": "word", "start": 0.6, "end": 1.0, "text": "world"},
            ]
        }
        result = _words_in_range(transcript, 0.0, 1.0)
        self.assertEqual(len(result), 1)

    def test_empty_transcript(self) -> None:
        result = _words_in_range({}, 0.0, 10.0)
        self.assertEqual(result, [])


# ── Master SRT tests (Hard Rule 5) ──────────────────────────────────────────


class SrtTimestampTests(unittest.TestCase):
    def test_zero(self) -> None:
        self.assertEqual(_srt_timestamp(0.0), "00:00:00,000")

    def test_simple_seconds(self) -> None:
        self.assertEqual(_srt_timestamp(5.5), "00:00:05,500")

    def test_minutes(self) -> None:
        self.assertEqual(_srt_timestamp(90.0), "00:01:30,000")

    def test_hours(self) -> None:
        self.assertEqual(_srt_timestamp(3723.5), "01:02:03,500")


class BuildMasterSrtTests(unittest.TestCase):
    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    def test_builds_srt_with_output_timeline_offsets(self, mock_probe: MagicMock) -> None:
        """Master SRT uses output-timeline offsets (Hard Rule 5)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            transcripts_dir = edit_dir / "transcripts"
            transcripts_dir.mkdir()

            # Create transcript for source
            transcript = {
                "words": [
                    {"type": "word", "start": 0.5, "end": 1.0, "text": "hello"},
                    {"type": "word", "start": 1.1, "end": 1.5, "text": "world"},
                    {"type": "word", "start": 1.6, "end": 2.0, "text": "foo"},
                    {"type": "word", "start": 2.1, "end": 2.5, "text": "bar"},
                ]
            }
            (transcripts_dir / "source1.mp4.json").write_text(
                json.dumps(transcript), encoding="utf-8"
            )

            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    {"source": "source1.mp4", "start": 0.5, "end": 2.5},
                ],
            }

            out_path = edit_dir / "master.srt"
            build_master_srt(edl, edit_dir, out_path)

            srt_content = out_path.read_text(encoding="utf-8")
            # Should have at least one cue
            self.assertIn("-->", srt_content)
            # With padding (30ms each edge), padded_start = 0.5-0.03 = 0.47
            # First word starts at 0.5 in source → out_start = 0.5 - 0.47 + 0 = 0.03
            # So the first cue should start at ~30ms
            self.assertIn("00:00:00,030", srt_content)

    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    def test_multi_range_srt_offsets_use_padded_durations(self, mock_probe: MagicMock) -> None:
        """Multiple ranges: segment offsets use padded durations (Hard Rule 5).

        This is the critical SRT offset drift fix — if we used unpadded
        durations, the second segment's subtitles would drift by ~60ms per
        preceding segment.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            transcripts_dir = edit_dir / "transcripts"
            transcripts_dir.mkdir()

            # Source names in the EDL are the dict keys ("src_a", "src_b")
            transcript_a = {
                "words": [
                    {"type": "word", "start": 5.0, "end": 5.5, "text": "first"},
                    {"type": "word", "start": 5.6, "end": 6.0, "text": "segment"},
                ]
            }
            (transcripts_dir / "src_a.json").write_text(
                json.dumps(transcript_a), encoding="utf-8"
            )

            transcript_b = {
                "words": [
                    {"type": "word", "start": 10.0, "end": 10.5, "text": "second"},
                    {"type": "word", "start": 10.6, "end": 11.0, "text": "segment"},
                ]
            }
            (transcripts_dir / "src_b.json").write_text(
                json.dumps(transcript_b), encoding="utf-8"
            )

            edl = {
                "version": 1,
                "sources": {"src_a": "a.mp4", "src_b": "b.mp4"},
                "ranges": [
                    {"source": "src_a", "start": 5.0, "end": 6.0},
                    {"source": "src_b", "start": 10.0, "end": 11.0},
                ],
            }

            out_path = edit_dir / "master.srt"
            build_master_srt(edl, edit_dir, out_path)

            srt_content = out_path.read_text(encoding="utf-8")
            # With padding: first range duration = (6.0+0.03) - (5.0-0.03) = 1.06s
            # Second range offset starts at 1.06s
            # padded_start for second range = 10.0-0.03 = 9.97
            # word "second" at 10.0: out_start = (10.0-9.97) + 1.06 = 1.09
            self.assertIn("00:00:01,090", srt_content)

    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    def test_srt_offsets_match_padded_segment_timeline(self, mock_probe: MagicMock) -> None:
        """SRT offset accumulation must use padded durations, not raw EDL ranges.

        Regression test for the SRT offset drift bug: with default 30ms
        padding per edge, each segment adds 60ms more than the raw range.
        After N segments the SRT drifts by ~N*60ms if unpadded durations
        are used for offset accumulation.
        """
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            transcripts_dir = edit_dir / "transcripts"
            transcripts_dir.mkdir()

            transcript = {
                "words": [
                    {"type": "word", "start": 0.0, "end": 0.5, "text": "word"},
                    {"type": "word", "start": 0.6, "end": 1.0, "text": "one"},
                    {"type": "word", "start": 10.0, "end": 10.5, "text": "word"},
                    {"type": "word", "start": 10.6, "end": 11.0, "text": "two"},
                    {"type": "word", "start": 20.0, "end": 20.5, "text": "word"},
                    {"type": "word", "start": 20.6, "end": 21.0, "text": "three"},
                ]
            }
            (transcripts_dir / "src.json").write_text(
                json.dumps(transcript), encoding="utf-8"
            )

            edl = {
                "version": 1,
                "sources": {"src": "src.mp4"},
                "ranges": [
                    {"source": "src", "start": 0.0, "end": 1.0},
                    {"source": "src", "start": 10.0, "end": 11.0},
                    {"source": "src", "start": 20.0, "end": 21.0},
                ],
            }

            out_path = edit_dir / "master.srt"
            build_master_srt(edl, edit_dir, out_path)

            srt_content = out_path.read_text(encoding="utf-8")

            # Segment 0: start=0.0, end=1.0 → padded_start=0.0 (clamped), padded_end=1.03, dur=1.03
            # Segment 1: start=10.0, end=11.0 → padded_start=9.97, padded_end=11.03, dur=1.06
            # Segment 2: start=20.0, end=21.0 → padded_start=19.97, padded_end=21.03, dur=1.06

            # seg_offset after seg 0: 1.03
            # seg_offset after seg 1: 1.03 + 1.06 = 2.09

            # Third segment word "word" at 20.0:
            # out_start = (20.0 - 19.97) + 2.09 = 0.03 + 2.09 = 2.12
            # If unpadded: would be (20.0 - 20.0) + 2.0 = 2.0 (drift!)
            self.assertIn("00:00:02,120", srt_content)
            # Verify unpadded value would NOT appear
            self.assertNotIn("00:00:02,000 -->", srt_content)

    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    def test_missing_transcript_skips_segment(self, mock_probe: MagicMock) -> None:
        """Missing transcript for a source produces a warning but no crash."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl = {
                "version": 1,
                "sources": ["missing.mp4"],
                "ranges": [
                    {"source": "missing.mp4", "start": 0.0, "end": 5.0},
                ],
            }

            out_path = edit_dir / "master.srt"
            with patch("builtins.print"):
                build_master_srt(edl, edit_dir, out_path)

            # Should create empty-ish SRT (just header)
            content = out_path.read_text(encoding="utf-8")
            # No cue entries since there's no transcript
            self.assertNotIn("-->", content)

    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    def test_unreadable_transcript_skips_segment(self, mock_probe: MagicMock) -> None:
        """Unreadable transcript (OSError) in build_master_srt warns and skips."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            transcripts_dir = edit_dir / "transcripts"
            transcripts_dir.mkdir()
            tr_path = transcripts_dir / "source1.mp4.json"
            tr_path.write_text('{"words": []}', encoding="utf-8")
            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    {"source": "source1.mp4", "start": 0.0, "end": 5.0},
                ],
            }
            out_path = edit_dir / "master.srt"
            with patch.object(Path, "read_text", side_effect=OSError("permission denied")), \
                 patch("builtins.print") as mock_print:
                build_master_srt(edl, edit_dir, out_path)
            warning_calls = [
                c for c in mock_print.call_args_list
                if "unreadable transcript" in str(c)
            ]
            self.assertGreater(len(warning_calls), 0)


# ── Segment extraction tests ────────────────────────────────────────────────


class ExtractSegmentTests(unittest.TestCase):
    @patch("media_tooling.edl_render.subprocess.run")
    def test_ffmpeg_command_includes_grade_and_fades(
        self, mock_run: MagicMock
    ) -> None:
        """extract_segment builds a command with grade filter and afade."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "seg.mp4"
            extract_segment(
                Path("/tmp/source.mp4"),
                seg_start=10.0,
                duration=5.0,
                grade_filter="eq=contrast=1.05",
                out_path=out_path,
            )
        cmd = mock_run.call_args[0][0]
        # Should have -vf with scale + grade
        vf_idx = cmd.index("-vf")
        vf = cmd[vf_idx + 1]
        self.assertIn("scale=1920:-2", vf)
        self.assertIn("eq=contrast=1.05", vf)
        # Should have -af with fades
        af_idx = cmd.index("-af")
        af = cmd[af_idx + 1]
        self.assertIn("afade=t=in:st=0:d=0.03", af)
        self.assertIn("afade=t=out", af)

    @patch("media_tooling.edl_render.subprocess.run")
    def test_short_segment_omits_afade(self, mock_run: MagicMock) -> None:
        """Very short segments (<60ms) should not have -af."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "seg.mp4"
            extract_segment(
                Path("/tmp/source.mp4"),
                seg_start=10.0,
                duration=0.05,
                grade_filter="",
                out_path=out_path,
            )
        cmd = mock_run.call_args[0][0]
        self.assertNotIn("-af", cmd)

    @patch("media_tooling.edl_render.subprocess.run")
    def test_draft_mode_uses_ultrafast(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "seg.mp4"
            extract_segment(
                Path("/tmp/source.mp4"),
                seg_start=10.0,
                duration=5.0,
                grade_filter="",
                out_path=out_path,
                draft=True,
            )
        cmd = mock_run.call_args[0][0]
        self.assertIn("ultrafast", cmd)
        self.assertIn("28", cmd)

    @patch("media_tooling.edl_render.subprocess.run")
    def test_preview_mode_uses_medium(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "seg.mp4"
            extract_segment(
                Path("/tmp/source.mp4"),
                seg_start=10.0,
                duration=5.0,
                grade_filter="",
                out_path=out_path,
                preview=True,
            )
        cmd = mock_run.call_args[0][0]
        self.assertIn("medium", cmd)
        self.assertIn("22", cmd)

    @patch("media_tooling.edl_render._source_has_audio", return_value=False)
    @patch("media_tooling.edl_render.subprocess.run")
    def test_audioless_source_skips_afade_and_uses_an(self, mock_run: MagicMock, mock_has_audio: MagicMock) -> None:
        """Sources without audio should skip afade and use -an instead of -c:a."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "seg.mp4"
            extract_segment(
                Path("/tmp/source.mp4"),
                seg_start=10.0,
                duration=5.0,
                grade_filter="",
                out_path=out_path,
            )
        cmd = mock_run.call_args[0][0]
        # Should NOT have -af
        self.assertNotIn("-af", cmd)
        # Should have -an (no audio)
        self.assertIn("-an", cmd)
        # Should NOT have -c:a
        self.assertNotIn("-c:a", cmd)

    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.subprocess.run")
    def test_audio_source_includes_afade_and_c_a(self, mock_run: MagicMock, mock_has_audio: MagicMock) -> None:
        """Sources with audio should include afade and -c:a aac."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "seg.mp4"
            extract_segment(
                Path("/tmp/source.mp4"),
                seg_start=10.0,
                duration=5.0,
                grade_filter="",
                out_path=out_path,
            )
        cmd = mock_run.call_args[0][0]
        self.assertIn("-af", cmd)
        self.assertIn("-c:a", cmd)


class SourceHasAudioTests(unittest.TestCase):
    @patch("media_tooling.edl_render.subprocess.run")
    def test_returns_true_when_audio_stream_present(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="codec_type\naudio\n", returncode=0)
        result = _source_has_audio(Path("/tmp/source.mp4"))
        self.assertTrue(result)

    @patch("media_tooling.edl_render.subprocess.run")
    def test_returns_false_when_no_audio_stream(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        result = _source_has_audio(Path("/tmp/source.mp4"))
        self.assertFalse(result)

    @patch("media_tooling.edl_render.subprocess.run", side_effect=FileNotFoundError)
    def test_returns_true_when_ffprobe_unavailable(self, mock_run: MagicMock) -> None:
        result = _source_has_audio(Path("/tmp/source.mp4"))
        self.assertTrue(result)  # safe default: assume audio present


class ExtractAllSegmentsTests(unittest.TestCase):
    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    @patch("media_tooling.edl_render.subprocess.run")
    @patch("media_tooling.edl_render.auto_grade_for_clip")
    def test_auto_grade_per_segment(
        self, mock_auto: MagicMock, mock_run: MagicMock, mock_probe: MagicMock, mock_has_audio: MagicMock
    ) -> None:
        mock_auto.return_value = ("eq=contrast=1.05", {})
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl = _multi_range_edl()
            seg_paths = extract_all_segments(edl, edit_dir)
        self.assertEqual(len(seg_paths), 3)
        # Second range has grade="auto" → should call auto_grade_for_clip once
        self.assertEqual(mock_auto.call_count, 1)
        # Find the ffmpeg extract call with the auto-grade filter
        # (call order may include _source_has_audio probes before each extract)
        auto_cmd = None
        for call in mock_run.call_args_list:
            cmd = call[0][0]
            if cmd[0] == "ffmpeg" and "-vf" in cmd:
                vf_idx = cmd.index("-vf")
                if "eq=contrast=1.05" in cmd[vf_idx + 1]:
                    auto_cmd = cmd
                    break
        self.assertIsNotNone(auto_cmd, "auto-graded ffmpeg command not found")

    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    @patch("media_tooling.edl_render.subprocess.run")
    def test_preset_grade_per_segment(self, mock_run: MagicMock, mock_probe: MagicMock, mock_has_audio: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    {"source": "source1.mp4", "start": 0.0, "end": 5.0, "grade": "subtle"},
                ],
            }
            extract_all_segments(edl, edit_dir)
        # Find the ffmpeg extract call (not the _source_has_audio ffprobe call)
        cmd = None
        for call in mock_run.call_args_list:
            c = call[0][0]
            if c[0] == "ffmpeg" and "-vf" in c:
                cmd = c
                break
        self.assertIsNotNone(cmd)
        assert cmd is not None  # for mypy
        vf_idx = cmd.index("-vf")
        vf_value = cmd[vf_idx + 1]
        self.assertIn("contrast=1.03", vf_value)

    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    @patch("media_tooling.edl_render.subprocess.run")
    def test_corrupt_transcript_falls_back_to_raw_cut_points(
        self, mock_run: MagicMock, mock_probe: MagicMock, mock_has_audio: MagicMock
    ) -> None:
        """Corrupt transcript JSON in extract_all_segments warns and uses raw cuts."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            tr_dir = edit_dir / "transcripts"
            tr_dir.mkdir()
            # Write corrupt JSON
            (tr_dir / "source1.mp4.json").write_text("NOT JSON{{{", encoding="utf-8")
            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    {"source": "source1.mp4", "start": 1.0, "end": 5.0},
                ],
            }
            with patch("builtins.print") as mock_print:
                seg_paths = extract_all_segments(edl, edit_dir)
            # Should still extract (no crash), with raw cut points
            self.assertEqual(len(seg_paths), 1)
            # Should have printed a warning about corrupt transcript
            warning_calls = [
                c for c in mock_print.call_args_list
                if "corrupt/unreadable transcript" in str(c)
            ]
            self.assertGreater(len(warning_calls), 0)

    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.subprocess.run")
    @patch("media_tooling.edl_render.probe_duration", return_value=9999.0)
    def test_unreadable_transcript_falls_back_to_raw_cut_points(
        self, mock_probe: MagicMock, mock_run: MagicMock, mock_has_audio: MagicMock
    ) -> None:
        """Unreadable transcript file (OSError) in extract_all_segments warns and uses raw cuts."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            tr_dir = edit_dir / "transcripts"
            tr_dir.mkdir()
            tr_path = tr_dir / "source1.mp4.json"
            # Create a file that exists but mock read_text to raise OSError
            tr_path.write_text('{"words": []}', encoding="utf-8")
            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    {"source": "source1.mp4", "start": 1.0, "end": 5.0},
                ],
            }
            with patch.object(Path, "read_text", side_effect=OSError("permission denied")), \
                 patch("builtins.print") as mock_print:
                seg_paths = extract_all_segments(edl, edit_dir)
            # Should still extract (no crash), with raw cut points
            self.assertEqual(len(seg_paths), 1)
            # Should have printed a warning about unreadable transcript
            warning_calls = [
                c for c in mock_print.call_args_list
                if "unreadable transcript" in str(c)
            ]
            self.assertGreater(len(warning_calls), 0)

    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.probe_duration", return_value=0.005)
    @patch("media_tooling.edl_render.subprocess.run")
    def test_zero_duration_segment_raises_runtime_error(
        self, mock_run: MagicMock, mock_probe: MagicMock, mock_has_audio: MagicMock
    ) -> None:
        """Segment with zero/negative duration after padding raises RuntimeError."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            # Source duration is 0.005s, range is 0.04-0.05, so padded_end clamps
            # to padded_start, producing zero duration
            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    {"source": "source1.mp4", "start": 0.04, "end": 0.05},
                ],
            }
            with self.assertRaises(RuntimeError) as ctx:
                extract_all_segments(edl, edit_dir)
            self.assertIn("zero/negative duration", str(ctx.exception))


# ── Concat tests (Hard Rule 2) ───────────────────────────────────────────────


class ConcatSegmentsTests(unittest.TestCase):
    @patch("media_tooling.edl_render.subprocess.run")
    @patch("media_tooling.edl_render.validate_concat_demuxer_usage")
    def test_uses_concat_demuxer(
        self, mock_validate: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            seg1 = edit_dir / "seg1.mp4"
            seg1.write_text("fake")
            out_path = edit_dir / "output.mp4"

            concat_segments([seg1], out_path, edit_dir)

        # Validate was called with the command
        mock_validate.assert_called_once()
        cmd = mock_validate.call_args[0][0]
        self.assertIn("-f", cmd)
        f_idx = cmd.index("-f")
        self.assertEqual(cmd[f_idx + 1], "concat")
        self.assertIn("-c", cmd)
        c_idx = cmd.index("-c")
        self.assertEqual(cmd[c_idx + 1], "copy")

    @patch("media_tooling.edl_render.subprocess.run")
    def test_concat_list_written_and_cleaned_up(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            seg1 = edit_dir / "seg1.mp4"
            seg1.write_text("fake")
            out_path = edit_dir / "output.mp4"

            concat_segments([seg1], out_path, edit_dir)

        # _concat.txt should be cleaned up
        concat_list = edit_dir / "_concat.txt"
        self.assertFalse(concat_list.exists())

    @patch("media_tooling.edl_render.subprocess.run")
    def test_concat_list_uses_single_quote_escaping(self, mock_run: MagicMock) -> None:
        """Paths in concat manifest must use single-quote escaping (ffmpeg concat demuxer format)."""
        captured_content: str = ""

        def _capture_and_succeed(*args: object, **kwargs: object) -> MagicMock:
            nonlocal captured_content
            # The concat list file is the -i argument
            cmd = cast("list[str]", args[0])
            i_idx = cmd.index("-i")
            concat_path = Path(cmd[i_idx + 1])
            captured_content = concat_path.read_text()
            return MagicMock(returncode=0)

        mock_run.side_effect = _capture_and_succeed
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            seg1 = edit_dir / "seg1.mp4"
            seg1.write_text("fake")
            out_path = edit_dir / "output.mp4"

            concat_segments([seg1], out_path, edit_dir)

        # Single-quoted path format, not double-quoted
        self.assertIn("file '", captured_content)
        self.assertNotIn('file "', captured_content)

    @patch("media_tooling.edl_render.subprocess.run")
    @patch("media_tooling.edl_render.validate_concat_demuxer_usage")
    def test_concat_ffmpeg_failure_raises_runtime_error(
        self, mock_validate: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            seg1 = edit_dir / "seg1.mp4"
            seg1.write_text("fake")
            out_path = edit_dir / "output.mp4"

            with self.assertRaises(RuntimeError) as ctx:
                concat_segments([seg1], out_path, edit_dir)
            self.assertIn("concat failed", str(ctx.exception))

    @patch("media_tooling.edl_render.subprocess.run")
    @patch("media_tooling.edl_render.validate_concat_demuxer_usage")
    def test_concat_ffmpeg_not_found_raises_runtime_error(
        self, mock_validate: MagicMock, mock_run: MagicMock
    ) -> None:
        mock_run.side_effect = FileNotFoundError("ffmpeg not found")
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            seg1 = edit_dir / "seg1.mp4"
            seg1.write_text("fake")
            out_path = edit_dir / "output.mp4"

            with self.assertRaises(RuntimeError) as ctx:
                concat_segments([seg1], out_path, edit_dir)
            self.assertIn("not found", str(ctx.exception))


# ── CLI tests ───────────────────────────────────────────────────────────────


class ParseArgsTests(unittest.TestCase):
    def test_requires_edl_and_output(self) -> None:
        from media_tooling.edl_render import parse_args
        with self.assertRaises(SystemExit):
            parse_args([])

    def test_valid_args(self) -> None:
        from media_tooling.edl_render import parse_args
        args = parse_args(["edl.json", "-o", "output.mp4"])
        self.assertEqual(args.edl, Path("edl.json"))
        self.assertEqual(args.output, Path("output.mp4"))
        self.assertFalse(args.preview)
        self.assertFalse(args.draft)

    def test_preview_flag(self) -> None:
        from media_tooling.edl_render import parse_args
        args = parse_args(["edl.json", "-o", "output.mp4", "--preview"])
        self.assertTrue(args.preview)

    def test_draft_flag(self) -> None:
        from media_tooling.edl_render import parse_args
        args = parse_args(["edl.json", "-o", "output.mp4", "--draft"])
        self.assertTrue(args.draft)

    def test_build_subtitles_flag(self) -> None:
        from media_tooling.edl_render import parse_args
        args = parse_args(["edl.json", "-o", "output.mp4", "--build-subtitles"])
        self.assertTrue(args.build_subtitles)

    def test_no_subtitles_flag(self) -> None:
        from media_tooling.edl_render import parse_args
        args = parse_args(["edl.json", "-o", "output.mp4", "--no-subtitles"])
        self.assertTrue(args.no_subtitles)

    def test_no_loudnorm_flag(self) -> None:
        from media_tooling.edl_render import parse_args
        args = parse_args(["edl.json", "-o", "output.mp4", "--no-loudnorm"])
        self.assertTrue(args.no_loudnorm)

    def test_preview_and_draft_mutually_exclusive(self) -> None:
        from media_tooling.edl_render import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["edl.json", "-o", "output.mp4", "--preview", "--draft"])

    def test_build_subtitles_and_no_subtitles_mutually_exclusive(self) -> None:
        from media_tooling.edl_render import parse_args
        with self.assertRaises(SystemExit):
            parse_args(["edl.json", "-o", "output.mp4", "--build-subtitles", "--no-subtitles"])


class RenderEDLTests(unittest.TestCase):
    @patch("media_tooling.edl_render.apply_loudnorm_two_pass", return_value=True)
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_full_pipeline_no_subtitles(
        self,
        mock_extract: MagicMock,
        mock_concat: MagicMock,
        mock_loudnorm: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl_path.write_text(json.dumps(_minimal_edl()), encoding="utf-8")
            output_path = edit_dir / "output.mp4"

            # Create the base.mp4 that concat would produce
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)

            mock_extract.return_value = [edit_dir / "seg_00.mp4"]
            # Make concat create the base file
            def fake_concat(*a: object, **kw: object) -> None:
                base_path.write_bytes(b"\x00" * 100)
            mock_concat.side_effect = fake_concat

            # Make loudnorm create the output
            def fake_loudnorm(inp: object, out: Path, **kw: object) -> bool:
                out.write_bytes(b"\x00" * 100)
                return True
            mock_loudnorm.side_effect = fake_loudnorm

            from media_tooling.edl_render import render_edl
            result = render_edl(
                edl_path, output_path,
                no_subtitles=True, no_loudnorm=False,
            )
        self.assertEqual(result, 0)

    def test_missing_edl_file(self) -> None:
        from media_tooling.edl_render import render_edl
        result = render_edl(Path("/nonexistent/edl.json"), Path("/tmp/out.mp4"))
        self.assertEqual(result, 1)

    def test_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edl_path = Path(tmpdir) / "bad.json"
            edl_path.write_text("not json", encoding="utf-8")
            from media_tooling.edl_render import render_edl
            result = render_edl(edl_path, Path(tmpdir) / "out.mp4")
        self.assertEqual(result, 1)

    def test_schema_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edl_path = Path(tmpdir) / "bad.json"
            edl_path.write_text(json.dumps({"version": 1}), encoding="utf-8")
            from media_tooling.edl_render import render_edl
            result = render_edl(edl_path, Path(tmpdir) / "out.mp4")
        self.assertEqual(result, 1)

    @patch("media_tooling.edl_render.extract_all_segments")
    def test_extract_runtime_error_returns_1(self, mock_extract: MagicMock) -> None:
        mock_extract.side_effect = RuntimeError("ffmpeg extract failed")
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl_path.write_text(json.dumps(_minimal_edl()), encoding="utf-8")
            output_path = edit_dir / "output.mp4"
            from media_tooling.edl_render import render_edl
            result = render_edl(edl_path, output_path, no_subtitles=True, no_loudnorm=True)
        self.assertEqual(result, 1)

    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_concat_runtime_error_returns_1(
        self, mock_extract: MagicMock, mock_concat: MagicMock
    ) -> None:
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]
        mock_concat.side_effect = RuntimeError("ffmpeg concat failed")
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl_path.write_text(json.dumps(_minimal_edl()), encoding="utf-8")
            output_path = edit_dir / "output.mp4"
            from media_tooling.edl_render import render_edl
            result = render_edl(edl_path, output_path, no_subtitles=True, no_loudnorm=True)
        self.assertEqual(result, 1)

    @patch("media_tooling.edl_render.build_master_srt")
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_build_master_srt_os_error_returns_1(
        self, mock_extract: MagicMock, mock_concat: MagicMock, mock_srt: MagicMock
    ) -> None:
        """OSError from build_master_srt is caught and returns 1."""
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]
        mock_concat.return_value = None
        mock_srt.side_effect = OSError("disk full")
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl_path.write_text(json.dumps(_minimal_edl()), encoding="utf-8")
            output_path = edit_dir / "output.mp4"
            from media_tooling.edl_render import render_edl
            result = render_edl(edl_path, output_path, build_subtitles=True, no_loudnorm=True)
        self.assertEqual(result, 1)

    @patch("media_tooling.edl_render.burn_subtitles_last")
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_subtitle_file_not_found_returns_1(
        self, mock_extract: MagicMock, mock_concat: MagicMock, mock_burn: MagicMock
    ) -> None:
        """FileNotFoundError from burn_subtitles is caught and returns 1."""
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]
        mock_burn.side_effect = FileNotFoundError("ffmpeg not found")
        edl = _minimal_edl()
        edl["subtitles"] = "subs.srt"
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl_path.write_text(json.dumps(edl), encoding="utf-8")
            # Create fake files so subs_path resolution succeeds
            (edit_dir / "subs.srt").write_text("", encoding="utf-8")
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            output_path = edit_dir / "output.mp4"
            from media_tooling.edl_render import render_edl
            result = render_edl(edl_path, output_path, no_loudnorm=True)
        self.assertEqual(result, 1)

    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_dict_subtitles_with_path_resolves_srt(
        self, mock_extract: MagicMock, mock_concat: MagicMock
    ) -> None:
        """Dict-format subtitles with 'path' key resolves the SRT file."""
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]

        def fake_concat(*a: object, **kw: object) -> None:
            pass
        mock_concat.side_effect = fake_concat

        edl = _minimal_edl()
        del edl["ranges"][0]["grade"]
        edl["subtitles"] = {"style": "bold-overlay", "path": "custom.srt"}
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl_path.write_text(json.dumps(edl), encoding="utf-8")
            # Create the SRT file so subs_path.exists() is True
            (edit_dir / "custom.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nTEST\n", encoding="utf-8")
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            output_path = edit_dir / "output.mp4"
            with patch("media_tooling.edl_render.burn_subtitles_last") as mock_burn:
                with patch("media_tooling.edl_render.apply_loudnorm_two_pass", return_value=True) as mock_loud:
                    # loudnorm needs to create the output file
                    def fake_loudnorm(inp: object, out: Path, **kw: object) -> bool:
                        out.write_bytes(b"\x00" * 100)
                        return True
                    mock_loud.side_effect = fake_loudnorm
                    from media_tooling.edl_render import render_edl
                    result = render_edl(edl_path, output_path)
            # burn_subtitles_last should have been called (dict had path)
            self.assertTrue(mock_burn.called)
            self.assertEqual(result, 0)

    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.probe_duration", return_value=5.0)
    @patch("media_tooling.edl_render.subprocess.run")
    def test_source_duration_clamps_padding(
        self, mock_run: MagicMock, mock_probe: MagicMock, mock_has_audio: MagicMock
    ) -> None:
        """apply_padding receives source_duration from ffprobe, clamps right edge."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    # End is at 4.9, pad would push to 4.93, but source_duration=5.0
                    {"source": "source1.mp4", "start": 0.0, "end": 4.9},
                ],
            }
            seg_paths = extract_all_segments(edl, edit_dir)
        # Source duration was probed once
        self.assertEqual(mock_probe.call_count, 1)
        self.assertEqual(len(seg_paths), 1)

    @patch("media_tooling.edl_render._source_has_audio", return_value=True)
    @patch("media_tooling.edl_render.probe_duration", side_effect=RuntimeError("ffprobe failed"))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_probe_failure_falls_back_to_unclamped(
        self, mock_run: MagicMock, mock_probe: MagicMock, mock_has_audio: MagicMock
    ) -> None:
        """If ffprobe fails, source_duration is inf and padding is unclamped."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl = {
                "version": 1,
                "sources": ["source1.mp4"],
                "ranges": [
                    {"source": "source1.mp4", "start": 0.0, "end": 5.0},
                ],
            }
            with patch("builtins.print"):
                seg_paths = extract_all_segments(edl, edit_dir)
        self.assertEqual(len(seg_paths), 1)

    @patch("media_tooling.edl_render.apply_loudnorm_two_pass")
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_render_edl_returns_1_when_output_missing(
        self, mock_extract: MagicMock, mock_concat: MagicMock, mock_loudnorm: MagicMock
    ) -> None:
        """render_edl returns 1 (failure) when the output file doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl_path.write_text(json.dumps(_minimal_edl()), encoding="utf-8")
            output_path = edit_dir / "missing_output.mp4"
            mock_extract.return_value = [edit_dir / "seg_00.mp4"]
            # concat creates the base file so we get past that step
            base_path = edit_dir / "base.mp4"
            def fake_concat(*a: object, **kw: object) -> None:
                base_path.write_bytes(b"\x00" * 100)
            mock_concat.side_effect = fake_concat
            # loudnorm "succeeds" but does NOT write the output file
            mock_loudnorm.return_value = True
            from media_tooling.edl_render import render_edl
            result = render_edl(
                edl_path, output_path,
                no_subtitles=True, no_loudnorm=False,
            )
        self.assertEqual(result, 1)

    @patch("media_tooling.loudnorm.apply_loudnorm_preview")
    @patch("media_tooling.edl_render.apply_loudnorm_two_pass", return_value=False)
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_loudnorm_preview_fallback_runtime_error_returns_1(
        self,
        mock_extract: MagicMock,
        mock_concat: MagicMock,
        mock_two_pass: MagicMock,
        mock_preview: MagicMock,
    ) -> None:
        """RuntimeError from loudnorm preview fallback is caught and returns 1."""
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]
        mock_preview.side_effect = RuntimeError("ffprobe crashed")

        def fake_concat(*a: object, **kw: object) -> None:
            pass
        mock_concat.side_effect = fake_concat

        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            edl_path.write_text(json.dumps(_minimal_edl()), encoding="utf-8")
            output_path = edit_dir / "output.mp4"
            from media_tooling.edl_render import render_edl
            with patch("media_tooling.edl_render.subprocess.run") as mock_run:
                # The copy-as fallback also fails
                mock_run.side_effect = subprocess.CalledProcessError(1, "ffmpeg")
                result = render_edl(
                    edl_path, output_path,
                    no_subtitles=True, no_loudnorm=False,
                )
        self.assertEqual(result, 1)

    def test_render_edl_oserror_on_read(self) -> None:
        """OSError when reading EDL file (e.g. permission denied) returns 1."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "unreadable.json"
            edl_path.write_text(json.dumps(_minimal_edl()), encoding="utf-8")
            output_path = edit_dir / "output.mp4"
            from media_tooling.edl_render import render_edl
            with patch.object(Path, "read_text", side_effect=OSError("Permission denied")):
                result = render_edl(edl_path, output_path, no_subtitles=True)
        self.assertEqual(result, 1)

    @patch("media_tooling.edl_render._probe_source_durations")
    @patch("media_tooling.edl_render.apply_loudnorm_two_pass", return_value=True)
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_shared_source_durations_prevent_divergence(
        self,
        mock_extract: MagicMock,
        mock_concat: MagicMock,
        mock_loudnorm: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """render_edl probes durations once and passes the same dict to both
        extract_all_segments and build_master_srt."""
        mock_probe.return_value = {"src.mp4": 60.0}
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]

        def fake_concat(*a: object, **kw: object) -> None:
            pass
        mock_concat.side_effect = fake_concat

        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl_path = edit_dir / "test_edl.json"
            edl = _minimal_edl()
            edl["subtitles"] = "test.srt"
            edl_path.write_text(json.dumps(edl), encoding="utf-8")
            # Create the SRT file
            srt_path = edit_dir / "test.srt"
            srt_path.write_text("1\n00:00:00,000 --> 00:00:05,000\nTEST\n", encoding="utf-8")
            output_path = edit_dir / "output.mp4"
            from media_tooling.edl_render import render_edl
            with patch("media_tooling.edl_render.burn_subtitles_last"):
                render_edl(
                    edl_path, output_path,
                    build_subtitles=True,
                )
        # _probe_source_durations called once
        self.assertEqual(mock_probe.call_count, 1)
        # extract_all_segments received source_durations kwarg
        _, kwargs = mock_extract.call_args
        self.assertIsNotNone(kwargs.get("source_durations"))


# ── Overlay validation tests ─────────────────────────────────────────────────


class ValidateOverlayTests(unittest.TestCase):
    def test_valid_source_overlay(self) -> None:
        ov = {"source": "overlay.png", "start": 5.0, "end": 10.0}
        _validate_overlay(ov, 0)  # should not raise

    def test_valid_card_text_overlay(self) -> None:
        ov = {"card": {"type": "text", "text": "Hello"}, "start": 5.0, "end": 10.0}
        _validate_overlay(ov, 0)  # should not raise

    def test_valid_card_counter_overlay(self) -> None:
        ov = {
            "card": {"type": "counter", "counter_start": 1, "counter_end": 5},
            "start": 5.0,
            "end": 10.0,
        }
        _validate_overlay(ov, 0)  # should not raise

    def test_overlay_with_position_and_z_order(self) -> None:
        ov = {
            "source": "overlay.png",
            "start": 5.0,
            "end": 10.0,
            "position": {"x": 50, "y": 100},
            "z_order": 2,
        }
        _validate_overlay(ov, 0)  # should not raise

    def test_overlay_not_dict_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay("not a dict", 0)  # type: ignore[arg-type]
        self.assertIn("must be a dict", str(ctx.exception))

    def test_overlay_missing_source_and_card_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay({"start": 5.0, "end": 10.0}, 0)
        self.assertIn("must have 'source' or 'card'", str(ctx.exception))

    def test_overlay_both_source_and_card_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "card": {"type": "text", "text": "X"},
                 "start": 5.0, "end": 10.0}, 0)
        self.assertIn("both 'source' and 'card'", str(ctx.exception))

    def test_overlay_source_not_string_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay({"source": 42, "start": 5.0, "end": 10.0}, 0)
        self.assertIn("'source' must be a string", str(ctx.exception))

    def test_overlay_card_not_dict_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay({"card": "bad", "start": 5.0, "end": 10.0}, 0)
        self.assertIn("'card' must be a dict", str(ctx.exception))

    def test_overlay_card_invalid_type_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"card": {"type": "image"}, "start": 5.0, "end": 10.0}, 0)
        self.assertIn("must be 'text' or 'counter'", str(ctx.exception))

    def test_overlay_card_text_missing_text_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"card": {"type": "text"}, "start": 5.0, "end": 10.0}, 0)
        self.assertIn("text card must have 'text' field", str(ctx.exception))

    def test_overlay_card_counter_missing_fields_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"card": {"type": "counter", "counter_start": 1},
                 "start": 5.0, "end": 10.0}, 0)
        self.assertIn("counter card must have", str(ctx.exception))

    def test_overlay_missing_start_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay({"source": "a.png", "end": 10.0}, 0)
        self.assertIn("missing required key 'start'", str(ctx.exception))

    def test_overlay_missing_end_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay({"source": "a.png", "start": 5.0}, 0)
        self.assertIn("missing required key 'end'", str(ctx.exception))

    def test_overlay_end_before_start_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay({"source": "a.png", "start": 10.0, "end": 5.0}, 0)
        self.assertIn("must be greater than", str(ctx.exception))

    def test_overlay_non_numeric_start_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay({"source": "a.png", "start": "abc", "end": 10.0}, 0)
        self.assertIn("must be numeric", str(ctx.exception))

    def test_overlay_infinite_start_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": float("inf"), "end": 10.0}, 0)
        self.assertIn("must be finite", str(ctx.exception))

    def test_overlay_position_not_dict_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": 5.0, "end": 10.0, "position": "bad"},
                0)
        self.assertIn("'position' must be a dict", str(ctx.exception))

    def test_overlay_position_non_numeric_x_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": 5.0, "end": 10.0,
                 "position": {"x": "abc", "y": 10}}, 0)
        self.assertIn("position.x must be numeric", str(ctx.exception))

    def test_overlay_z_order_non_numeric_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": 5.0, "end": 10.0, "z_order": "bad"},
                0)
        self.assertIn("'z_order' must be numeric", str(ctx.exception))

    def test_overlay_sync_duration_too_short_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": 0.0, "end": 2.0,
                 "duration_type": "sync"}, 0)
        self.assertIn("sync-to-narration duration", str(ctx.exception))

    def test_overlay_sync_duration_too_long_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": 0.0, "end": 15.0,
                 "duration_type": "sync"}, 0)
        self.assertIn("sync-to-narration duration", str(ctx.exception))

    def test_overlay_beat_duration_too_short_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": 0.0, "end": 0.3,
                 "duration_type": "beat"}, 0)
        self.assertIn("beat-synced duration", str(ctx.exception))

    def test_overlay_beat_duration_too_long_raises(self) -> None:
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(
                {"source": "a.png", "start": 0.0, "end": 3.0,
                 "duration_type": "beat"}, 0)
        self.assertIn("beat-synced duration", str(ctx.exception))

    def test_overlay_sync_valid_duration_passes(self) -> None:
        ov = {"source": "a.png", "start": 0.0, "end": 7.0, "duration_type": "sync"}
        _validate_overlay(ov, 0)  # 7s is within 3-14s

    def test_overlay_beat_valid_duration_passes(self) -> None:
        ov = {"source": "a.png", "start": 0.0, "end": 1.0, "duration_type": "beat"}
        _validate_overlay(ov, 0)  # 1s is within 0.5-2s

    def test_overlay_invalid_duration_type_raises(self) -> None:
        ov = {"source": "a.png", "start": 0.0, "end": 5.0, "duration_type": "slow"}
        with self.assertRaises(EDLSchemaError) as ctx:
            _validate_overlay(ov, 0)
        self.assertIn("must be 'sync' or 'beat'", str(ctx.exception))

    def test_overlay_none_duration_type_passes(self) -> None:
        """duration_type=None means no duration rule applies."""
        ov = {"source": "a.png", "start": 0.0, "end": 100.0}
        _validate_overlay(ov, 0)  # should not raise


class OverlayEDLValidationTests(unittest.TestCase):
    """Tests for overlay validation within validate_edl()."""

    def test_edl_with_valid_overlays_passes(self) -> None:
        edl = _minimal_edl()
        edl["overlays"] = [
            {"source": "overlay.png", "start": 5.0, "end": 10.0}
        ]
        validate_edl(edl)  # should not raise

    def test_edl_with_empty_overlays_passes(self) -> None:
        edl = _minimal_edl()
        edl["overlays"] = []
        validate_edl(edl)  # should not raise

    def test_edl_without_overlays_passes(self) -> None:
        edl = _minimal_edl()
        del edl["overlays"]
        validate_edl(edl)  # should not raise

    def test_edl_overlays_not_list_raises(self) -> None:
        edl = _minimal_edl()
        edl["overlays"] = "not a list"
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("'overlays' must be a list", str(ctx.exception))

    def test_edl_with_invalid_overlay_raises(self) -> None:
        edl = _minimal_edl()
        edl["overlays"] = [{"start": 5.0, "end": 10.0}]  # missing source/card
        with self.assertRaises(EDLSchemaError) as ctx:
            validate_edl(edl)
        self.assertIn("must have 'source' or 'card'", str(ctx.exception))


# ── Overlay filter builder tests ──────────────────────────────────────────────


class BuildOverlayFilterPartsTests(unittest.TestCase):
    def test_single_overlay_pts_shift(self) -> None:
        overlays = [{"source": "a.png", "start": 5.0, "end": 10.0}]
        parts = build_overlay_filter_parts(overlays)
        self.assertEqual(len(parts), 1)
        self.assertIn("setpts=PTS-STARTPTS+5.000/TB", parts[0])
        self.assertIn("[1:v]", parts[0])
        self.assertIn("[a1]", parts[0])

    def test_multiple_overlay_pts_shifts(self) -> None:
        overlays = [
            {"source": "a.mp4", "start": 5.0, "end": 10.0},
            {"source": "b.mp4", "start": 15.0, "end": 20.0},
        ]
        parts = build_overlay_filter_parts(overlays)
        self.assertEqual(len(parts), 2)
        self.assertIn("PTS-STARTPTS+5.000/TB", parts[0])
        self.assertIn("PTS-STARTPTS+15.000/TB", parts[1])

    def test_image_overlay_gets_fps_filter(self) -> None:
        """Image overlays need fps filter to generate continuous frames."""
        overlays = [
            {"source": "card.png", "start": 5.0, "end": 10.0,
             "_resolved_path": "/tmp/cards/overlay_card_0.png"},
        ]
        parts = build_overlay_filter_parts(overlays)
        self.assertEqual(len(parts), 1)
        self.assertIn("fps=30", parts[0])
        self.assertIn("setpts=PTS-STARTPTS+5.000/TB", parts[0])

    def test_video_overlay_no_fps_filter(self) -> None:
        """Video overlays should NOT get fps filter."""
        overlays = [
            {"source": "overlay.mp4", "start": 5.0, "end": 10.0,
             "_resolved_path": "/tmp/overlay.mp4"},
        ]
        parts = build_overlay_filter_parts(overlays)
        self.assertEqual(len(parts), 1)
        self.assertNotIn("fps=", parts[0])
        self.assertIn("setpts=PTS-STARTPTS+5.000/TB", parts[0])

    def test_custom_fps_for_image_overlay(self) -> None:
        overlays = [
            {"source": "card.png", "start": 5.0, "end": 10.0,
             "_resolved_path": "/tmp/card.png"},
        ]
        parts = build_overlay_filter_parts(overlays, base_fps=24)
        self.assertIn("fps=24", parts[0])

    def test_mixed_image_and_video_overlays(self) -> None:
        overlays = [
            {"source": "card.png", "start": 5.0, "end": 10.0,
             "_resolved_path": "/tmp/card.png"},
            {"source": "clip.mp4", "start": 15.0, "end": 20.0,
             "_resolved_path": "/tmp/clip.mp4"},
        ]
        parts = build_overlay_filter_parts(overlays)
        self.assertIn("fps=30", parts[0])  # image gets fps
        self.assertNotIn("fps=", parts[1])  # video does not

    def test_base_size_adds_scale_and_format(self) -> None:
        """When base_size is provided, overlays get scale + format filters."""
        overlays = [
            {"source": "overlay.png", "start": 5.0, "end": 10.0,
             "_resolved_path": "/tmp/overlay.png"},
        ]
        parts = build_overlay_filter_parts(overlays, base_size=(1920, 1080))
        self.assertEqual(len(parts), 1)
        self.assertIn("scale=1920:1080", parts[0])
        self.assertIn("format=yuva420p", parts[0])
        self.assertIn("fps=30", parts[0])
        self.assertIn("setpts=PTS-STARTPTS+5.000/TB", parts[0])

    def test_base_size_video_overlay_gets_scale(self) -> None:
        """Video overlays also get scale+format when base_size is set."""
        overlays = [
            {"source": "clip.mp4", "start": 5.0, "end": 10.0,
             "_resolved_path": "/tmp/clip.mp4"},
        ]
        parts = build_overlay_filter_parts(overlays, base_size=(1280, 720))
        self.assertIn("scale=1280:720", parts[0])
        self.assertIn("format=yuva420p", parts[0])
        self.assertNotIn("fps=", parts[0])  # video doesn't need fps

    def test_no_base_size_no_scale(self) -> None:
        """Without base_size, no scale or format filters are added."""
        overlays = [
            {"source": "overlay.png", "start": 5.0, "end": 10.0,
             "_resolved_path": "/tmp/overlay.png"},
        ]
        parts = build_overlay_filter_parts(overlays, base_size=None)
        self.assertNotIn("scale=", parts[0])
        self.assertNotIn("format=", parts[0])


# ── IsImagePath helper tests ──────────────────────────────────────────────────


class IsImagePathTests(unittest.TestCase):
    def test_png_is_image(self) -> None:
        self.assertTrue(_is_image_path("/tmp/overlay.png"))

    def test_jpg_is_image(self) -> None:
        self.assertTrue(_is_image_path("/tmp/photo.jpg"))

    def test_jpeg_is_image(self) -> None:
        self.assertTrue(_is_image_path("/tmp/photo.jpeg"))

    def test_webp_is_image(self) -> None:
        self.assertTrue(_is_image_path("/tmp/img.webp"))

    def test_mp4_is_not_image(self) -> None:
        self.assertFalse(_is_image_path("/tmp/clip.mp4"))

    def test_mov_is_not_image(self) -> None:
        self.assertFalse(_is_image_path("/tmp/clip.mov"))

    def test_case_insensitive(self) -> None:
        self.assertTrue(_is_image_path("/tmp/overlay.PNG"))
        self.assertTrue(_is_image_path("/tmp/overlay.Jpg"))


# ── Sorted overlay indices tests ──────────────────────────────────────────────


class SortedOverlayIndicesTests(unittest.TestCase):
    def test_sorted_by_z_order(self) -> None:
        overlays = [
            {"source": "a.png", "start": 0, "end": 5, "z_order": 2},
            {"source": "b.png", "start": 0, "end": 5, "z_order": 1},
            {"source": "c.png", "start": 0, "end": 5, "z_order": 3},
        ]
        result = _sorted_overlay_indices(overlays)
        indices = [idx for idx, _ in result]
        self.assertEqual(indices, [2, 1, 3])  # z_order 1,2,3

    def test_stable_sort_preserves_insertion_order(self) -> None:
        overlays = [
            {"source": "a.png", "start": 0, "end": 5, "z_order": 0},
            {"source": "b.png", "start": 0, "end": 5, "z_order": 0},
            {"source": "c.png", "start": 0, "end": 5, "z_order": 0},
        ]
        result = _sorted_overlay_indices(overlays)
        indices = [idx for idx, _ in result]
        self.assertEqual(indices, [1, 2, 3])  # insertion order preserved

    def test_default_z_order_is_zero(self) -> None:
        overlays = [
            {"source": "a.png", "start": 0, "end": 5},  # no z_order
            {"source": "b.png", "start": 0, "end": 5, "z_order": -1},
        ]
        result = _sorted_overlay_indices(overlays)
        indices = [idx for idx, _ in result]
        self.assertEqual(indices, [2, 1])  # -1 before 0


class BuildOverlayChainTests(unittest.TestCase):
    def test_single_overlay_chain(self) -> None:
        overlays = [
            {"source": "a.png", "start": 5.0, "end": 10.0,
             "position": {"x": 50, "y": 100}, "z_order": 0}
        ]
        parts = build_overlay_chain(overlays)
        self.assertEqual(len(parts), 1)
        self.assertIn("overlay=enable='between(t,5.000,10.000)'", parts[0])
        self.assertIn("eof_action=end", parts[0])
        self.assertIn(":x=50:y=100", parts[0])
        self.assertIn("[0:v][a1]", parts[0])
        self.assertIn("[v1]", parts[0])

    def test_z_order_sorting(self) -> None:
        overlays = [
            {"source": "a.png", "start": 5.0, "end": 10.0, "z_order": 2},
            {"source": "b.png", "start": 5.0, "end": 10.0, "z_order": 1},
        ]
        parts = build_overlay_chain(overlays)
        self.assertEqual(len(parts), 2)
        # z_order=1 (overlay index 2) should be first
        self.assertIn("[0:v][a2]", parts[0])
        self.assertIn("[v2]", parts[0])

    def test_default_position_is_zero(self) -> None:
        overlays = [
            {"source": "a.png", "start": 5.0, "end": 10.0}
        ]
        parts = build_overlay_chain(overlays)
        self.assertIn(":x=0:y=0", parts[0])

    def test_enable_between_restricts_visibility(self) -> None:
        overlays = [
            {"source": "a.png", "start": 3.5, "end": 7.25}
        ]
        parts = build_overlay_chain(overlays)
        self.assertIn("enable='between(t,3.500,7.250)'", parts[0])

    def test_eof_action_prevents_stale_last_frame(self) -> None:
        """eof_action=end prevents short video overlays from showing
        stale last frame past the overlay's natural duration."""
        overlays = [
            {"source": "short.mp4", "start": 5.0, "end": 10.0}
        ]
        parts = build_overlay_chain(overlays)
        self.assertIn("eof_action=end", parts[0])


# ── PIL overlay card generation tests ─────────────────────────────────────────


class GenerateOverlayCardTests(unittest.TestCase):
    def test_text_card_generates_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            spec = {"type": "text", "text": "Chapter 1"}
            path = generate_overlay_card(spec, out_dir, 0)
            self.assertTrue(path.exists())
            self.assertTrue(str(path).endswith(".png"))
            self.assertEqual(path.name, "overlay_card_0.png")

    def test_counter_card_generates_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            spec = {"type": "counter", "counter_start": 1, "counter_end": 5}
            path = generate_overlay_card(spec, out_dir, 1)
            self.assertTrue(path.exists())
            self.assertEqual(path.name, "overlay_card_1.png")

    def test_card_with_custom_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            spec = {
                "type": "text", "text": "Test",
                "width": 800, "height": 600, "font_size": 36,
            }
            path = generate_overlay_card(spec, out_dir, 0)
            self.assertTrue(path.exists())
            # Verify it's a valid image with the right dimensions
            from PIL import Image
            img = Image.open(path)
            self.assertEqual(img.size, (800, 600))

    def test_unknown_card_type_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir)
            spec = {"type": "unknown"}
            with self.assertRaises(ValueError) as ctx:
                generate_overlay_card(spec, out_dir, 0)
            self.assertIn("unknown card type", str(ctx.exception))


# ── Resolve overlay sources tests ─────────────────────────────────────────────


class ResolveOverlaySourcesTests(unittest.TestCase):
    def test_source_overlay_resolves_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            # Create the source file so resolution succeeds
            overlay_file = edit_dir / "overlay.png"
            overlay_file.write_bytes(b"\x00" * 10)
            overlays = [{"source": "overlay.png", "start": 5.0, "end": 10.0}]
            resolved = resolve_overlay_sources(overlays, edit_dir)
            self.assertEqual(len(resolved), 1)
            self.assertIn("_resolved_path", resolved[0])
            self.assertTrue(
                resolved[0]["_resolved_path"].endswith("overlay.png")
            )

    def test_card_overlay_generates_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            overlays = [
                {"card": {"type": "text", "text": "Hello"},
                 "start": 5.0, "end": 10.0}
            ]
            resolved = resolve_overlay_sources(overlays, edit_dir)
            self.assertEqual(len(resolved), 1)
            self.assertIn("_resolved_path", resolved[0])
            self.assertIn("overlay_card_0.png", resolved[0]["_resolved_path"])

    def test_source_overlay_does_not_modify_original(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            overlay_file = edit_dir / "overlay.png"
            overlay_file.write_bytes(b"\x00" * 10)
            overlays = [{"source": "overlay.png", "start": 5.0, "end": 10.0}]
            resolved = resolve_overlay_sources(overlays, edit_dir)
            self.assertNotIn("_resolved_path", overlays[0])
            self.assertIn("_resolved_path", resolved[0])

    def test_missing_source_file_raises(self) -> None:
        """resolve_overlay_sources raises FileNotFoundError for missing source."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            overlays = [{"source": "nonexistent.png", "start": 5.0, "end": 10.0}]
            with self.assertRaises(FileNotFoundError) as ctx:
                resolve_overlay_sources(overlays, edit_dir)
            self.assertIn("source file not found", str(ctx.exception))
            self.assertIn("nonexistent.png", str(ctx.exception))

    def test_existing_source_file_passes(self) -> None:
        """resolve_overlay_sources succeeds when source file exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            overlay_file = edit_dir / "overlay.png"
            overlay_file.write_bytes(b"\x00" * 10)
            overlays = [{"source": "overlay.png", "start": 5.0, "end": 10.0}]
            resolved = resolve_overlay_sources(overlays, edit_dir)
            self.assertEqual(len(resolved), 1)
            self.assertIn("_resolved_path", resolved[0])


# ── Build final composite tests ───────────────────────────────────────────────


class BuildFinalCompositeTests(unittest.TestCase):
    @patch("media_tooling.edl_render.probe_video_size", return_value=(1920, 1080))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_overlays_with_subtitles(self, mock_run: MagicMock, mock_probe: MagicMock) -> None:
        """build_final_composite builds filter_complex with PTS shift,
        enable-between, and subtitles last."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            srt_path = edit_dir / "test.srt"
            srt_path.write_text("1\n00:00:00,000 --> 00:00:05,000\nTEST\n",
                                encoding="utf-8")
            out_path = edit_dir / "output.mp4"
            overlays = [
                {"source": "overlay.png", "start": 5.0, "end": 10.0,
                 "position": {"x": 50, "y": 100}, "z_order": 0,
                 "_resolved_path": str(edit_dir / "overlay.png")},
            ]
            build_final_composite(
                base_path, overlays, srt_path, out_path, edit_dir
            )
        # Verify the ffmpeg command was called
        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        # Image overlay gets -loop 1
        self.assertIn("-loop 1", cmd_str)
        # Image overlay gets fps filter in filter_complex
        self.assertIn("fps=30", cmd_str)
        self.assertIn("setpts=PTS-STARTPTS+5.000/TB", cmd_str)
        self.assertIn("overlay=enable='between(t,5.000,10.000)'", cmd_str)
        self.assertIn("subtitles=", cmd_str)
        # Verify subtitles filter comes after overlay filter in the chain
        fc_idx = cmd.index("-filter_complex")
        filter_complex = cmd[fc_idx + 1]
        overlay_pos = filter_complex.find("overlay=")
        subs_pos = filter_complex.find("subtitles=")
        self.assertLess(overlay_pos, subs_pos,
                        "subtitles filter must come after overlay filter")

    @patch("media_tooling.edl_render.probe_video_size", return_value=(1920, 1080))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_overlays_without_subtitles(self, mock_run: MagicMock, mock_probe: MagicMock) -> None:
        """build_final_composite with overlays but no subtitles
        uses null filter for final output label."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            out_path = edit_dir / "output.mp4"
            overlays = [
                {"source": "overlay.png", "start": 5.0, "end": 10.0,
                 "_resolved_path": str(edit_dir / "overlay.png")},
            ]
            build_final_composite(
                base_path, overlays, None, out_path, edit_dir
            )
        self.assertTrue(mock_run.called)
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        self.assertIn("-loop 1", cmd_str)
        self.assertIn("fps=30", cmd_str)
        self.assertIn("setpts=PTS-STARTPTS", cmd_str)
        self.assertIn("overlay=enable='between(t,", cmd_str)
        self.assertNotIn("subtitles=", cmd_str)
        self.assertIn("null[outv]", cmd_str)

    @patch("media_tooling.edl_render.probe_video_size", return_value=(1280, 720))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_video_overlay_no_loop(self, mock_run: MagicMock, mock_probe: MagicMock) -> None:
        """Video overlay inputs should NOT get -loop 1."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            out_path = edit_dir / "output.mp4"
            overlays = [
                {"source": "clip.mp4", "start": 5.0, "end": 10.0,
                 "_resolved_path": str(edit_dir / "clip.mp4")},
            ]
            build_final_composite(
                base_path, overlays, None, out_path, edit_dir
            )
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        self.assertNotIn("-loop", cmd_str)
        self.assertNotIn("fps=", cmd_str)
        self.assertIn("setpts=PTS-STARTPTS", cmd_str)

    @patch("media_tooling.edl_render.probe_video_size", return_value=(1920, 1080))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_codec_matches_subtitle_path(self, mock_run: MagicMock, mock_probe: MagicMock) -> None:
        """Compositing codec settings should match burn_subtitles."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            out_path = edit_dir / "output.mp4"
            overlays = [
                {"source": "overlay.png", "start": 5.0, "end": 10.0,
                 "_resolved_path": str(edit_dir / "overlay.png")},
            ]
            build_final_composite(
                base_path, overlays, None, out_path, edit_dir
            )
        cmd = mock_run.call_args[0][0]
        # Verify codec matches burn_subtitles settings
        self.assertIn("veryfast", cmd)
        self.assertIn("20", cmd)  # CRF 20

    @patch("media_tooling.edl_render.probe_video_size", return_value=(1920, 1080))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_shortest_flag_with_loop(self, mock_run: MagicMock, mock_probe: MagicMock) -> None:
        """-shortest must be present when -loop 1 is used for image overlays."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            out_path = edit_dir / "output.mp4"
            overlays = [
                {"source": "card.png", "start": 5.0, "end": 10.0,
                 "_resolved_path": str(edit_dir / "card.png")},
            ]
            build_final_composite(
                base_path, overlays, None, out_path, edit_dir
            )
        cmd = mock_run.call_args[0][0]
        self.assertIn("-shortest", cmd)
        self.assertIn("-loop", cmd)

    @patch("media_tooling.edl_render.probe_video_size", return_value=(1920, 1080))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_scale_normalization_with_base_size(self, mock_run: MagicMock, mock_probe: MagicMock) -> None:
        """build_final_composite applies scale+format when base video dimensions are known."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            out_path = edit_dir / "output.mp4"
            overlays = [
                {"source": "overlay.png", "start": 5.0, "end": 10.0,
                 "_resolved_path": str(edit_dir / "overlay.png")},
            ]
            build_final_composite(
                base_path, overlays, None, out_path, edit_dir
            )
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        self.assertIn("scale=1920:1080", cmd_str)
        self.assertIn("format=yuva420p", cmd_str)

    @patch("media_tooling.edl_render.probe_video_size", side_effect=RuntimeError("probe failed"))
    @patch("media_tooling.edl_render.subprocess.run")
    def test_probe_failure_proceeds_without_scale(self, mock_run: MagicMock, mock_probe: MagicMock) -> None:
        """If probing base video dimensions fails, compositing proceeds
        without scale/format normalization."""
        mock_run.return_value = MagicMock(returncode=0)
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            out_path = edit_dir / "output.mp4"
            overlays = [
                {"source": "overlay.png", "start": 5.0, "end": 10.0,
                 "_resolved_path": str(edit_dir / "overlay.png")},
            ]
            build_final_composite(
                base_path, overlays, None, out_path, edit_dir
            )
        cmd = mock_run.call_args[0][0]
        cmd_str = " ".join(cmd)
        self.assertNotIn("scale=", cmd_str)
        self.assertNotIn("format=yuva420p", cmd_str)

    @patch("media_tooling.edl_render.burn_subtitles_last")
    def test_no_overlays_with_subtitles_delegates(
        self, mock_burn: MagicMock
    ) -> None:
        """build_final_composite with no overlays but subtitles
        delegates to burn_subtitles_last."""
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            srt_path = edit_dir / "test.srt"
            srt_path.write_text("1\n00:00:00,000 --> 00:00:05,000\nTEST\n",
                                encoding="utf-8")
            out_path = edit_dir / "output.mp4"
            build_final_composite(
                base_path, [], srt_path, out_path, edit_dir
            )
        self.assertTrue(mock_burn.called)

    @patch("media_tooling.edl_render._copy_to_output")
    def test_no_overlays_no_subtitles_copies(
        self, mock_copy: MagicMock
    ) -> None:
        """build_final_composite with no overlays and no subtitles
        copies base to output."""
        mock_copy.return_value = 0
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            out_path = edit_dir / "output.mp4"
            build_final_composite(base_path, [], None, out_path, edit_dir)
        self.assertTrue(mock_copy.called)


# ── Render EDL integration tests with overlays ────────────────────────────────


class RenderEDLOverlayTests(unittest.TestCase):
    @patch("media_tooling.edl_render._probe_source_durations")
    @patch("media_tooling.edl_render.apply_loudnorm_two_pass", return_value=True)
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    @patch("media_tooling.edl_render.build_final_composite")
    def test_render_edl_with_overlays_calls_build_final_composite(
        self,
        mock_composite: MagicMock,
        mock_extract: MagicMock,
        mock_concat: MagicMock,
        mock_loudnorm: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """render_edl with overlays calls build_final_composite
        instead of burn_subtitles_last."""
        mock_probe.return_value = {"source1.mp4": 60.0}
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]
        mock_concat.side_effect = lambda *a, **kw: None

        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            # Create the overlay source file so resolve_overlay_sources succeeds
            overlay_file = edit_dir / "overlay.png"
            overlay_file.write_bytes(b"\x00" * 10)
            edl_path = edit_dir / "test_edl.json"
            edl = _minimal_edl()
            edl["overlays"] = [
                {"source": "overlay.png", "start": 5.0, "end": 10.0}
            ]
            edl_path.write_text(json.dumps(edl), encoding="utf-8")
            output_path = edit_dir / "output.mp4"

            # Mock build_final_composite to write output file
            def fake_composite(*a: object, **kw: object) -> None:
                output_path.write_bytes(b"\x00" * 100)
            mock_composite.side_effect = fake_composite

            from media_tooling.edl_render import render_edl
            with patch("media_tooling.edl_render.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                render_edl(edl_path, output_path, no_subtitles=True,
                           no_loudnorm=True)

        self.assertTrue(mock_composite.called)

    @patch("media_tooling.edl_render._probe_source_durations")
    @patch("media_tooling.edl_render.apply_loudnorm_two_pass", return_value=True)
    @patch("media_tooling.edl_render.concat_segments")
    @patch("media_tooling.edl_render.extract_all_segments")
    def test_render_edl_without_overlays_uses_burn_subtitles(
        self,
        mock_extract: MagicMock,
        mock_concat: MagicMock,
        mock_loudnorm: MagicMock,
        mock_probe: MagicMock,
    ) -> None:
        """render_edl without overlays uses burn_subtitles_last
        for subtitle burning (existing path)."""
        mock_probe.return_value = {"source1.mp4": 60.0}
        mock_extract.return_value = [Path("/tmp/seg_00.mp4")]
        mock_concat.side_effect = lambda *a, **kw: None

        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            base_path = edit_dir / "base.mp4"
            base_path.write_bytes(b"\x00" * 100)
            edl_path = edit_dir / "test_edl.json"
            edl = _minimal_edl()
            del edl["overlays"]
            edl["subtitles"] = "test.srt"
            edl_path.write_text(json.dumps(edl), encoding="utf-8")
            srt_path = edit_dir / "test.srt"
            srt_path.write_text(
                "1\n00:00:00,000 --> 00:00:05,000\nTEST\n",
                encoding="utf-8",
            )
            output_path = edit_dir / "output.mp4"

            from media_tooling.edl_render import render_edl
            with patch("media_tooling.edl_render.burn_subtitles_last") as mock_burn:
                mock_burn.side_effect = lambda *a, **kw: None
                with patch("media_tooling.edl_render.subprocess.run") as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    render_edl(edl_path, output_path, no_loudnorm=True)

        self.assertTrue(mock_burn.called)


if __name__ == "__main__":
    unittest.main()
