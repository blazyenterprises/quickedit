import tkinter as tk
from tkinter import ttk
import unittest
import time
from types import SimpleNamespace, MethodType
from unittest.mock import Mock, patch
import export_options
from quickedit import QuickEdit


class ExportTests(unittest.TestCase):
    def app(self):
        app = object.__new__(QuickEdit)
        app.require_document = Mock(return_value=SimpleNamespace(source_path='song.wav', frame_rate=44100, sample_width=2, channels=2))
        app.export_sample_rate = app.export_bit_depth = app.export_channels = None
        app.export_bitrate = 192
        app._save_to = Mock()
        return app

    def test_save_as_applies_chosen_options_before_writing(self):
        app = self.app()
        with patch('quickedit.filedialog.asksaveasfilename', return_value='chosen.flac'), patch('export_options.choose_options', return_value=(48000, 24, 1, 256)) as options:
            app.save_as()
        options.assert_called_once_with(app, 'chosen.flac', (44100, 16, 2, 192))
        self.assertEqual((app.export_sample_rate, app.export_bit_depth, app.export_channels, app.export_bitrate), (48000, 24, 1, 256))
        app._save_to.assert_called_once_with('chosen.flac')

    def test_cancel_options_does_not_write_or_change_settings(self):
        app = self.app()
        with patch('quickedit.filedialog.asksaveasfilename', return_value='existing.wav'), patch('export_options.choose_options', return_value=None):
            app.save_as()
        app._save_to.assert_not_called()
        self.assertIsNone(app.export_sample_rate)
        self.assertEqual(app.export_bitrate, 192)

    def test_cancel_filename_does_not_show_settings(self):
        app = self.app()
        with patch('quickedit.filedialog.asksaveasfilename', return_value=''), patch('export_options.choose_options') as options:
            app.save_as()
        options.assert_not_called(); app._save_to.assert_not_called()

    def test_invalid_values_rejected(self):
        for values in [('bad', '16', '2', '192'), ('0', '16', '2', '192'), ('44100', '12', '2', '192'), ('44100', '16', '9', '192'), ('44100', '16', '2', '0')]:
            with self.subTest(values=values), self.assertRaises(ValueError): export_options.validate_options(values)

    def test_real_dialog_has_labeled_controls_and_saves_typed_values(self):
        root = tk.Tk(); root.withdraw()
        self.addCleanup(root.destroy)
        root.screen_reader = Mock()
        root.bind_accessible_combobox = Mock(wraps=MethodType(QuickEdit.bind_accessible_combobox, root))
        root.accessible_button = lambda parent, text, command: ttk.Button(parent, text=text, command=command, takefocus=True)
        def interact(dialog):
            root.deiconify(); dialog.deiconify(); root.update()
            boxes = [w for w in dialog.winfo_children() if isinstance(w, ttk.Combobox)]
            self.assertEqual(len(boxes), 4)
            self.assertEqual(root.bind_accessible_combobox.call_count, 4)
            for box, value in zip(boxes, ('48000', '24', '1', '256')): box.set(value)
            boxes[0].event_generate('<<ComboboxSelected>>')
            deadline = time.monotonic() + 1
            while not root.screen_reader.speak.called and time.monotonic() < deadline:
                root.update(); time.sleep(.01)
            root.screen_reader.speak.assert_called_with('Sample rate in Hertz, 48000.')
            for box, binding in zip(boxes, root.bind_accessible_combobox.call_args_list):
                dialog.focus_force(); root.update()
                root.screen_reader.speak.reset_mock()
                box.focus_force()
                deadline = time.monotonic() + 1
                while not root.screen_reader.speak.called and time.monotonic() < deadline:
                    root.update(); time.sleep(.01)
                label, value = binding.args[1:]
                root.screen_reader.speak.assert_called_with(f'{label}, combo box, current value {value.get()}.')
            frame = next(w for w in dialog.winfo_children() if isinstance(w, tk.Frame))
            next(w for w in frame.winfo_children() if w.cget('text') == 'Save Audio').invoke()
        root.wait_window = interact
        self.assertEqual(export_options.choose_options(root, 'song.flac', (44100, 16, 2, 192)), (48000, 24, 1, 256))


if __name__ == '__main__': unittest.main()
