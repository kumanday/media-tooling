from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.subtitle import (
    SUBTITLE_MAX_DURATION_SECONDS,
    build_srt,
    build_txt,
    compute_source_hash,
    elevenlabs_backend_available,
    maybe_correct_suspicious_timestamps,
    merge_tiny_adjacent_blocks,
    parse_scribe_response,
    resegment_for_subtitles,
    resolve_backend,
    resolve_model_name,
    source_matches_cache,
    transcribe_with_elevenlabs,
)


class TimestampCorrectionTests(unittest.TestCase):
    def test_applies_observed_ten_x_correction_for_mlx(self) -> None:
        segments = [
            {
                "start": 0.0,
                "end": 30.0,
                "text": "one",
                "words": [
                    {"word": "one", "start": 0.0, "end": 30.0},
                ],
            },
            {"start": 30.0, "end": 286.853, "text": "two", "words": []},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=2868.551959,
            backend="mlx",
            enabled=True,
        )

        self.assertTrue(correction["applied"])
        self.assertAlmostEqual(correction["scale_factor"], 10.000076551, places=6)
        self.assertAlmostEqual(corrected[0]["end"], 300.002, places=3)
        self.assertAlmostEqual(corrected[-1]["end"], 2868.552, places=3)
        self.assertAlmostEqual(corrected[0]["words"][0]["start"], 0.0, places=3)
        self.assertAlmostEqual(corrected[0]["words"][0]["end"], 300.002, places=3)

    def test_skips_non_mlx_backends(self) -> None:
        segments = [
            {"start": 0.0, "end": 30.0, "text": "one"},
            {"start": 30.0, "end": 286.853, "text": "two"},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=2868.551959,
            backend="faster-whisper",
            enabled=True,
        )

        self.assertFalse(correction["applied"])
        self.assertEqual(corrected, segments)

    def test_skips_ratio_close_to_one(self) -> None:
        segments = [
            {"start": 0.0, "end": 15.0, "text": "one"},
            {"start": 15.0, "end": 60.0, "text": "two"},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=60.004,
            backend="mlx",
            enabled=True,
        )

        self.assertFalse(correction["applied"])
        self.assertEqual(correction["reason"], "ratio-close-to-1")
        self.assertEqual(corrected, segments)

    def test_skips_other_integer_ratios_for_mlx(self) -> None:
        segments = [
            {"start": 0.0, "end": 10.0, "text": "one"},
            {"start": 10.0, "end": 30.0, "text": "two"},
        ]

        corrected, correction = maybe_correct_suspicious_timestamps(
            segments=segments,
            media_duration=60.0,
            backend="mlx",
            enabled=True,
        )

        self.assertFalse(correction["applied"])
        self.assertEqual(
            correction["reason"], "ratio-does-not-match-observed-mlx-compression"
        )
        self.assertEqual(corrected, segments)


class SubtitleResegmentationTests(unittest.TestCase):
    def test_resegments_long_segment_with_word_timestamps(self) -> None:
        segment = {
            "start": 0.0,
            "end": 12.0,
            "text": "Hello everyone, thanks for joining. Today we will review the workflow. Then we will discuss next steps.",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 1.0},
                {"word": " everyone,", "start": 1.0, "end": 2.0},
                {"word": " thanks", "start": 2.0, "end": 3.0},
                {"word": " for", "start": 3.0, "end": 4.0},
                {"word": " joining.", "start": 4.0, "end": 5.0},
                {"word": " Today", "start": 5.0, "end": 6.0},
                {"word": " we", "start": 6.0, "end": 7.0},
                {"word": " will", "start": 7.0, "end": 8.0},
                {"word": " review", "start": 8.0, "end": 9.0},
                {"word": " the", "start": 9.0, "end": 10.0},
                {"word": " workflow.", "start": 10.0, "end": 11.0},
                {"word": " Then", "start": 11.0, "end": 11.5},
                {"word": " we", "start": 11.5, "end": 11.75},
                {"word": " will", "start": 11.75, "end": 11.9},
                {"word": " discuss", "start": 11.9, "end": 11.95},
                {"word": " next", "start": 11.95, "end": 11.98},
                {"word": " steps.", "start": 11.98, "end": 12.0},
            ],
        }

        refined, metadata = resegment_for_subtitles([segment])

        self.assertTrue(metadata["used_word_timestamps"])
        self.assertGreater(len(refined), 1)
        self.assertTrue(
            all(
                subtitle["end"] - subtitle["start"] <= SUBTITLE_MAX_DURATION_SECONDS
                for subtitle in refined
            )
        )
        self.assertEqual(refined[0]["text"], "Hello everyone, thanks for joining.")

    def test_resegments_long_segment_without_word_timestamps(self) -> None:
        segment = {
            "start": 0.0,
            "end": 12.0,
            "text": "This is a deliberately long subtitle segment without word timestamps so it should still be split into shorter readable captions for video.",
            "words": [],
        }

        refined, metadata = resegment_for_subtitles([segment])

        self.assertFalse(metadata["used_word_timestamps"])
        self.assertGreater(len(refined), 1)
        self.assertTrue(
            all(
                subtitle["end"] - subtitle["start"] <= SUBTITLE_MAX_DURATION_SECONDS
                for subtitle in refined
            )
        )
        self.assertEqual(refined[0]["start"], 0.0)
        self.assertEqual(refined[-1]["end"], 12.0)


