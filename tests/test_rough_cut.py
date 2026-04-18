from __future__ import annotations

import unittest

from media_tooling.rough_cut import (
    AssemblyMethodError,
    validate_concat_demuxer_usage,
)


class ValidateConcatDemuxerUsageTests(unittest.TestCase):
    def _make_valid_concat_command(self) -> list[str]:
        """Return a valid concat demuxer command (the standard assembly approach)."""
        return [
            "ffmpeg",
            "-y",
            "-fflags", "+genpts",
            "-f", "concat",
            "-safe", "0",
            "-i", "/tmp/manifest.txt",
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "48000",
            "-ac", "2",
            "-movflags", "+faststart",
            "/tmp/output.mp4",
        ]

    def test_valid_concat_command_passes(self) -> None:
        """A standard concat demuxer command should pass validation."""
        command = self._make_valid_concat_command()
        validate_concat_demuxer_usage(command)  # should not raise

    def test_concat_with_filter_complex_raises(self) -> None:
        """Concat command with -filter_complex violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        command.extend(["-filter_complex", "[0:v][1:v]xfade=transition=fade:duration=0.5"])
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))
        self.assertIn("-filter_complex", str(ctx.exception))

    def test_concat_with_lavfi_raises(self) -> None:
        """Concat command with -lavfi violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        command.extend(["-lavfi", "concat=n=2:v=1:a=1"])
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))

    def test_concat_with_xfade_raises(self) -> None:
        """Concat command containing xfade filter violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        # Insert xfade as a flag-like arg (simulating it appearing in the command)
        command.append("xfade")
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))

    def test_concat_with_acrossfade_raises(self) -> None:
        """Concat command containing acrossfade filter violates Hard Rule 2."""
        command = self._make_valid_concat_command()
        command.append("acrossfade")
        with self.assertRaises(AssemblyMethodError) as ctx:
            validate_concat_demuxer_usage(command)
        self.assertIn("Hard Rule 2", str(ctx.exception))

    def test_non_concat_command_passes(self) -> None:
        """Commands that are not concat assembly commands should not be validated."""
        # A segment extraction command with -filter_complex is fine
        # because it's per-segment, not a concat assembly
        command = [
            "ffmpeg",
            "-y",
            "-ss", "10.0",
            "-to", "20.0",
            "-i", "/tmp/input.mp4",
            "-vf", "scale=1920:1080",
            "-c:v", "libx264",
            "/tmp/segment.mp4",
        ]
        validate_concat_demuxer_usage(command)  # should not raise

    def test_filter_complex_without_concat_passes(self) -> None:
        """-filter_complex without -f concat should not trigger validation."""
        command = [
            "ffmpeg",
            "-y",
            "-i", "/tmp/a.mp4",
            "-i", "/tmp/b.mp4",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=1",
            "/tmp/output.mp4",
        ]
        # This is NOT using the concat demuxer (-f concat), so the
        # validation doesn't apply — it's not an assembly command
        # (though it is an anti-pattern, the guardrail only validates
        # commands that claim to use the concat demuxer)
        validate_concat_demuxer_usage(command)  # should not raise

    def test_empty_command_passes(self) -> None:
        """An empty command should pass validation."""
        validate_concat_demuxer_usage([])


if __name__ == "__main__":
    unittest.main()