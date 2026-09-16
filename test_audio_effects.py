import unittest

import audio_effects


class AudioEffectTests(unittest.TestCase):
    def test_amplify_and_clip_16_bit(self):
        source = (1000).to_bytes(2, "little", signed=True) + (20000).to_bytes(2, "little", signed=True)
        result = audio_effects.scale_pcm(source, 2, 2)
        self.assertEqual(int.from_bytes(result[:2], "little", signed=True), 2000)
        self.assertEqual(int.from_bytes(result[2:], "little", signed=True), 32767)

    def test_silence_uses_unsigned_midpoint_for_8_bit(self):
        self.assertEqual(audio_effects.silence(b"\x00\xff", 1), b"\x80\x80")

    def test_reverse_preserves_stereo_frames(self):
        self.assertEqual(audio_effects.reverse_frames(b"LRlr", 2), b"lrLR")

    def test_swap_stereo_channels(self):
        self.assertEqual(audio_effects.swap_first_two_channels(b"LRlr", 1, 2), b"RLrl")

    def test_fades_reach_silence_at_the_correct_end(self):
        sample = (1000).to_bytes(2, "little", signed=True)
        source = sample * 3
        faded_in = audio_effects.fade(source, 2, 1, True)
        faded_out = audio_effects.fade(source, 2, 1, False)
        self.assertEqual(int.from_bytes(faded_in[:2], "little", signed=True), 0)
        self.assertEqual(int.from_bytes(faded_in[-2:], "little", signed=True), 1000)
        self.assertEqual(int.from_bytes(faded_out[:2], "little", signed=True), 1000)
        self.assertEqual(int.from_bytes(faded_out[-2:], "little", signed=True), 0)

    def test_normalize_silence_is_unchanged(self):
        self.assertEqual(audio_effects.normalize(bytes(8), 2), bytes(8))

    def test_echo_does_not_cross_stereo_channels(self):
        # One left-channel impulse followed by silent stereo frames.
        source = b"\xff\x7f\x00\x00" + bytes(12)
        result = audio_effects.echo(source, 2, 2, 4, delay_ms=250, feedback=0.5, wet=1.0)
        right = [int.from_bytes(result[i + 2:i + 4], "little", signed=True) for i in range(0, len(result), 4)]
        self.assertEqual(right, [0, 0, 0, 0])
        self.assertNotEqual(result[4:6], b"\x00\x00")

    def test_modulation_effects_preserve_length(self):
        source = (1000).to_bytes(2, "little", signed=True) * 100
        for effect in (audio_effects.reverb, audio_effects.flanger, audio_effects.chorus):
            with self.subTest(effect=effect.__name__):
                self.assertEqual(len(effect(source, 2, 1, 100)), len(source))

    def test_filter_and_dynamics_effects_preserve_length(self):
        source = (1000).to_bytes(2, "little", signed=True) * 200
        effects = (
            lambda: audio_effects.lowpass(source, 2, 1, 1000, 100),
            lambda: audio_effects.highpass(source, 2, 1, 1000, 100),
            lambda: audio_effects.noise_gate(source, 2, 1, 1000),
            lambda: audio_effects.noise_reduce(source, 2, 1, 1000),
            lambda: audio_effects.compressor(source, 2, 1, 1000),
        )
        for effect in effects:
            self.assertEqual(len(effect()), len(source))

    def test_lowpass_smooths_an_abrupt_change(self):
        source = (0).to_bytes(2, "little", signed=True) + (20000).to_bytes(2, "little", signed=True)
        result = audio_effects.lowpass(source, 2, 1, 1000, 50)
        second = int.from_bytes(result[2:4], "little", signed=True)
        self.assertGreater(second, 0)
        self.assertLess(second, 20000)

    def test_compressor_reduces_loud_signal(self):
        source = (30000).to_bytes(2, "little", signed=True) * 1000
        result = audio_effects.compressor(source, 2, 1, 1000, -20, 4, attack_ms=1)
        self.assertLess(abs(int.from_bytes(result[-2:], "little", signed=True)), 30000)

    def test_mix_extends_to_longer_input_and_clips(self):
        one = (20000).to_bytes(2, "little", signed=True)
        result = audio_effects.mix_pcm(one, one * 2, 2)
        self.assertEqual(len(result), 4)
        self.assertEqual(int.from_bytes(result[:2], "little", signed=True), 32767)
        self.assertEqual(int.from_bytes(result[2:], "little", signed=True), 20000)

    def test_crossfade_halves_overlap_and_shorten(self):
        outgoing = (1000).to_bytes(2, "little", signed=True) * 4
        incoming = (2000).to_bytes(2, "little", signed=True) * 4
        result = audio_effects.crossfade_halves(outgoing + incoming, 2, 1)
        self.assertEqual(len(result), len(outgoing))
        self.assertEqual(int.from_bytes(result[:2], "little", signed=True), 1000)
        self.assertEqual(int.from_bytes(result[-2:], "little", signed=True), 2000)


if __name__ == "__main__":
    unittest.main()
