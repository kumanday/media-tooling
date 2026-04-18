from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
from PIL import Image, ImageDraw

from media_tooling.ffprobe_utils import probe_duration
from media_tooling.timeline_view import (
    _cap_n_frames,
    _create_placeholder_frame,
    _render_filmstrip,
    _render_ruler,
    _render_waveform,
    _time_to_x,
    compute_envelope,
    compute_frame_timestamps,
    compute_layout,
    extract_frames,
    find_silences,
    generate_timeline,
    load_words,
    parse_args,
)

# ---------------------------------------------------------------------------
# compute_frame_timestamps
# ---------------------------------------------------------------------------


class TestComputeFrameTimestamps(unittest.TestCase):
    def test_single_frame_returns_midpoint(self) -> None:
        result = compute_frame_timestamps(10.0, 20.0, 1)
        self.assertEqual(result, [15.0])

    def test_two_frames_at_endpoints(self) -> None:
        result = compute_frame_timestamps(0.0, 10.0, 2)
        self.assertAlmostEqual(result[0], 0.0)
        self.assertAlmostEqual(result[1], 10.0)

    def test_ten_frames_evenly_spaced(self) -> None:
        result = compute_frame_timestamps(0.0, 9.0, 10)
        self.assertEqual(len(result), 10)
        self.assertAlmostEqual(result[0], 0.0)
        self.assertAlmostEqual(result[-1], 9.0)
        # Spacing should be 1.0
        for i in range(1, len(result)):
            self.assertAlmostEqual(result[i] - result[i - 1], 1.0, places=6)

    def test_zero_n_clamped_to_one(self) -> None:
        result = compute_frame_timestamps(5.0, 15.0, 0)
        self.assertEqual(len(result), 1)
        self.assertAlmostEqual(result[0], 10.0)

    def test_negative_n_clamped_to_one(self) -> None:
        result = compute_frame_timestamps(5.0, 15.0, -3)
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# find_silences
# ---------------------------------------------------------------------------


class TestFindSilences(unittest.TestCase):
    def test_no_words_returns_empty(self) -> None:
        gaps = find_silences([], 0.0, 5.0, threshold=0.4)
        self.assertEqual(gaps, [])

    def test_continuous_speech_no_silence(self) -> None:
        words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": " world", "start": 0.5, "end": 1.0},
        ]
        gaps = find_silences(words, 0.0, 1.0, threshold=0.4)
        self.assertEqual(gaps, [])

    def test_silence_gap_between_words(self) -> None:
        words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": " world", "start": 1.5, "end": 2.0},
        ]
        gaps = find_silences(words, 0.0, 2.0, threshold=0.4)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0][0], 0.5)
        self.assertAlmostEqual(gaps[0][1], 1.5)

    def test_gap_below_threshold_ignored(self) -> None:
        words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
            {"word": " world", "start": 0.8, "end": 1.3},
        ]
        gaps = find_silences(words, 0.0, 1.3, threshold=0.4)
        self.assertEqual(gaps, [])

    def test_trailing_silence(self) -> None:
        words = [
            {"word": "hello", "start": 0.0, "end": 0.5},
        ]
        gaps = find_silences(words, 0.0, 3.0, threshold=0.4)
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0][0], 0.5)
        self.assertAlmostEqual(gaps[0][1], 3.0)

    def test_default_threshold_is_400ms(self) -> None:
        words = [
            {"word": "a", "start": 0.0, "end": 0.2},
            {"word": " b", "start": 0.8, "end": 1.0},  # gap = 0.6
        ]
        gaps = find_silences(words, 0.0, 1.0)
        self.assertEqual(len(gaps), 1)  # 0.6 >= 0.4 threshold

    def test_gap_just_under_default_threshold(self) -> None:
        words = [
            {"word": "a", "start": 0.0, "end": 0.3},
            {"word": " b", "start": 0.699, "end": 1.0},  # gap = 0.399
        ]
        gaps = find_silences(words, 0.0, 1.0)
        self.assertEqual(gaps, [])  # 0.399 < 0.4

    def test_out_of_order_words_produces_correct_gaps(self) -> None:
        words = [
            {"word": "second", "start": 2.0, "end": 2.5},
            {"word": "first", "start": 0.0, "end": 0.5},
        ]
        gaps = find_silences(words, 0.0, 2.5, threshold=0.4)
        # Between the two words (0.5 → 2.0) is a 1.5s gap; no trailing silence
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0][0], 0.5)
        self.assertAlmostEqual(gaps[0][1], 2.0)


