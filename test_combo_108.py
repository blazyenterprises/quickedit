import time
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock
from accessible_combo import bind_combobox


class ComboTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.root.screen_reader = Mock()
        self.value = tk.StringVar(value='44100')
        self.box = ttk.Combobox(self.root, textvariable=self.value, values=('22050', '44100', '48000', '96000'))
        self.box.pack()
        bind_combobox(self.root, self.box, 'Sample rate', self.value)
        self.root.update(); self.box.focus_force(); self.pump()
        self.root.screen_reader.speak.reset_mock()
        self.addCleanup(self.root.destroy)

    def pump(self):
        end = time.monotonic() + .12
        while time.monotonic() < end:
            self.root.update(); time.sleep(.005)

    def test_open_dropdown_announces_highlight_before_commit(self):
        self.box.event_generate('<Down>'); self.pump()
        listing = self.root.tk.call('focus')
        self.assertEqual(self.root.tk.call('winfo', 'class', listing), 'Listbox')
        self.root.tk.call('event', 'generate', listing, '<Down>')
        self.root.tk.call('event', 'generate', listing, '<KeyRelease-Down>')
        self.pump()
        self.assertEqual(self.value.get(), '44100')
        self.root.screen_reader.speak.assert_called_with('Sample rate, 48000.')
        self.root.tk.call('event', 'generate', listing, '<Down>')
        self.root.tk.call('event', 'generate', listing, '<KeyRelease-Down>')
        self.pump()
        self.root.screen_reader.speak.assert_called_with('Sample rate, 96000.')
        self.root.tk.call('event', 'generate', listing, '<Return>'); self.pump()
        self.assertEqual(self.value.get(), '96000')

    def test_typed_value_is_announced(self):
        self.box.delete(0, 'end'); self.box.insert(0, '32000'); self.pump()
        self.root.screen_reader.speak.assert_called_with('Sample rate, 32000.')

    def test_destroy_cancels_pending_speech(self):
        self.value.set('48000'); self.box.destroy(); self.pump()
        self.root.screen_reader.speak.assert_not_called()


if __name__ == '__main__': unittest.main()
