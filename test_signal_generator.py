import unittest

import signal_generator


class SignalGeneratorTests(unittest.TestCase):
    def test_every_basic_waveform_has_expected_pcm_length(self):
        for kind in ("sine", "square", "triangle", "sawtooth", "white noise", "pink noise"):
            data = signal_generator.generate_waveform(kind, 440, .1, 8000, 2, 2)
            self.assertEqual(len(data), 800 * 2 * 2)

    def test_dtmf_uses_original_telephone_generator_table(self):
        self.assertEqual(signal_generator.DTMF["5"], (770, 1336))
        self.assertEqual(signal_generator.DTMF["#"], (941, 1477))
        data = signal_generator.generate_phone_keys("DTMF", "5#", 10, 8000, 2, 1)
        self.assertGreater(len(data), 0)

    def test_mf_uses_original_telephone_generator_table(self):
        self.assertEqual(signal_generator.MF["1"], (700, 900))
        self.assertEqual(signal_generator.MF["0"], (1300, 1500))

    def test_invalid_phone_key_is_rejected(self):
        with self.assertRaises(ValueError):
            signal_generator.generate_phone_keys("MF", "#", 8, 44100, 2, 1)


if __name__ == "__main__":
    unittest.main()