# ---------------------------------------------------------------------------
# load_words
# ---------------------------------------------------------------------------


class TestLoadWords(unittest.TestCase):
    def test_none_path_returns_empty(self) -> None:
        self.assertEqual(load_words(None, 0.0, 10.0), [])

    def test_nonexistent_path_returns_empty(self) -> None:
        self.assertEqual(load_words(Path("/nonexistent/file.json"), 0.0, 10.0), [])

    def test_flat_words_format(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "words": [
                    {"word": "hello", "start": 0.0, "end": 0.5},
                    {"word": " world", "start": 0.5, "end": 1.0},
                    {"word": " outside", "start": 20.0, "end": 20.5},
                ],
            }, f)
            path = Path(f.name)

        result = load_words(path, 0.0, 5.0)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["word"], "hello")

    def test_segmented_format(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({
                "segments": [
                    {
                        "start": 0.0,
                        "end": 1.0,
                        "text": "hello world",
                        "words": [
                            {"word": "hello", "start": 0.0, "end": 0.5},
                            {"word": " world", "start": 0.5, "end": 1.0},
                        ],
                    },
                    {
                        "start": 5.0,
                        "end": 6.0,
                        "text": "test",
                        "words": [
                            {"word": " test", "start": 5.0, "end": 6.0},
                        ],
                    },
                ],
            }, f)
            path = Path(f.name)

        result = load_words(path, 0.0, 3.0)
        self.assertEqual(len(result), 2)

    def test_empty_json_returns_empty(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({}, f)
            path = Path(f.name)
        self.assertEqual(load_words(path, 0.0, 10.0), [])


# ---------------------------------------------------------------------------
# parse_args
# ---------------------------------------------------------------------------


class TestParseArgs(unittest.TestCase):
    def test_basic_invocation(self) -> None:
        args = parse_args(["video.mp4", "-o", "out.png"])
        self.assertEqual(args.input, "video.mp4")
        self.assertEqual(args.output, "out.png")
        self.assertEqual(args.start, 0.0)
        self.assertIsNone(args.end)

    def test_start_end_flags(self) -> None:
        args = parse_args(["video.mp4", "--start", "30", "--end", "60"])
        self.assertEqual(args.start, 30.0)
        self.assertEqual(args.end, 60.0)

    def test_transcript_flag(self) -> None:
        args = parse_args(["video.mp4", "--transcript", "words.json"])
        self.assertEqual(args.transcript, "words.json")

    def test_n_frames_default(self) -> None:
        args = parse_args(["video.mp4"])
        self.assertEqual(args.n_frames, 10)


# ---------------------------------------------------------------------------
# compute_layout
# ---------------------------------------------------------------------------


class TestComputeLayout(unittest.TestCase):
    def test_returns_expected_keys(self) -> None:
        layout = compute_layout()
        for key in ("filmstrip_y", "frame_height", "wave_y", "waveform_height",
                     "ruler_y", "label_y", "canvas_height"):
            self.assertIn(key, layout)

    def test_canvas_height_is_positive(self) -> None:
        layout = compute_layout()
        self.assertGreater(layout["canvas_height"], 0)

    def test_wave_y_is_below_filmstrip(self) -> None:
        layout = compute_layout()
        self.assertGreater(layout["wave_y"], layout["filmstrip_y"] + layout["frame_height"])


# ---------------------------------------------------------------------------
# compute_envelope (mocked ffmpeg)
# ---------------------------------------------------------------------------


class TestComputeEnvelope(unittest.TestCase):
    @patch("media_tooling.timeline_view.subprocess.run")
    def test_returns_zeros_when_ffmpeg_fails(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1)
        result = compute_envelope(Path("test.mp4"), 0.0, 10.0, "ffmpeg")
        self.assertEqual(result.shape[0], 2000)
        self.assertTrue(np.all(result == 0))


class TestWindowedRms(unittest.TestCase):
    def test_constant_signal_envelope_is_one(self) -> None:
        from media_tooling.timeline_view import _windowed_rms
        signal = np.ones(16000, dtype=np.float32)  # 1 second of constant audio
        env = _windowed_rms(signal, 100)
        self.assertEqual(env.shape, (100,))
        self.assertTrue(np.all(env > 0))

    def test_silence_envelope_is_zero(self) -> None:
        from media_tooling.timeline_view import _windowed_rms
        signal = np.zeros(16000, dtype=np.float32)
        env = _windowed_rms(signal, 100)
        self.assertTrue(np.all(env == 0))


# ---------------------------------------------------------------------------
# probe_duration (mocked ffprobe)
# ---------------------------------------------------------------------------


class TestProbeDuration(unittest.TestCase):
    @patch("media_tooling.ffprobe_utils.subprocess.run")
    def test_extracts_duration(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format": {"duration": "120.5"}}',
        )
        dur = probe_duration(Path("test.mp4"), "ffprobe")
        self.assertAlmostEqual(dur, 120.5)

    @patch("media_tooling.ffprobe_utils.subprocess.run")
    def test_raises_on_ffprobe_failure(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(returncode=1, stderr="error")
        with self.assertRaises(RuntimeError):
            probe_duration(Path("missing.mp4"), "ffprobe")

    @patch("media_tooling.ffprobe_utils.subprocess.run")
    def test_raises_when_duration_missing(self, mock_run: MagicMock) -> None:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='{"format": {}}',
        )
        with self.assertRaises(RuntimeError):
            probe_duration(Path("test.mp4"), "ffprobe")


# ---------------------------------------------------------------------------
# Output dimensions (integration-style test with mocked ffmpeg/ffprobe)
# ---------------------------------------------------------------------------


class TestOutputDimensions(unittest.TestCase):
    @patch("media_tooling.timeline_view.probe_duration", return_value=60.0)
    @patch("media_tooling.timeline_view.extract_frames")
    @patch("media_tooling.timeline_view.compute_envelope")
    def test_output_png_dimensions(
        self,
        mock_env: MagicMock,
        mock_frames: MagicMock,
        mock_dur: MagicMock,
    ) -> None:
        # Create dummy frame images
        with tempfile.TemporaryDirectory() as tmp:
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(3):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)
            mock_frames.return_value = frame_paths
            mock_env.return_value = np.zeros(2000, dtype=np.float32)

            out_path = Path(tmp) / "output.png"
            generate_timeline(
                input_path=Path("test.mp4"),
                output_path=out_path,
                start=0.0,
                end=60.0,
                n_frames=3,
                transcript_path=None,
                ffmpeg_bin="ffmpeg",
            )

            self.assertTrue(out_path.exists())
            with Image.open(str(out_path)) as result:
                self.assertGreaterEqual(result.width, 1920)
                self.assertGreater(result.height, 0)

    @patch("media_tooling.timeline_view.probe_duration", return_value=60.0)
    @patch("media_tooling.timeline_view.compute_envelope")
    @patch("media_tooling.timeline_view.subprocess.run")
    def test_placeholder_frame_loading_through_generate_timeline(
        self,
        mock_run: MagicMock,
        mock_env: MagicMock,
        mock_dur: MagicMock,
    ) -> None:
        """Exercise frame-loading-to-canvas pipeline via placeholder frames (ffmpeg-failure path)."""
        mock_run.return_value = MagicMock(returncode=1)
        mock_env.return_value = np.zeros(2000, dtype=np.float32)

        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "output.png"
            generate_timeline(
                input_path=Path("test.mp4"),
                output_path=out_path,
                start=0.0,
                end=60.0,
                n_frames=3,
                transcript_path=None,
                ffmpeg_bin="ffmpeg",
            )

            self.assertTrue(out_path.exists())
            with Image.open(str(out_path)) as result:
                self.assertGreaterEqual(result.width, 1920)


# ---------------------------------------------------------------------------
# _time_to_x helper
# ---------------------------------------------------------------------------


class TestTimeToX(unittest.TestCase):
    def test_start_maps_to_x0(self) -> None:
        self.assertEqual(_time_to_x(0.0, 0.0, 60.0, 50, 1820), 50)

    def test_end_maps_to_x0_plus_span(self) -> None:
        self.assertEqual(_time_to_x(60.0, 0.0, 60.0, 50, 1820), 50 + 1820)

    def test_midpoint(self) -> None:
        result = _time_to_x(30.0, 0.0, 60.0, 50, 1820)
        self.assertAlmostEqual(result, 50 + 910, delta=1)


# ---------------------------------------------------------------------------
# _render_filmstrip
# ---------------------------------------------------------------------------


class TestRenderFilmstrip(unittest.TestCase):
    def test_returns_strip_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(3):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)

            canvas = Image.new("RGB", (1920, 600), (0, 0, 0))
            layout = compute_layout()
            x1, span = _render_filmstrip(canvas, frame_paths, 3, layout, 50, 1820)
            self.assertGreater(x1, 50)
            self.assertGreater(span, 0)

    def test_many_frames_do_not_overflow_strip(self) -> None:
        """Filmstrip with many frames must stay within strip_width bounds."""
        with tempfile.TemporaryDirectory() as tmp:
            n = 20
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(n):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)

            canvas = Image.new("RGB", (1920, 600), (0, 0, 0))
            layout = compute_layout()
            strip_x0 = 50
            strip_width = 1820
            x1, span = _render_filmstrip(canvas, frame_paths, n, layout, strip_x0, strip_width)
            self.assertLessEqual(x1, strip_x0 + strip_width, "filmstrip overflows strip_width")

    def test_extreme_n_frames_capped_and_fits_canvas(self) -> None:
        """With very large n_frames, frames are capped and strip fits within canvas."""
        with tempfile.TemporaryDirectory() as tmp:
            strip_width = 1820
            capped = _cap_n_frames(500, strip_width)
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(capped):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)

            canvas = Image.new("RGB", (1920, 600), (0, 0, 0))
            layout = compute_layout()
            strip_x0 = 50
            x1, span = _render_filmstrip(canvas, frame_paths, capped, layout, strip_x0, strip_width)
            self.assertGreater(span, 0)
            self.assertLessEqual(x1, 1920, "capped filmstrip must not overflow canvas")


