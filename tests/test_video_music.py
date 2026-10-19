from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import statistics
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.video_music import (
    SILENCE,
    Loudness,
    bed_momentary,
    derive_music_db,
    derive_sfx_db,
    main,
    measure,
    mix,
    mix_filter,
    mix_graph,
    parse_ebur128,
    pause_frames,
    speech_frames,
    speech_level,
    under_voice,
)

EBUR128_LOG = """\
[Parsed_ebur128_0 @ 0x1] t: 0.0999792  TARGET:-23 LUFS    M:-120.7 S:-120.7     I: -70.0 LUFS       LRA:   0.0 LU
[Parsed_ebur128_0 @ 0x1] t: 0.199979   TARGET:-23 LUFS    M: -23.4 S: -25.0     I: -23.4 LUFS       LRA:   0.0 LU
[Parsed_ebur128_0 @ 0x1] t: 0.299979   TARGET:-23 LUFS    M:   nan S: -38.9     I: -23.4 LUFS       LRA:   3.7 LU
[Parsed_ebur128_0 @ 0x1] t: 0.399979   TARGET:-23 LUFS    M: -inf S: -42.0     I: -23.4 LUFS       LRA:   3.8 LU
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -25.9 LUFS
    Threshold: -36.3 LUFS

  True peak:
    Peak:       -8.0 dBFS
"""

# Narration: 100 frames speaking at -26 LUFS momentary, 20 frames of pause.
VOICE = Loudness([-26.0] * 100 + [SILENCE] * 20, -26.0)


def ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y", *args], check=True)