class BackendDispatchTests(unittest.TestCase):
    def test_whisper_resolves_like_auto(self) -> None:
        """whisper backend should resolve to same backend as auto."""
        with patch("media_tooling.subtitle.mlx_backend_available", return_value=True):
            result = resolve_backend("whisper")
            self.assertEqual(result, "mlx")

        with patch("media_tooling.subtitle.mlx_backend_available", return_value=False), \
             patch("media_tooling.subtitle.faster_whisper_available", return_value=True):
            result = resolve_backend("whisper")
            self.assertEqual(result, "faster-whisper")

    def test_auto_still_works(self) -> None:
        with patch("media_tooling.subtitle.mlx_backend_available", return_value=True):
            result = resolve_backend("auto")
            self.assertEqual(result, "mlx")

    def test_elevenlabs_requires_requests_and_key(self) -> None:
        with patch("media_tooling.subtitle.elevenlabs_backend_available", return_value=False):
            with self.assertRaises(RuntimeError) as ctx:
                resolve_backend("elevenlabs")
            self.assertIn("requests", str(ctx.exception))
            self.assertIn("ELEVENLABS_API_KEY", str(ctx.exception))

    def test_elevenlabs_available_when_requests_and_key_present(self) -> None:
        with patch("media_tooling.subtitle._requests_module", MagicMock()), \
             patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}):
            self.assertTrue(elevenlabs_backend_available())

    def test_elevenlabs_not_available_without_key(self) -> None:
        with patch("media_tooling.subtitle._requests_module", MagicMock()), \
             patch.dict(os.environ, {}, clear=True):
            # Remove ELEVENLABS_API_KEY if it exists
            os.environ.pop("ELEVENLABS_API_KEY", None)
            self.assertFalse(elevenlabs_backend_available())

    def test_elevenlabs_not_available_without_requests(self) -> None:
        with patch("media_tooling.subtitle._requests_module", None), \
             patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}):
            self.assertFalse(elevenlabs_backend_available())


