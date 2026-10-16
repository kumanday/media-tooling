from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.video_music import main, mix_filter


def zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


class VideoMusicTests(unittest.TestCase):
    def test_generate_unpacks_separate_tracks_and_records_request(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "cut.mp4"
            video.write_bytes(b"video")
            requests = MagicMock()
            requests.post.return_value = MagicMock(ok=True, content=zip_bytes({"music.mp3": b"m", "sfx.mp3": b"s"}))
            with patch("media_tooling.tts._requests_module", requests), patch.dict(os.environ, {"ELEVENLABS_API_KEY": "k"}), \
                    patch("sys.stdout", new_callable=io.StringIO):
                code = main(["generate", str(video), "--out-dir", f"{d}/score", "--sfx", "--tag", "ambient", "--description", "quiet"])
            self.assertEqual(code, 0)
            self.assertEqual((Path(d) / "score/music.mp3").read_bytes(), b"m")
            self.assertEqual((Path(d) / "score/sfx.mp3").read_bytes(), b"s")
            form = dict(requests.post.call_args.kwargs["data"])
            self.assertEqual(form["separate_tracks"], "true")
            self.assertEqual(form["add_sfx"], "true")
            self.assertEqual(form["use_audio_as_reference"], "false")
            self.assertEqual(form["model_id"], "music_v2_5")
            rec = json.loads((Path(d) / "score/request.json").read_text())
            self.assertEqual(rec["outputs"], ["music.mp3", "sfx.mp3"])

    def test_generate_reports_api_errors(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            video = Path(d) / "cut.mp4"
            video.write_bytes(b"video")
            requests = MagicMock()
            requests.post.return_value = MagicMock(ok=False, status_code=422, text="bad video")
            with patch("media_tooling.tts._requests_module", requests), patch.dict(os.environ, {"ELEVENLABS_API_KEY": "k"}), \
                    patch("sys.stderr", new_callable=io.StringIO) as err:
                self.assertEqual(main(["generate", str(video), "--out-dir", d]), 1)
            self.assertIn("422", err.getvalue())

    def test_mix_filter_ducks_music_and_keeps_sfx_level(self) -> None:
        f = mix_filter(has_sfx=True, music_db=-10, sfx_db=-4, duck=True, lufs=-14, true_peak=-1.0)
        self.assertIn("sidechaincompress", f)
        self.assertIn("[2:a]volume=-4dB[fx]", f)
        self.assertIn("amix=inputs=3", f)
        self.assertNotIn("sidechaincompress", mix_filter(has_sfx=False, music_db=-10, sfx_db=-4, duck=False, lufs=-14, true_peak=-1.0))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_mix_writes_video_with_mixed_audio(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            run = lambda *a: subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *a], check=True)  # noqa: E731
            run("-f", "lavfi", "-i", "color=c=black:s=64x64:d=2", "-f", "lavfi", "-i", "sine=f=440:d=2", "-shortest",
                "-c:v", "libx264", "-c:a", "aac", f"{d}/v.mp4")
            run("-f", "lavfi", "-i", "sine=f=220:d=2", f"{d}/music.mp3")
            run("-f", "lavfi", "-i", "sine=f=880:d=2", f"{d}/sfx.mp3")
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main(["mix", f"{d}/v.mp4", "--music", f"{d}/music.mp3", "--sfx", f"{d}/sfx.mp3", "-o", f"{d}/out.mp4"]), 0)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", f"{d}/out.mp4"],
                                   capture_output=True, text=True, check=True).stdout.split()
            self.assertEqual(sorted(probe), ["audio", "video"])

    def test_mix_refuses_to_overwrite_input(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(main(["mix", f"{d}/v.mp4", "--music", f"{d}/m.mp3", "-o", f"{d}/v.mp4"]), 1)


if __name__ == "__main__":
    unittest.main()
