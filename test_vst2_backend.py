import os
import struct
import tempfile
import unittest

from vst2_backend import PE_MACHINE_X64, PE_MACHINE_X86, inspect_vst2


class VST2InspectionTests(unittest.TestCase):
    def _fake_dll(self, machine: int, vst_entry: bool) -> str:
        handle, path = tempfile.mkstemp(suffix=".dll")
        os.close(handle)
        data = bytearray(512)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\0\0"
        struct.pack_into("<H", data, 0x84, machine)
        if vst_entry:
            data[0x100:0x10E] = b"VSTPluginMain\0"
        with open(path, "wb") as target:
            target.write(data)
        self.addCleanup(lambda: os.path.isfile(path) and os.remove(path))
        return path

    def test_identifies_32_bit_vst2(self):
        result = inspect_vst2(self._fake_dll(PE_MACHINE_X86, True))
        self.assertEqual(result["architecture"], "32-bit")
        self.assertTrue(result["has_vst_entry"])

    def test_identifies_64_bit_helper_dll(self):
        result = inspect_vst2(self._fake_dll(PE_MACHINE_X64, False))
        self.assertEqual(result["architecture"], "64-bit")
        self.assertFalse(result["has_vst_entry"])


if __name__ == "__main__":
    unittest.main()
