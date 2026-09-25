import json
from pathlib import Path
import tempfile
import unittest
import wave
from media_backend import MediaBackend, MediaError


class RealEncoderTests(unittest.TestCase):
    def setUp(self):
        self.media = MediaBackend(str(Path(__file__).parent))
        if not self.media.ffmpeg or not self.media.ffprobe:
            self.skipTest('Bundled FFmpeg/FFprobe required for real export tests')
        folder = tempfile.TemporaryDirectory(); self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name); self.source = self.folder / 'source.wav'
        with wave.open(str(self.source), 'wb') as audio:
            audio.setnchannels(2); audio.setsampwidth(2); audio.setframerate(44100)
            audio.writeframes(b'\0\0\0\0' * 4410)

    def probe(self, path):
        return json.loads(self.media._run([self.media.ffprobe, '-v', 'error', '-show_streams', '-of', 'json', str(path)]).stdout)['streams'][0]

    def test_requested_24_bit_stereo_is_really_written(self):
        for extension in ['wav', 'flac', 'snd', 'caf', 'w64', 'rf64', 'wv', 'mka', 'mov']:
            with self.subTest(extension=extension):
                path = self.folder / ('result.' + extension)
                self.media.encode(str(self.source), str(path), 48000, 2, 24)
                actual = self.probe(path)
                self.assertEqual(int(actual.get('bits_per_raw_sample') or actual['bits_per_sample']), 24)
                self.assertEqual(actual['sample_rate'], '48000')
                self.assertEqual(actual['channels'], 2)

    def test_lossless_export_preserves_actual_24_bit_samples(self):
        frames = b''.join(value.to_bytes(3, 'little', signed=True) for value in [-8388607, -1, 0, 1, 1234567, 8388607]) * 100
        with wave.open(str(self.source), 'wb') as audio:
            audio.setnchannels(2); audio.setsampwidth(3); audio.setframerate(44100); audio.writeframes(frames)
        for extension in ['flac', 'wv', 'mov', 'snd', 'caf', 'w64', 'rf64']:
            with self.subTest(extension=extension):
                encoded = self.folder / ('precision.' + extension)
                decoded = self.folder / 'decoded.wav'
                self.media.encode(str(self.source), str(encoded), 44100, 2, 24)
                self.media.decode_to_format(str(encoded), str(decoded), 44100, 2, 3)
                with wave.open(str(decoded), 'rb') as audio:
                    self.assertEqual(audio.readframes(audio.getnframes()), frames)

    def test_failed_real_encoder_preserves_existing_file(self):
        path = self.folder / 'important.mp3'; path.write_bytes(b'original file')
        with self.assertRaises(MediaError): self.media.encode(str(self.source), str(path), 44100, 8, 16)
        self.assertEqual(path.read_bytes(), b'original file')
        self.assertFalse(list(self.folder.glob('.quickedit-*')))

    def test_unsupported_lossless_depth_is_not_silently_reduced(self):
        path = self.folder / 'important.flac'; path.write_bytes(b'original file')
        with self.assertRaisesRegex(MediaError, '16 or 24'): self.media.encode(str(self.source), str(path), 44100, 2, 32)
        self.assertEqual(path.read_bytes(), b'original file')

    def test_opus_rate_checked_and_supported_rate_encodes(self):
        path = self.folder / 'song.opus'
        with self.assertRaisesRegex(MediaError, '48000'): self.media.encode(str(self.source), str(path), 44100, 2, 16)
        self.assertFalse(path.exists())
        self.media.encode(str(self.source), str(path), 48000, 2, 16)
        self.assertEqual(self.probe(path)['sample_rate'], '48000')


if __name__ == '__main__': unittest.main()