# ---------------------------------------------------------------------------
# _cap_n_frames
# ---------------------------------------------------------------------------


class TestCapNFrames(unittest.TestCase):
    def test_normal_value_unchanged(self) -> None:
        self.assertEqual(_cap_n_frames(10, 1820), 10)

    def test_extreme_value_capped(self) -> None:
        self.assertLess(_cap_n_frames(500, 1820), 500)
        self.assertGreater(_cap_n_frames(500, 1820), 0)

    def test_zero_passed_through(self) -> None:
        # Zero/negative is guarded by max(1, n_frames) in generate_timeline
        self.assertEqual(_cap_n_frames(0, 1820), 0)

    def test_negative_passed_through(self) -> None:
        self.assertEqual(_cap_n_frames(-5, 1820), -5)

    def test_cap_produces_readable_frame_width(self) -> None:
        strip_width = 1820
        gap = 4
        for n in [10, 50, 100, 200, 500]:
            capped = _cap_n_frames(n, strip_width)
            frame_w = (strip_width - (capped - 1) * gap) // capped
            self.assertGreaterEqual(frame_w, 10, f"frame_w too small for n={n}, capped={capped}")


# ---------------------------------------------------------------------------
# _render_ruler
# ---------------------------------------------------------------------------


class TestRenderRuler(unittest.TestCase):
    def test_ruler_draws_without_error(self) -> None:
        canvas = Image.new("RGB", (1920, 600), (0, 0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        layout = compute_layout()
        from media_tooling.timeline_view import load_font
        label_font = load_font(14)
        _render_ruler(draw, layout, 0.0, 60.0, 50, 1820, label_font, [])


# ---------------------------------------------------------------------------
# _render_waveform
# ---------------------------------------------------------------------------


class TestRenderWaveform(unittest.TestCase):
    def test_waveform_draws_without_error(self) -> None:
        canvas = Image.new("RGB", (1920, 600), (0, 0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        layout = compute_layout()
        from media_tooling.timeline_view import load_font
        small_font = load_font(12)
        env = np.zeros(2000, dtype=np.float32)
        _render_waveform(
            draw, env, layout, 50, 1870, [], [], 0.0, 60.0, small_font,
        )

    def test_waveform_with_silence_and_words(self) -> None:
        canvas = Image.new("RGB", (1920, 600), (0, 0, 0))
        draw = ImageDraw.Draw(canvas, "RGBA")
        layout = compute_layout()
        from media_tooling.timeline_view import load_font
        small_font = load_font(12)
        env = np.zeros(2000, dtype=np.float32)
        silences = [(5.0, 10.0)]
        words = [{"word": "hello", "start": 0.0, "end": 1.0}]
        _render_waveform(
            draw, env, layout, 50, 1870, silences, words, 0.0, 60.0, small_font,
        )


# ---------------------------------------------------------------------------
# n_frames edge case
# ---------------------------------------------------------------------------


class TestNFramesZero(unittest.TestCase):
    @patch("media_tooling.timeline_view.probe_duration", return_value=60.0)
    @patch("media_tooling.timeline_view.extract_frames")
    @patch("media_tooling.timeline_view.compute_envelope")
    def test_n_frames_zero_does_not_crash(
        self,
        mock_env: MagicMock,
        mock_frames: MagicMock,
        mock_dur: MagicMock,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            fp = frame_dir / "f_000.jpg"
            img = Image.new("RGB", (320, 180), (40, 40, 44))
            img.save(str(fp), "JPEG")
            mock_frames.return_value = [fp]
            mock_env.return_value = np.zeros(2000, dtype=np.float32)

            out_path = Path(tmp) / "output.png"
            generate_timeline(
                input_path=Path("test.mp4"),
                output_path=out_path,
                start=0.0,
                end=60.0,
                n_frames=0,
                transcript_path=None,
                ffmpeg_bin="ffmpeg",
            )

            self.assertTrue(out_path.exists())


class TestNFramesCapAlignment(unittest.TestCase):
    @patch("media_tooling.timeline_view.probe_duration", return_value=60.0)
    @patch("media_tooling.timeline_view.extract_frames")
    @patch("media_tooling.timeline_view.compute_envelope")
    def test_extreme_n_frames_filmstrip_covers_full_range(
        self,
        mock_env: MagicMock,
        mock_frames: MagicMock,
        mock_dur: MagicMock,
    ) -> None:
        """When --n-frames exceeds max_n, cap is applied before extraction so
        the filmstrip still covers the full time range and stays aligned with
        the waveform/ruler."""
        with tempfile.TemporaryDirectory() as tmp:
            strip_width = 1820
            capped = _cap_n_frames(500, strip_width)

            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(capped):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)
            mock_frames.return_value = frame_paths
            mock_env.return_value = np.zeros(2000, dtype=np.float32)

            out_path = Path(tmp) / "output.png"
            generate_timeline(
                input_path=Path("test.mp4"),
                output_path=out_path,
                start=0.0,
                end=60.0,
                n_frames=500,
                transcript_path=None,
                ffmpeg_bin="ffmpeg",
            )

            self.assertTrue(out_path.exists())
            with Image.open(str(out_path)) as result:
                # Filmstrip should span most of the canvas width
                # (not just a tiny fraction because n_frames was huge)
                layout = compute_layout()
                filmstrip_y = layout["filmstrip_y"] + layout["frame_height"] // 2
                # Check that frames exist at both left and right ends of the strip
                left_pixel = result.getpixel((55, filmstrip_y))
                right_pixel = result.getpixel((1850, filmstrip_y))
                # Both should be the placeholder grey, not the background
                bg = (18, 18, 22)
                assert isinstance(left_pixel, tuple)
                assert isinstance(right_pixel, tuple)
                self.assertNotEqual(left_pixel[:3], bg, "Left end of filmstrip should have frame content")
                self.assertNotEqual(right_pixel[:3], bg, "Right end of filmstrip should have frame content")


# ---------------------------------------------------------------------------
# extract_frames / _create_placeholder_frame
# ---------------------------------------------------------------------------


class TestExtractFrames(unittest.TestCase):
    @patch("media_tooling.timeline_view.subprocess.run")
    def test_ffmpeg_failure_produces_placeholder(self, mock_run: MagicMock) -> None:
        """When ffmpeg fails, extract_frames should produce a placeholder frame."""
        mock_run.return_value = MagicMock(returncode=1)
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "frames"
            paths = extract_frames(Path("test.mp4"), [0.0, 5.0], "ffmpeg", dest)
            self.assertEqual(len(paths), 2)
            for p in paths:
                self.assertTrue(p.exists())
                with Image.open(str(p)) as img:
                    self.assertEqual(img.size, (320, 180))

    @patch("media_tooling.timeline_view.subprocess.run")
    def test_ffmpeg_success_returns_extracted_frames(self, mock_run: MagicMock) -> None:
        """When ffmpeg succeeds, the extracted frame file is returned."""
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "frames"
            dest.mkdir(parents=True)
            # Pre-create a frame file so the "exists" check passes
            fake_frame = dest / "f_000.jpg"
            Image.new("RGB", (320, 180), (100, 100, 100)).save(str(fake_frame), "JPEG")

            mock_run.return_value = MagicMock(returncode=0)
            paths = extract_frames(Path("test.mp4"), [0.0], "ffmpeg", dest)
            self.assertEqual(len(paths), 1)
            self.assertTrue(paths[0].exists())


class TestCreatePlaceholderFrame(unittest.TestCase):
    def test_creates_jpeg_of_requested_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "placeholder.jpg"
            _create_placeholder_frame(path, 320, 180)
            self.assertTrue(path.exists())
            with Image.open(str(path)) as img:
                self.assertEqual(img.size, (320, 180))
                self.assertEqual(img.mode, "RGB")

    def test_grey_fill_colour(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "placeholder.jpg"
            _create_placeholder_frame(path, 64, 64)
            with Image.open(str(path)) as img:
                px = img.getpixel((0, 0))
                assert isinstance(px, tuple)
                # JPEG compression may shift values slightly; check within tolerance
                self.assertAlmostEqual(px[0], 40, delta=5)
                self.assertAlmostEqual(px[1], 40, delta=5)
                self.assertAlmostEqual(px[2], 44, delta=5)


# ---------------------------------------------------------------------------
# Transcript / silence rendering integration
# ---------------------------------------------------------------------------


class TestTranscriptRendering(unittest.TestCase):
    @patch("media_tooling.timeline_view.probe_duration", return_value=10.0)
    @patch("media_tooling.timeline_view.extract_frames")
    @patch("media_tooling.timeline_view.compute_envelope")
    def test_transcript_produces_silence_shading(
        self,
        mock_env: MagicMock,
        mock_frames: MagicMock,
        mock_dur: MagicMock,
    ) -> None:
        """Verify that silence gaps from a transcript produce visible shading."""
        with tempfile.TemporaryDirectory() as tmp:
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(3):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)
            mock_frames.return_value = frame_paths
            mock_env.return_value = np.zeros(2000, dtype=np.float32)

            # Create a transcript JSON with a silence gap 3.0→7.0 (4s gap ≥ 400ms)
            transcript = {
                "words": [
                    {"word": "hello", "start": 0.0, "end": 1.0},
                    {"word": " world", "start": 1.0, "end": 3.0},
                    {"word": " again", "start": 7.0, "end": 10.0},
                ],
            }
            transcript_path = Path(tmp) / "transcript.json"
            transcript_path.write_text(json.dumps(transcript))

            out_path = Path(tmp) / "output.png"
            generate_timeline(
                input_path=Path("test.mp4"),
                output_path=out_path,
                start=0.0,
                end=10.0,
                n_frames=3,
                transcript_path=transcript_path,
                ffmpeg_bin="ffmpeg",
            )

            self.assertTrue(out_path.exists())
            with Image.open(str(out_path)) as result:
                layout = compute_layout()
                wave_y = layout["wave_y"]
                strip_x0 = 50
                strip_span = 1920 - 100

                # Sample OFF the midline (where the zero-envelope waveform line sits)
                # to avoid the waveform line dominating the pixel colour.
                sample_y = wave_y + 20

                # Sample pixel in the silence region (mid-gap around t=5.0)
                silence_x = _time_to_x(5.0, 0.0, 10.0, strip_x0, strip_span)
                silence_pixel = result.getpixel((silence_x, sample_y))
                assert isinstance(silence_pixel, tuple)

                # Sample pixel in the speech region (around t=1.5)
                speech_x = _time_to_x(1.5, 0.0, 10.0, strip_x0, strip_span)
                speech_pixel = result.getpixel((speech_x, sample_y))
                assert isinstance(speech_pixel, tuple)

                # Silence region should have a visible tint (blue-ish overlay)
                # The silence fill is RGBA (50,80,120,120) on top of (28,28,34).
                # After alpha compositing, the blue channel is noticeably higher.
                self.assertGreater(silence_pixel[2], speech_pixel[2],
                                   "Silence region should have more blue than speech region")

    @patch("media_tooling.timeline_view.probe_duration", return_value=10.0)
    @patch("media_tooling.timeline_view.extract_frames")
    @patch("media_tooling.timeline_view.compute_envelope")
    def test_no_transcript_no_silence_legend(
        self,
        mock_env: MagicMock,
        mock_frames: MagicMock,
        mock_dur: MagicMock,
    ) -> None:
        """Without a transcript, the silence legend should not appear."""
        with tempfile.TemporaryDirectory() as tmp:
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(3):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)
            mock_frames.return_value = frame_paths
            mock_env.return_value = np.zeros(2000, dtype=np.float32)

            out_path = Path(tmp) / "output.png"
            generate_timeline(
                input_path=Path("test.mp4"),
                output_path=out_path,
                start=0.0,
                end=10.0,
                n_frames=3,
                transcript_path=None,
                ffmpeg_bin="ffmpeg",
            )

            self.assertTrue(out_path.exists())
            # Verify silence legend is absent: pixel at legend position matches background
            with Image.open(str(out_path)) as result:
                label_y = compute_layout()["label_y"]
                legend_pixel = result.getpixel((50, label_y))
                # BG colour is (18, 18, 22) — no legend text should be drawn
                assert isinstance(legend_pixel, tuple)
                self.assertEqual(legend_pixel[:3], (18, 18, 22), "Silence legend should not appear without transcript")

    @patch("media_tooling.timeline_view.probe_duration", return_value=10.0)
    @patch("media_tooling.timeline_view.extract_frames")
    @patch("media_tooling.timeline_view.compute_envelope")
    def test_string_timestamps_handled_gracefully(
        self,
        mock_env: MagicMock,
        mock_frames: MagicMock,
        mock_dur: MagicMock,
    ) -> None:
        """Word labels with string-valued timestamps should be cast to float."""
        with tempfile.TemporaryDirectory() as tmp:
            frame_dir = Path(tmp) / "frames"
            frame_dir.mkdir()
            frame_paths: list[Path] = []
            for i in range(3):
                fp = frame_dir / f"f_{i:03d}.jpg"
                img = Image.new("RGB", (320, 180), (40, 40, 44))
                img.save(str(fp), "JPEG")
                frame_paths.append(fp)
            mock_frames.return_value = frame_paths
            mock_env.return_value = np.zeros(2000, dtype=np.float32)

            transcript = {
                "words": [
                    {"word": "hello", "start": "0.0", "end": "1.0"},
                    {"word": " world", "start": "1.0", "end": "3.0"},
                ],
            }
            transcript_path = Path(tmp) / "transcript.json"
            transcript_path.write_text(json.dumps(transcript))

            out_path = Path(tmp) / "output.png"
            # Should not raise TypeError from string timestamp arithmetic
            generate_timeline(
                input_path=Path("test.mp4"),
                output_path=out_path,
                start=0.0,
                end=10.0,
                n_frames=3,
                transcript_path=transcript_path,
                ffmpeg_bin="ffmpeg",
            )

            self.assertTrue(out_path.exists())


if __name__ == "__main__":
    unittest.main()