class ScribeResponseParsingTests(unittest.TestCase):
    def test_parse_scribe_response_with_diarization(self) -> None:
        scribe_response = {
            "text": "Hello world",
            "language_code": "en",
            "words": [
                {"text": "Hello", "start": 0.0, "end": 1.0, "speaker_id": "speaker_0"},
                {"text": "world", "start": 1.0, "end": 2.0, "speaker_id": "speaker_0"},
            ],
            "audio_events": [
                {"text": "(laughter)", "start": 2.5, "end": 3.0, "type": "laughter"},
            ],
        }

        result = parse_scribe_response(scribe_response)

        self.assertEqual(result["language"], "en")
        self.assertEqual(result["text"], "Hello world")
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["speaker_id"], "speaker_0")
        self.assertEqual(len(result["segments"][0]["words"]), 2)
        self.assertEqual(result["segments"][0]["words"][0]["word"], "Hello")
        self.assertEqual(result["segments"][0]["words"][1]["word"], " world")
        self.assertEqual(len(result["audio_events"]), 1)
        self.assertEqual(result["audio_events"][0]["text"], "(laughter)")

    def test_parse_scribe_response_speaker_change_creates_new_segment(self) -> None:
        scribe_response = {
            "text": "Hello How are you",
            "language_code": "en",
            "words": [
                {"text": "Hello", "start": 0.0, "end": 1.0, "speaker_id": "speaker_0"},
                {"text": "How", "start": 1.5, "end": 2.0, "speaker_id": "speaker_1"},
                {"text": "are", "start": 2.0, "end": 2.5, "speaker_id": "speaker_1"},
                {"text": "you", "start": 2.5, "end": 3.0, "speaker_id": "speaker_1"},
            ],
            "audio_events": [],
        }

        result = parse_scribe_response(scribe_response)

        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["speaker_id"], "speaker_0")
        self.assertEqual(result["segments"][0]["text"], "Hello")
        self.assertEqual(result["segments"][1]["speaker_id"], "speaker_1")
        self.assertEqual(result["segments"][1]["text"], "How are you")

    def test_parse_scribe_response_empty_words(self) -> None:
        scribe_response = {
            "text": "",
            "language_code": "en",
            "words": [],
            "audio_events": [],
        }

        result = parse_scribe_response(scribe_response)

        self.assertEqual(result["language"], "en")
        self.assertEqual(result["text"], "")
        self.assertEqual(len(result["segments"]), 0)
        self.assertEqual(len(result["audio_events"]), 0)

    def test_parse_scribe_response_word_key_fallback(self) -> None:
        """Some Scribe responses use 'word' key instead of 'text'."""
        scribe_response = {
            "text": "Test",
            "words": [
                {"word": "Test", "start": 0.0, "end": 1.0, "speaker_id": "speaker_0"},
            ],
            "audio_events": [],
        }

        result = parse_scribe_response(scribe_response)
        self.assertEqual(result["segments"][0]["text"], "Test")

    def test_parse_scribe_response_none_speaker_id_inherits_previous(self) -> None:
        """Words with None speaker_id inherit from the previous segment."""
        scribe_response = {
            "text": "Hello there",
            "words": [
                {"text": "Hello", "start": 0.0, "end": 1.0, "speaker_id": "speaker_0"},
                {"text": "there", "start": 1.0, "end": 2.0, "speaker_id": None},
                {"text": "friend", "start": 2.0, "end": 3.0, "speaker_id": "speaker_1"},
            ],
            "audio_events": [],
        }
        result = parse_scribe_response(scribe_response)
        # "there" (None speaker_id) should inherit speaker_0 from "Hello",
        # producing one segment for speaker_0, then one for speaker_1.
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["speaker_id"], "speaker_0")
        self.assertEqual(result["segments"][0]["text"], "Hello there")
        self.assertEqual(result["segments"][1]["speaker_id"], "speaker_1")
        self.assertEqual(result["segments"][1]["text"], "friend")

    def test_parse_scribe_response_first_word_none_speaker_inherits_first_non_none(self) -> None:
        """First words with None speaker_id inherit from the first non-None speaker."""
        scribe_response = {
            "text": "Uh Hello there",
            "words": [
                {"text": "Uh", "start": 0.0, "end": 0.5, "speaker_id": None},
                {"text": "Hello", "start": 0.5, "end": 1.0, "speaker_id": "speaker_0"},
                {"text": "there", "start": 1.0, "end": 1.5, "speaker_id": "speaker_0"},
            ],
            "audio_events": [],
        }
        result = parse_scribe_response(scribe_response)
        # "Uh" (None speaker_id on first word) should inherit speaker_0,
        # producing a single segment rather than a tiny None-fragment.
        self.assertEqual(len(result["segments"]), 1)
        self.assertEqual(result["segments"][0]["speaker_id"], "speaker_0")
        self.assertEqual(result["segments"][0]["text"], "Uh Hello there")

    def test_parse_scribe_response_mid_stream_none_inherits_previous(self) -> None:
        """Mid-stream None speaker_ids inherit from previous segment, not first speaker."""
        scribe_response = {
            "text": "Hello yeah right",
            "words": [
                {"text": "Hello", "start": 0.0, "end": 1.0, "speaker_id": "speaker_0"},
                {"text": "yeah", "start": 1.0, "end": 2.0, "speaker_id": "speaker_1"},
                {"text": "right", "start": 2.0, "end": 3.0, "speaker_id": None},
            ],
            "audio_events": [],
        }
        result = parse_scribe_response(scribe_response)
        # "right" (None speaker_id after speaker_1) should inherit speaker_1,
        # NOT be incorrectly pre-filled with speaker_0 (the first non-None).
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(result["segments"][0]["speaker_id"], "speaker_0")
        self.assertEqual(result["segments"][0]["text"], "Hello")
        self.assertEqual(result["segments"][1]["speaker_id"], "speaker_1")
        self.assertEqual(result["segments"][1]["text"], "yeah right")

    def test_speaker_id_propagated_through_resegmentation(self) -> None:
        segment = {
            "start": 0.0,
            "end": 12.0,
            "text": "Hello everyone. Thanks for joining. Today we will discuss next steps.",
            "words": [
                {"word": "Hello", "start": 0.0, "end": 1.0},
                {"word": " everyone.", "start": 1.0, "end": 2.0},
                {"word": " Thanks", "start": 2.0, "end": 3.0},
                {"word": " for", "start": 3.0, "end": 4.0},
                {"word": " joining.", "start": 4.0, "end": 5.0},
                {"word": " Today", "start": 5.0, "end": 6.0},
                {"word": " we", "start": 6.0, "end": 7.0},
                {"word": " will", "start": 7.0, "end": 8.0},
                {"word": " discuss", "start": 8.0, "end": 9.0},
                {"word": " next", "start": 9.0, "end": 10.0},
                {"word": " steps.", "start": 10.0, "end": 12.0},
            ],
            "speaker_id": "speaker_0",
        }

        refined, metadata = resegment_for_subtitles([segment])

        self.assertTrue(metadata["used_word_timestamps"])
        for sub in refined:
            self.assertEqual(sub.get("speaker_id"), "speaker_0")

    def test_merge_tiny_blocks_never_crosses_speaker_boundary(self) -> None:
        """Adjacent tiny blocks from different speakers must NOT be merged."""
        blocks = [
            {"start": 0.0, "end": 0.3, "text": "Hi", "speaker_id": "speaker_0"},
            {"start": 0.3, "end": 0.6, "text": "Hey", "speaker_id": "speaker_1"},
            {"start": 0.6, "end": 0.9, "text": "there", "speaker_id": "speaker_1"},
        ]
        merged = merge_tiny_adjacent_blocks(blocks)
        # speaker_0's tiny block should NOT merge into speaker_1
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0].get("speaker_id"), "speaker_0")
        self.assertEqual(merged[0]["text"], "Hi")
        # speaker_1's two tiny blocks CAN merge with each other
        self.assertEqual(merged[1].get("speaker_id"), "speaker_1")


