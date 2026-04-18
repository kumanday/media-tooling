from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.edl_render import (
    EDLSchemaError,
    _srt_timestamp,
    _words_in_range,
    apply_padding,
    build_afade_filter,
    build_master_srt,
    concat_segments,
    extract_all_segments,
    extract_segment,
    resolve_grade_filter,
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

    def test_raw_filter_grade_passes(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["grade"] = "eq=contrast=1.1:brightness=0.05"
        validate_edl(edl)  # should not raise

    def test_auto_grade_passes(self) -> None:
        edl = _minimal_edl()
        edl["ranges"][0]["grade"] = "auto"
        validate_edl(edl)  # should not raise

    def test_sources_as_dict(self) -> None:
        edl = _minimal_edl()
        edl["sources"] = {"source1.mp4": "/path/to/source1.mp4"}
        validate_edl(edl)  # should not raise


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

    def test_unknown_simple_name_passthrough(self) -> None:
        # Unknown name without = or , is passed through as-is
        result = resolve_grade_filter("unknown_preset")
        self.assertEqual(result, "unknown_preset")


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

    def test_padding_capped_at_max_pad(self) -> None:
        start, end = apply_padding(10.0, 20.0, min_pad=0.5, max_pad=0.2)
        self.assertAlmostEqual(start, 9.8, places=2)
        self.assertAlmostEqual(end, 20.2, places=2)


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

    def test_dict_sources(self) -> None:
        edl = {"sources": {"src_a": "/absolute/path/a.mp4"}}
        result = resolve_source_path("src_a", edl, Path("/base"))
        self.assertEqual(result, Path("/absolute/path/a.mp4"))

    def test_dict_sources_relative(self) -> None:
        edl = {"sources": {"src_a": "relative/a.mp4"}}
        result = resolve_source_path("src_a", edl, Path("/base"))
        self.assertEqual(result, Path("/base/relative/a.mp4"))


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
    def test_builds_srt_with_output_timeline_offsets(self) -> None:
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
            # First word starts at 0.5 in source, offset by -0.5 → 0.0 in output
            # output_time = word.start - segment_start + segment_offset
            # For first chunk (hello, world): local_start=0.5, seg_start=0.5 → 0.0
            self.assertIn("00:00:00,000", srt_content)

    def test_multi_range_srt_offsets(self) -> None:
        """Multiple ranges accumulate correct segment offsets."""
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
            # First range: 1s duration, offset starts at 0.0
            # Second range: 1s duration, offset starts at 1.0
            # second segment words: 10.0-10.5 and 10.6-11.0
            # output_start = 10.0 - 10.0 + 1.0 = 1.0
            self.assertIn("00:00:01,000", srt_content)

    def test_missing_transcript_skips_segment(self) -> None:
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


class ExtractAllSegmentsTests(unittest.TestCase):
    @patch("media_tooling.edl_render.extract_segment")
    @patch("media_tooling.edl_render.auto_grade_for_clip")
    def test_auto_grade_per_segment(
        self, mock_auto: MagicMock, mock_extract: MagicMock
    ) -> None:
        mock_auto.return_value = ("eq=contrast=1.05", {})
        with tempfile.TemporaryDirectory() as tmpdir:
            edit_dir = Path(tmpdir)
            edl = _multi_range_edl()
            seg_paths = extract_all_segments(edl, edit_dir)
        self.assertEqual(len(seg_paths), 3)
        # Second range has grade="auto" → should call auto_grade_for_clip once
        self.assertEqual(mock_auto.call_count, 1)
        # First range has grade="subtle" → should not trigger auto
        # Third range has grade="none" → should not trigger auto

    @patch("media_tooling.edl_render.extract_segment")
    def test_preset_grade_per_segment(self, mock_extract: MagicMock) -> None:
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
        # Should call extract_segment with the preset filter
        mock_extract.assert_called_once()
        # grade_filter is the 4th positional argument (index 3)
        call_args = mock_extract.call_args
        grade_filter = call_args[0][3]
        self.assertIn("contrast=1.03", grade_filter)


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


if __name__ == "__main__":
    unittest.main()