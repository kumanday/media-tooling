from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from media_tooling.batch_utils import finish_batch, load_manifest_inputs


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
