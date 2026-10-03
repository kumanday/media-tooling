from __future__ import annotations

import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from media_tooling.tts import main, read_script, resolve_voice_id, synthesize_text


class TtsTests(unittest.TestCase):
    def test_main_preserves_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "narration.mp3"
            output.write_bytes(b"existing")
            with patch("media_tooling.tts.synthesize_text") as synthesize, patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(main(["missing.txt", "-o", str(output)]), 1)
                synthesize.assert_not_called()
            self.assertEqual(output.read_bytes(), b"existing")

    def test_main_never_overwrites_input_script(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "script.txt"
            source.write_text("Hello", encoding="utf-8")
            with patch("media_tooling.tts.synthesize_text") as synthesize, patch("sys.stderr", new_callable=io.StringIO):
                self.assertEqual(main([str(source), "-o", str(source), "--overwrite"]), 1)
                synthesize.assert_not_called()
            self.assertEqual(source.read_text(encoding="utf-8"), "Hello")

    def test_main_writes_generated_audio(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "script.txt"
            source.write_text("Hello", encoding="utf-8")
            output = Path(temp_dir) / "audio" / "narration.mp3"
            with patch("media_tooling.tts.synthesize_text", return_value=b"audio"), patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(main([str(source), "-o", str(output)]), 0)
            self.assertEqual(output.read_bytes(), b"audio")

    def test_main_reports_network_failure_without_request_details(self) -> None:
        requests = MagicMock()
        requests.exceptions.RequestException = OSError
        requests.post.side_effect = OSError("private request details")
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "script.txt"
            source.write_text("Hello", encoding="utf-8")
            output = Path(temp_dir) / "narration.mp3"
            with patch("media_tooling.tts._requests_module", requests), patch.dict(os.environ, {"ELEVENLABS_API_KEY": "test-key", "ELEVENLABS_VOICE_ID_EN": "test-voice"}), patch("sys.stderr", new_callable=io.StringIO) as stderr:
                self.assertEqual(main([str(source), "-o", str(output)]), 1)
                self.assertIn("Could not reach ElevenLabs", stderr.getvalue())
                self.assertNotIn("private request details", stderr.getvalue())
            self.assertFalse(output.exists())

    def test_resolve_voice_id_prefers_english_environment_value(self) -> None:
        with patch.dict(
            os.environ,
            {"ELEVENLABS_VOICE_ID_EN": "english-id", "ELEVENLABS_VOICE_ID": "generic-id"},
        ):
            self.assertEqual(resolve_voice_id(), "english-id")

    def test_read_script_flattens_srt_cues(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".srt", encoding="utf-8") as handle:
            handle.write("1\n00:00:00,000 --> 00:00:01,000\nHello\n\n2\n00:00:01,000 --> 00:00:02,000\nworld\n")
            handle.flush()
            self.assertEqual(read_script(handle.name), "Hello\nworld")

    def test_synthesize_text_calls_elevenlabs_with_env_key(self) -> None:
        response = MagicMock(ok=True, content=b"audio")
        requests = MagicMock()
        requests.post.return_value = response

        with patch("media_tooling.tts._requests_module", requests), patch.dict(
            os.environ,
            {"ELEVENLABS_API_KEY": "test-key"},
        ):
            audio = synthesize_text(
                backend="elevenlabs",
                text="Hello world",
                voice_id="voice-id",
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
                stability=0.62,
                similarity_boost=0.78,
                style=0.12,
                speed=1.0,
                use_speaker_boost=True,
            )

        self.assertEqual(audio, b"audio")
        requests.post.assert_called_once()
        call = requests.post.call_args
        self.assertEqual(call.args[0], "https://api.elevenlabs.io/v1/text-to-speech/voice-id")
        self.assertEqual(call.kwargs["headers"]["xi-api-key"], "test-key")
        self.assertEqual(call.kwargs["json"]["text"], "Hello world")

    def test_synthesize_text_requires_voice_id(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError) as context:
                synthesize_text(
                    backend="elevenlabs",
                    text="Hello",
                    voice_id=None,
                    model_id="eleven_multilingual_v2",
                    output_format="mp3_44100_128",
                    stability=0.62,
                    similarity_boost=0.78,
                    style=0.12,
                    speed=1.0,
                    use_speaker_boost=True,
                )
        self.assertIn("ELEVENLABS_VOICE_ID_EN", str(context.exception))


if __name__ == "__main__":
    unittest.main()
