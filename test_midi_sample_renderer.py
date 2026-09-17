import os
import tempfile
import unittest
import wave

from midi_sample_renderer import filter_midi_channels, read_midi_notes, render_midi_with_sample
from soundfont_tools import Preset, one_note_midi


class MidiSampleRendererTests(unittest.TestCase):
    def test_reads_note_timing_from_standard_midi(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "note.mid")
            with open(path, "wb") as target:
                target.write(one_note_midi(64, Preset("Test", 0, 0), duration_seconds=1.0, velocity=91))
            division, tempos, notes = read_midi_notes(path)
            self.assertEqual(division, 480)
            self.assertEqual(tempos[0], (0, 500_000))
            self.assertEqual((notes[0].note, notes[0].velocity), (64, 91))
            self.assertEqual(notes[0].end_tick - notes[0].start_tick, 960)

    def test_channel_filter_removes_only_muted_channel_events(self):
        with tempfile.TemporaryDirectory() as folder:
            source = os.path.join(folder, "source.mid")
            filtered = os.path.join(folder, "filtered.mid")
            with open(source, "wb") as target:
                target.write(one_note_midi(64, Preset("Test", 0, 0)))
            filter_midi_channels(source, filtered, {0})
            _division, _tempos, notes = read_midi_notes(filtered)
            self.assertEqual(notes, [])
            filter_midi_channels(source, filtered, {1})
            _division, _tempos, notes = read_midi_notes(filtered)
            self.assertEqual(notes[0].channel, 0)

    def test_sample_is_repeated_for_full_note_duration(self):
        with tempfile.TemporaryDirectory() as folder:
            midi = os.path.join(folder, "note.mid")
            sample = os.path.join(folder, "beep.wav")
            rendered = os.path.join(folder, "rendered.wav")
            with open(midi, "wb") as target:
                target.write(one_note_midi(60, Preset("Test", 0, 0), duration_seconds=1.0))
            with wave.open(sample, "wb") as target:
                target.setnchannels(1); target.setsampwidth(2); target.setframerate(8000)
                target.writeframes((b"\x00\x20\x00\xe0") * 40)
            render_midi_with_sample(midi, sample, rendered, root_note=60, sample_rate=8000)
            with wave.open(rendered, "rb") as result:
                self.assertGreaterEqual(result.getnframes(), 7900)
                self.assertEqual(result.getframerate(), 8000)


if __name__ == "__main__":
    unittest.main()
