import os
import tempfile
import unittest
from unittest.mock import patch

import tts_backend


class TtsBackendTests(unittest.TestCase):
    def test_openai_request_uses_wav_and_selected_voice(self):
        with tempfile.TemporaryDirectory() as folder, patch("tts_backend._post", return_value=b"RIFFaudio") as post:
            target = os.path.join(folder, "speech.wav")
            tts_backend.web_synthesize("OpenAI", "hello", "alloy", target, {"api_key": "secret"})
            with open(target, "rb") as source:
                self.assertEqual(source.read(), b"RIFFaudio")
            self.assertIn(b'"voice": "alloy"', post.call_args.args[1])
            self.assertEqual(post.call_args.args[2]["Authorization"], "Bearer secret")

    def test_fish_audio_request_uses_reference_voice(self):
        with tempfile.TemporaryDirectory() as folder, patch("tts_backend._post", return_value=b"audio") as post:
            target = os.path.join(folder, "speech.wav")
            tts_backend.web_synthesize("Fish Audio", "hello", "fish-model", target, {"api_key": "secret"})
            self.assertIn(b'"reference_id": "fish-model"', post.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