def synth(d: str, *, voice_amp: float = 0.05) -> tuple[Path, Path, Path]:
    """A 16 s video whose narration speaks 2.5 s in every 4 s, a pink-noise music stem and two SFX hits."""
    video, music, sfx = Path(d) / "v.mp4", Path(d) / "music.wav", Path(d) / "sfx.wav"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=16", "-f", "lavfi", "-i",
           f"aevalsrc='{voice_amp}*sin(2*PI*220*t)*(0.6+0.4*sin(2*PI*1.3*t))*lt(mod(t,4),2.5)':s=48000:d=16",
           "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video))
    ffmpeg("-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.3:seed=7:d=16", "-ac", "2", str(music))
    ffmpeg("-f", "lavfi", "-i", "aevalsrc='0.6*sin(2*PI*1000*t)*between(mod(t,8),5,5.4)':s=48000:d=16", str(sfx))
    return video, music, sfx


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

    def test_parse_ebur128_reads_momentary_and_summary(self) -> None:
        loudness = parse_ebur128(EBUR128_LOG)
        self.assertEqual(loudness.momentary, [SILENCE, -23.4, SILENCE, SILENCE])
        self.assertEqual(loudness.integrated, -25.9)
        self.assertEqual(loudness.true_peak, -8.0)
        with self.assertRaises(RuntimeError):
            parse_ebur128("no summary here")

    def test_speech_and_pause_frames_follow_narration_level(self) -> None:
        self.assertEqual(speech_frames(VOICE), list(range(100)))
        self.assertEqual(pause_frames(VOICE), list(range(100, 120)))
        self.assertEqual(speech_level(VOICE), -26.0)
        self.assertIsNone(speech_level(Loudness([SILENCE] * 10, -70.0)))

    def test_music_gain_puts_bed_20_db_under_speech(self) -> None:
        # Music at -14 LUFS while the voice sits at -26: -32 dB puts it 20 dB under.
        music = Loudness([-14.0] * 120, -14.0)
        self.assertAlmostEqual(derive_music_db(VOICE, music, under=20, min_under=12), -32.0, delta=0.11)

    def test_music_gain_respects_tenth_percentile_floor(self) -> None:
        # 30% of the speech has the music 12 dB louder; the 10th percentile floor then sets the gain.
        music = Loudness([-2.0] * 30 + [-14.0] * 90, -8.0)
        self.assertAlmostEqual(derive_music_db(VOICE, music, under=20, min_under=12), -36.0, delta=0.11)

    def test_music_gain_ignores_frames_where_the_stem_has_ended(self) -> None:
        short = Loudness([-14.0] * 60, -14.0)
        self.assertAlmostEqual(derive_music_db(VOICE, short, under=20, min_under=12), -32.0, delta=0.11)

    def test_music_gain_counts_sfx_toward_the_bed(self) -> None:
        music = Loudness([-14.0] * 120, -14.0)
        fx = Loudness([-28.0] * 70 + [SILENCE] * 50, -28.0)  # at -20 dB the SFX sit at -48 for most of the speech
        alone = derive_music_db(VOICE, music, under=20, min_under=12)
        with_fx = derive_music_db(VOICE, music, under=20, min_under=12, fx=fx, sfx_db=-20)
        self.assertLess(with_fx, alone - 3)
        margins = under_voice(VOICE, bed_momentary(music, with_fx, fx, -20), speech_frames(VOICE))
        self.assertAlmostEqual(statistics.median(margins), 20.0, delta=0.15)

    def test_music_gain_ignores_sfx_that_break_the_targets_alone(self) -> None:
        music = Loudness([-14.0] * 120, -14.0)
        fx = Loudness([-10.0] * 120, -10.0)  # at -20 dB the SFX alone sit 4 dB under the voice
        self.assertAlmostEqual(derive_music_db(VOICE, music, under=20, min_under=12, fx=fx, sfx_db=-20), -32.0,
                               delta=0.11)

    def test_bed_prediction_adds_stems_as_power(self) -> None:
        music = Loudness([-20.0, SILENCE], -20.0)
        fx = Loudness([-30.0, -30.0, -30.0], -30.0)
        bed = bed_momentary(music, -10.0, fx, 0.0)
        self.assertAlmostEqual(bed[0], -30.0 + 10 * math.log10(2), places=6)
        self.assertEqual(bed[1:], [-30.0, -30.0])

    def test_sfx_gain_puts_loudest_effect_8_db_under_speech(self) -> None:
        fx = Loudness([SILENCE, -20.0, -7.0, -15.0], -12.0)
        self.assertEqual(derive_sfx_db(VOICE, fx, under=8), -27.0)
        self.assertEqual(derive_sfx_db(VOICE, Loudness([SILENCE] * 4, -70.0), under=8), 0.0)

    def test_mix_filter_ducks_music_and_normalizes_linearly(self) -> None:
        f = mix_filter(has_sfx=True, music_db=-30, sfx_db=-17.5, duck=True, threshold=0.03, gain_db=12, limit_db=-1.5)
        self.assertIn("sidechaincompress=threshold=0.03000", f)
        self.assertIn("[2:a]volume=-17.50dB[fx]", f)
        self.assertIn("amix=inputs=3:duration=first:normalize=0[mix]", f)
        self.assertIn("[mix]volume=12.00dB,aresample=192000,alimiter=limit=0.8414:level=disabled", f)
        self.assertNotIn("loudnorm", f)
        self.assertNotIn("sidechaincompress", mix_filter(has_sfx=False, music_db=-10, sfx_db=0, duck=False,
                                                         threshold=0.03, gain_db=0, limit_db=-1))

    def test_mix_graph_renders_bed_without_voice(self) -> None:
        bed = mix_graph(has_sfx=True, music_db=-30, sfx_db=-20, duck=True, voice=False, out="a")
        self.assertNotIn("[voice]", bed)
        self.assertIn("[0:a]anull[key]", bed)
        self.assertIn("[music][fx]amix=inputs=2:duration=longest:normalize=0[a]", bed)
        self.assertTrue(mix_graph(has_sfx=False, music_db=0, sfx_db=0, duck=False, voice=False, out="a")
                        .endswith("[music]anull[a]"))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_mix_sets_bed_relative_to_narration_and_keeps_pauses(self) -> None:
        reports = []
        for amp in (0.05, 0.158):  # the second narration is 10 dB hotter
            with tempfile.TemporaryDirectory() as d:
                video, music, sfx = synth(d, voice_amp=amp)
                out = Path(d) / "out.mp4"
                report = mix(video, music, sfx, out)
                reports.append(report)
                self.assertTrue(report.music_derived and report.sfx_derived)
                assert report.bed_under is not None and report.bed_under_p10 is not None
                self.assertGreaterEqual(report.bed_under, 19.9)
                self.assertGreaterEqual(report.bed_under_p10, 11.9)
                assert report.sfx_loudest_under is not None
                self.assertAlmostEqual(report.sfx_loudest_under, 8.0, delta=0.15)
                self.assertAlmostEqual(report.output_lufs, -14.0, delta=0.15)
                self.assertLessEqual(report.output_true_peak, -1.0)
                probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0",
                                        str(out)], capture_output=True, text=True, check=True).stdout.split()
                self.assertEqual(sorted(probe), ["audio", "video"])
                self.assertFalse((Path(d) / "out.partial.mp4").exists())
                # Linear normalization: speech and pauses keep the level difference measured before the gain.
                voice = measure([video], "[0:a]anull[a]")
                final = measure([out], "[0:a]anull[a]").momentary
                speaking = statistics.median(final[i] for i in speech_frames(voice) if i < len(final))
                pausing = statistics.median(final[i] for i in pause_frames(voice) if i < len(final))
                assert report.bed_pause_under is not None
                self.assertAlmostEqual(speaking - pausing, report.bed_pause_under, delta=1.0)
        quiet, hot = reports
        self.assertAlmostEqual(hot.music_db - quiet.music_db, 10.0, delta=0.5)
        self.assertAlmostEqual(hot.sfx_db or 0.0, (quiet.sfx_db or 0.0) + 10.0, delta=0.5)
        assert quiet.bed_pause_under is not None and hot.bed_pause_under is not None
        self.assertAlmostEqual(hot.bed_pause_under, quiet.bed_pause_under, delta=0.5)

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg required")
    def test_mix_without_narration_needs_fixed_gains(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            _, music, _ = synth(d)
            ffmpeg("-f", "lavfi", "-i", "color=c=black:s=64x64:r=10:d=4", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
                   "-t", "4", "-c:v", "libx264", "-c:a", "aac", f"{d}/silent.mp4")
            with patch("sys.stderr", new_callable=io.StringIO) as err:
                self.assertEqual(main(["mix", f"{d}/silent.mp4", "--music", str(music), "-o", f"{d}/out.mp4"]), 1)
            self.assertIn("no narration", err.getvalue())
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                self.assertEqual(main(["mix", f"{d}/silent.mp4", "--music", str(music), "--music-db", "-20",
                                       "-o", f"{d}/out.mp4"]), 0)
            self.assertIn("music -20.0 dB (given)", out.getvalue())
            self.assertRegex(out.getvalue(), re.compile(r"bed under the voice while speaking: n/a"))

    def test_mix_refuses_to_overwrite_input(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            with patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(main(["mix", f"{d}/v.mp4", "--music", f"{d}/m.mp3", "-o", f"{d}/v.mp4"]), 1)


if __name__ == "__main__":
    unittest.main()
