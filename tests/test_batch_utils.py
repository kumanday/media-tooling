from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from media_tooling.batch_utils import (
    finish_batch,
    guard_existing_output,
    load_manifest_inputs,
    record_failure,
)


class BatchUtilsTests(unittest.TestCase):
    def test_load_manifest_inputs_skips_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = root / "first.mp4"
            second = root / "second.mov"
            first.touch()
            second.touch()
            manifest = root / "inputs.txt"
            manifest.write_text(
                f"\n# comment\n{first}\n\n  {second}  \n",
                encoding="utf-8",
            )

            loaded = load_manifest_inputs(manifest)

            self.assertEqual(loaded, [first.resolve(), second.resolve()])

    def test_load_manifest_inputs_resolves_relative_paths_from_manifest_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            media_dir = root / "media"
            media_dir.mkdir()
            media_path = media_dir / "clip.mp4"
            media_path.touch()
            manifest = root / "inputs.txt"
            manifest.write_text("media/clip.mp4\n", encoding="utf-8")

            loaded = load_manifest_inputs(manifest)

            self.assertEqual(loaded, [media_path.resolve()])

    def test_record_failure_appends_and_prints(self) -> None:
        failures: list[str] = []
        stream = io.StringIO()

        with contextlib.redirect_stdout(stream):
            record_failure(failures, Path("clip.mp4"), "boom")

        self.assertEqual(failures, ["clip.mp4: boom"])
        self.assertIn("FAILED: clip.mp4", stream.getvalue())
        self.assertIn("boom", stream.getvalue())

    def test_guard_existing_output_allows_missing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            failures: list[str] = []

            should_process = guard_existing_output(
                item=root / "clip.mp4",
                output_path=root / "out.mp4",
                overwrite=False,
                skip_existing=False,
                failures=failures,
                label="render",
            )

            self.assertTrue(should_process)
            self.assertEqual(failures, [])

    def test_guard_existing_output_skip_existing_wins(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "out.mp4"
            output_path.touch()
            failures: list[str] = []
            stream = io.StringIO()

            with contextlib.redirect_stdout(stream):
                should_process = guard_existing_output(
                    item=root / "clip.mp4",
                    output_path=output_path,
                    overwrite=True,
                    skip_existing=True,
                    failures=failures,
                    label="render",
                )

            self.assertFalse(should_process)
            self.assertEqual(failures, [])
            self.assertIn("Skipping existing render", stream.getvalue())

    def test_guard_existing_output_records_conflict_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "out.mp4"
            output_path.touch()
            failures: list[str] = []

            should_process = guard_existing_output(
                item=root / "clip.mp4",
                output_path=output_path,
                overwrite=False,
                skip_existing=False,
                failures=failures,
                label="render",
            )

            self.assertFalse(should_process)
            self.assertEqual(len(failures), 1)
            self.assertIn("output exists", failures[0])

    def test_guard_existing_output_allows_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_path = root / "out.mp4"
            output_path.touch()
            failures: list[str] = []

            should_process = guard_existing_output(
                item=root / "clip.mp4",
                output_path=output_path,
                overwrite=True,
                skip_existing=False,
                failures=failures,
                label="render",
            )

            self.assertTrue(should_process)
            self.assertEqual(failures, [])

    def test_finish_batch_success(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = finish_batch([])

        self.assertEqual(result, 0)

    def test_finish_batch_failures(self) -> None:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            result = finish_batch(["x"])

        self.assertEqual(result, 1)


if __name__ == "__main__":
    unittest.main()
