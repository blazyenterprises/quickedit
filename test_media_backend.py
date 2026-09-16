import unittest

from media_backend import MediaBackend


class MediaEncodingTests(unittest.TestCase):
    def backend(self):
        backend = object.__new__(MediaBackend)
        backend.ffmpeg = "ffmpeg.exe"
        commands = []
        backend._run = commands.append
        return backend, commands

    def test_mp3_uses_requested_rate_channels_and_bitrate(self):
        backend, commands = self.backend()
        backend.encode("source.wav", "target.mp3", 48000, 1, 24, 256)
        command = commands[0]
        self.assertIn("48000", command)
        self.assertIn("256k", command)
        self.assertIn("libmp3lame", command)

    def test_wav_uses_requested_pcm_depth(self):
        backend, commands = self.backend()
        backend.encode("source.wav", "target.wav", 96000, 2, 24, 192)
        self.assertIn("pcm_s24le", commands[0])

    def test_unknown_extension_is_delegated_to_ffmpeg(self):
        backend, commands = self.backend()
        backend.encode("source.wav", "target.xyz", 44100, 2, 16, 192)
        self.assertEqual(commands[0][-1], "target.xyz")

    def test_mix_decode_matches_open_document_format(self):
        backend, commands = self.backend()
        backend.decode_to_format("incoming.mp3", "mix.wav", 48000, 2, 3)
        command = commands[0]
        self.assertIn("48000", command)
        self.assertIn("pcm_s24le", command)


if __name__ == "__main__":
    unittest.main()
