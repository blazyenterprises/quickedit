import json
import tempfile
import unittest
from pathlib import Path

from theme_manager import PALETTES, ThemeManager


def luminance(color: str) -> float:
    values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    values = [value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4 for value in values]
    return 0.2126 * values[0] + 0.7152 * values[1] + 0.0722 * values[2]


def contrast(a: str, b: str) -> float:
    bright, dark = sorted((luminance(a), luminance(b)), reverse=True)
    return (bright + 0.05) / (dark + 0.05)


class ThemeTests(unittest.TestCase):
    def test_all_palette_text_meets_wcag_aa(self):
        for name, palette in PALETTES.items():
            with self.subTest(name=name):
                self.assertGreaterEqual(contrast(palette.text, palette.window), 4.5)
                self.assertGreaterEqual(contrast(palette.text, palette.surface), 4.5)
                self.assertGreaterEqual(contrast(palette.selection_text, palette.selection), 4.5)

    def test_setting_round_trip_without_gui(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            holder = object.__new__(ThemeManager)
            holder.settings_path = path
            holder.MODES = ThemeManager.MODES
            ThemeManager.save_mode(holder, "dark_dim")
            self.assertEqual(json.loads(path.read_text())["theme_mode"], "dark_dim")
            self.assertEqual(ThemeManager.load_mode(holder), "dark_dim")


if __name__ == "__main__":
    unittest.main()