class CachingTests(unittest.TestCase):
    def test_compute_source_hash_deterministic(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as f:
            f.write(b"test audio data")
            f.flush()
            path = Path(f.name)
            hash1 = compute_source_hash(path)
            hash2 = compute_source_hash(path)
            self.assertEqual(hash1, hash2)
            os.unlink(f.name)

    def test_compute_source_hash_content_based(self) -> None:
        """Hash should be based on file content, not metadata."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.wav"
            source.write_bytes(b"audio data")
            hash1 = compute_source_hash(source)
            # Touch the file (changes mtime, not content)
            import time
            source.write_bytes(b"audio data")  # same content
            time.sleep(0.05)
            os.utime(source, (time.time() + 100, time.time() + 100))
            hash2 = compute_source_hash(source)
            self.assertEqual(hash1, hash2)

    def test_source_matches_cache_returns_true_when_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.wav"
            source.write_bytes(b"audio data")
            json_path = Path(tmpdir) / "source.json"
            source_hash = compute_source_hash(source)
            json_path.write_text(json.dumps({
                "source_hash": source_hash,
                "backend": "elevenlabs",
            }))
            self.assertTrue(source_matches_cache(json_path, source, backend="elevenlabs"))
            # Also works without backend check
            self.assertTrue(source_matches_cache(json_path, source))

    def test_source_matches_cache_returns_false_when_source_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.wav"
            source.write_bytes(b"audio data original")
            json_path = Path(tmpdir) / "source.json"
            source_hash = compute_source_hash(source)
            json_path.write_text(json.dumps({"source_hash": source_hash}))
            # Modify the source
            source.write_bytes(b"audio data modified")
            self.assertFalse(source_matches_cache(json_path, source))

    def test_source_matches_cache_returns_false_when_backend_differs(self) -> None:
        """Cache should not match if backend field differs."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.wav"
            source.write_bytes(b"audio data")
            json_path = Path(tmpdir) / "source.json"
            source_hash = compute_source_hash(source)
            json_path.write_text(json.dumps({
                "source_hash": source_hash,
                "backend": "elevenlabs",
            }))
            # Requesting whisper backend should not match elevenlabs cache
            self.assertFalse(source_matches_cache(json_path, source, backend="whisper"))

    def test_source_matches_cache_returns_true_for_legacy_no_hash(self) -> None:
        """Legacy outputs without source_hash should still honor skip-existing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.wav"
            source.write_bytes(b"audio data")
            json_path = Path(tmpdir) / "source.json"
            json_path.write_text(json.dumps({"backend": "whisper"}))
            # No source_hash → legacy fallback, return True
            self.assertTrue(source_matches_cache(json_path, source))
            # But backend mismatch still returns False
            self.assertFalse(source_matches_cache(json_path, source, backend="elevenlabs"))

    def test_source_matches_cache_works_for_whisper_with_hash(self) -> None:
        """Whisper skip_existing should work when source_hash is present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.wav"
            source.write_bytes(b"audio data")
            json_path = Path(tmpdir) / "source.json"
            source_hash = compute_source_hash(source)
            json_path.write_text(json.dumps({
                "source_hash": source_hash,
                "backend": "whisper",
            }))
            self.assertTrue(source_matches_cache(json_path, source, backend="whisper"))

    def test_source_matches_cache_returns_false_when_json_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            source = Path(tmpdir) / "source.wav"
            source.write_bytes(b"audio data")
            json_path = Path(tmpdir) / "nonexistent.json"
            self.assertFalse(source_matches_cache(json_path, source))

    def test_source_matches_cache_accepts_computed_hash(self) -> None:
        """source_matches_cache should use the pre-computed hash when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.mp4"
            src.write_bytes(b"\x00" * 64)
            json_path = Path(tmpdir) / "test.json"
            h = compute_source_hash(src)
            json_path.write_text(
                json.dumps({"backend": "whisper", "source_hash": h}),
                encoding="utf-8",
            )
            self.assertTrue(source_matches_cache(json_path, src, backend="whisper", computed_hash=h))


class ElevenLabsErrorHandlingTests(unittest.TestCase):
    def test_transcribe_with_elevenlabs_raises_without_requests(self) -> None:
        with patch("media_tooling.subtitle._requests_module", None):
            with self.assertRaises(RuntimeError) as ctx:
                transcribe_with_elevenlabs(
                    audio_path=Path("/tmp/test.wav"),
                    language=None,
                )
            self.assertIn("requests", str(ctx.exception))

    def test_transcribe_with_elevenlabs_raises_without_api_key(self) -> None:
        with patch("media_tooling.subtitle._requests_module", MagicMock()), \
             patch.dict(os.environ, {}, clear=True):
            os.environ.pop("ELEVENLABS_API_KEY", None)
            with self.assertRaises(RuntimeError) as ctx:
                transcribe_with_elevenlabs(
                    audio_path=Path("/tmp/test.wav"),
                    language=None,
                )
            self.assertIn("ELEVENLABS_API_KEY", str(ctx.exception))

    def test_transcribe_with_elevenlabs_calls_scribe_api(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "text": "Hello",
            "language_code": "en",
            "words": [
                {"text": "Hello", "start": 0.0, "end": 1.0, "speaker_id": "speaker_0"},
            ],
            "audio_events": [],
        }

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake wav data")
            wav_path = Path(f.name)

        try:
            with patch("media_tooling.subtitle._requests_module", mock_requests), \
                 patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}):
                result = transcribe_with_elevenlabs(
                    audio_path=wav_path,
                    language="en",
                )
                self.assertEqual(result["language"], "en")
                self.assertEqual(result["text"], "Hello")
                mock_requests.post.assert_called_once()
                call_kwargs = mock_requests.post.call_args
                self.assertEqual(call_kwargs.kwargs["headers"]["xi-api-key"], "test-key")
                self.assertIn("language_code", call_kwargs.kwargs["data"])
        finally:
            os.unlink(wav_path)

    def test_transcribe_with_elevenlabs_raises_on_api_error(self) -> None:
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_response

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake wav data")
            wav_path = Path(f.name)

        try:
            with patch("media_tooling.subtitle._requests_module", mock_requests), \
                 patch.dict(os.environ, {"ELEVENLABS_API_KEY": "bad-key"}):
                with self.assertRaises(RuntimeError) as ctx:
                    transcribe_with_elevenlabs(
                        audio_path=wav_path,
                        language=None,
                    )
                self.assertIn("401", str(ctx.exception))
        finally:
            os.unlink(wav_path)

    def test_transcribe_with_elevenlabs_retries_on_429(self) -> None:
        """429 rate-limit should be retried before raising."""
        mock_429 = MagicMock()
        mock_429.status_code = 429
        mock_429.text = "Rate limited"
        mock_429.headers = {}

        mock_200 = MagicMock()
        mock_200.status_code = 200
        mock_200.json.return_value = {
            "text": "Hello",
            "language_code": "en",
            "words": [
                {"text": "Hello", "start": 0.0, "end": 1.0, "speaker_id": "speaker_0"},
            ],
            "audio_events": [],
        }

        mock_requests = MagicMock()
        mock_requests.post.side_effect = [mock_429, mock_200]

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake wav data")
            wav_path = Path(f.name)

        try:
            with patch("media_tooling.subtitle._requests_module", mock_requests), \
                 patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}), \
                 patch("media_tooling.subtitle.time.sleep"):
                result = transcribe_with_elevenlabs(
                    audio_path=wav_path,
                    language=None,
                )
                self.assertEqual(result["text"], "Hello")
                self.assertEqual(mock_requests.post.call_count, 2)
        finally:
            os.unlink(wav_path)

    def test_transcribe_with_elevenlabs_retries_on_5xx_then_raises(self) -> None:
        """Persistent 5xx errors should eventually raise after retries."""
        mock_503 = MagicMock()
        mock_503.status_code = 503
        mock_503.text = "Service Unavailable"
        mock_503.headers = {}

        mock_requests = MagicMock()
        mock_requests.post.return_value = mock_503

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"fake wav data")
            wav_path = Path(f.name)

        try:
            with patch("media_tooling.subtitle._requests_module", mock_requests), \
                 patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key"}), \
                 patch("media_tooling.subtitle.time.sleep"):
                with self.assertRaises(RuntimeError) as ctx:
                    transcribe_with_elevenlabs(
                        audio_path=wav_path,
                        language=None,
                    )
                self.assertIn("503", str(ctx.exception))
                self.assertEqual(mock_requests.post.call_count, 3)
        finally:
            os.unlink(wav_path)


class SpeakerLabelOutputTests(unittest.TestCase):
    def test_build_srt_includes_speaker_id_when_present(self) -> None:
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello", "speaker_id": "speaker_0"},
            {"start": 2.0, "end": 4.0, "text": "Hi there", "speaker_id": "speaker_1"},
        ]
        srt = build_srt(segments)
        self.assertIn("[speaker_0] Hello", srt)
        self.assertIn("[speaker_1] Hi there", srt)

    def test_build_srt_omits_speaker_id_when_absent(self) -> None:
        segments = [{"start": 0.0, "end": 2.0, "text": "Hello"}]
        srt = build_srt(segments)
        self.assertIn("Hello", srt)
        self.assertNotIn("[speaker_", srt)

    def test_build_txt_includes_speaker_id_when_present(self) -> None:
        segments = [
            {"start": 0.0, "end": 2.0, "text": "Hello", "speaker_id": "speaker_0"},
        ]
        txt = build_txt(segments)
        self.assertIn("[speaker_0] Hello", txt)

    def test_build_txt_omits_speaker_id_when_absent(self) -> None:
        segments = [{"start": 0.0, "end": 2.0, "text": "Hello"}]
        txt = build_txt(segments)
        self.assertNotIn("[speaker_", txt)


class ModelNameOverrideTests(unittest.TestCase):
    """Verify that ElevenLabs runs report 'scribe_v1' as the model name."""

    def test_elevenlabs_model_name_overrides_input(self) -> None:
        """For ElevenLabs, resolve_model_name should return 'scribe_v1'."""
        self.assertEqual(resolve_model_name("elevenlabs", "small"), "scribe_v1")

    def test_whisper_model_name_unchanged(self) -> None:
        """For Whisper backends, model name should pass through unchanged."""
        self.assertEqual(resolve_model_name("whisper", "small"), "small")

    def test_mlx_model_name_unchanged(self) -> None:
        """For MLX backend, model name should pass through unchanged."""
        self.assertEqual(resolve_model_name("mlx", "large"), "large")


if __name__ == "__main__":
    unittest.main()
