from __future__ import annotations

import unittest
from pathlib import Path

from media_tooling.burn_subtitles import (
    build_filter_chain,
    validate_subtitles_last,
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


class BuildFilterChainTests(unittest.TestCase):
    def test_no_extras_places_subtitles_last(self) -> None:
        """Without extra filters, the chain should be just the subtitle filter."""
        chain = build_filter_chain(
            srt_path=Path("/tmp/test.srt"),
            style="bold-overlay",
            extra_filters=None,
        )
        # The subtitle filter must be the last (and only) filter
        self.assertIn("subtitles=", chain)

    def test_extras_prepended_before_subtitles(self) -> None:
        """Extra filters should be prepended, leaving subtitles last."""
        chain = build_filter_chain(
            srt_path=Path("/tmp/test.srt"),
            style="bold-overlay",
            extra_filters="scale=1920:1080,fps=30",
        )
        # The chain should start with the extra filters
        self.assertTrue(chain.startswith("scale=1920:1080,fps=30,"))
        # The subtitles filter (with force_style containing commas) should be at the end
        self.assertIn("subtitles=", chain)
        # Verify subtitles appears after the extra filters
        extra_end = chain.index("fps=30") + len("fps=30")
        subtitle_start = chain.index("subtitles=")
        self.assertGreater(subtitle_start, extra_end)

    def test_extras_with_subtitle_filter_raises(self) -> None:
        """If extras contain a subtitles filter, build_filter_chain must raise."""
        with self.assertRaises(ValueError) as ctx:
            build_filter_chain(
                srt_path=Path("/tmp/test.srt"),
                style="bold-overlay",
                extra_filters="subtitles=other.srt",
            )
        self.assertIn("Hard Rule 1", str(ctx.exception))

    def test_natural_sentence_style(self) -> None:
        """Natural-sentence style should use different force_style parameters."""
        chain = build_filter_chain(
            srt_path=Path("/tmp/test.srt"),
            style="natural-sentence",
            extra_filters=None,
        )
        self.assertIn("FontSize=22", chain)
        self.assertIn("MarginV=45", chain)

    def test_bold_overlay_style(self) -> None:
        """Bold-overlay style should use the default parameters."""
        chain = build_filter_chain(
            srt_path=Path("/tmp/test.srt"),
            style="bold-overlay",
            extra_filters=None,
        )
        self.assertIn("FontSize=28", chain)
        self.assertIn("MarginV=35", chain)

    def test_comma_in_path_is_escaped(self) -> None:
        """Commas in SRT path must be escaped to avoid breaking the filter chain."""
        chain = build_filter_chain(
            srt_path=Path("/tmp/my,file.srt"),
            style="bold-overlay",
            extra_filters=None,
        )
        self.assertIn("\\,", chain)
        self.assertNotIn("my,file", chain)  # unescaped comma must not appear


if __name__ == "__main__":
    unittest.main()
