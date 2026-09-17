import unittest

import cd_burner


class CdBurnerTests(unittest.TestCase):
    def test_burn_command_uses_windows_audio_cd_writer(self):
        command = cd_burner.burn_command("recorder-id", [r"C:\track 1.raw", r"C:\track 2.raw"])
        script = command[-1]
        self.assertIn("MsftDiscFormat2TrackAtOnce", script)
        self.assertIn("PrepareMedia", script)
        self.assertIn("AddAudioTrack", script)
        self.assertIn("ReleaseMedia", script)
        self.assertIn("DoNotFinalizeMedia = $false", script)


if __name__ == "__main__":
    unittest.main()
