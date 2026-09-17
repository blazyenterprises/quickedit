import unittest
from types import SimpleNamespace
from unittest.mock import patch

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

    def test_encode_writes_metadata(self):
        backend, commands = self.backend()
        backend.encode("source.wav", "target.flac", metadata={"title": "Example", "artist": "Someone"})
        command = commands[0]
        self.assertIn("title=Example", command)
        self.assertIn("artist=Someone", command)

    def test_read_metadata_normalizes_probe_keys(self):
        backend = object.__new__(MediaBackend)
        backend.ffprobe = "ffprobe.exe"
        backend._run = lambda command: SimpleNamespace(stdout='{"format":{"tags":{"TITLE":"Example","Artist":"Someone"}}}')
        self.assertEqual(backend.read_metadata("song.mp3"), {"title": "Example", "artist": "Someone"})

    @patch("media_backend.subprocess.Popen")
    def test_streaming_playback_enables_rolling_cache(self, popen):
        backend = object.__new__(MediaBackend)
        backend.mpv = "mpv.exe"
        process = SimpleNamespace()
        popen.return_value = process
        backend.start_playback("https://radio.example/stream", streaming=True)
        command = popen.call_args.args[0]
        self.assertIn("--cache=yes", command)
        self.assertIn("--cache-secs=1800", command)
        self.assertTrue(process.quickedit_ipc_path.startswith(r"\\.\pipe\quickedit-mpv-"))

    @patch("media_backend.subprocess.Popen")
    def test_normal_speed_bypasses_pitch_correction_filter(self, popen):
        backend = object.__new__(MediaBackend)
        backend.mpv = "mpv.exe"
        popen.return_value = SimpleNamespace()
        backend.start_playback("imported.wav")
        self.assertIn("--speed=1", popen.call_args.args[0])
        self.assertIn("--audio-pitch-correction=no", popen.call_args.args[0])

    @patch("media_backend.subprocess.Popen")
    def test_changed_speed_preserves_pitch(self, popen):
        backend = object.__new__(MediaBackend)
        backend.mpv = "mpv.exe"
        popen.return_value = SimpleNamespace()
        backend.start_playback("imported.wav", speed=1.25)
        self.assertIn("--audio-pitch-correction=yes", popen.call_args.args[0])

    def test_volume_control_uses_mpv_property(self):
        backend = object.__new__(MediaBackend)
        commands = []
        backend._send_mpv_command = lambda process, command: commands.append(command) or True
        self.assertTrue(backend.set_playback_volume(object(), 85))
        self.assertEqual(commands, [["set_property", "volume", 85]])


if __name__ == "__main__":
    unittest.main()
