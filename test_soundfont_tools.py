import struct
import tempfile
import unittest
import os

from soundfont_tools import Preset, list_presets, one_note_midi


class SoundFontToolTests(unittest.TestCase):
    def test_reads_presets_and_ignores_eop(self):
        def record(name, program, bank):
            return struct.pack("<20sHHHIII", name.encode(), program, bank, 0, 0, 0, 0)
        phdr = record("Piano", 0, 0) + record("Drums", 0, 128) + record("EOP", 0, 0)
        body = b"sfbk" + b"phdr" + struct.pack("<I", len(phdr)) + phdr
        riff = b"RIFF" + struct.pack("<I", len(body)) + body
        handle, path = tempfile.mkstemp(suffix=".sf2")
        os.close(handle)
        try:
            with open(path, "wb") as target:
                target.write(riff)
            self.assertEqual(list_presets(path), [Preset("Piano", 0, 0), Preset("Drums", 128, 0)])
        finally:
            os.remove(path)

    def test_one_note_midi_has_valid_header_and_program(self):
        data = one_note_midi(60, Preset("Organ", 0, 16))
        self.assertEqual(data[:4], b"MThd")
        self.assertIn(bytes((0xC0, 16)), data)
        self.assertIn(bytes((0x90, 60, 100)), data)


if __name__ == "__main__":
    unittest.main()
