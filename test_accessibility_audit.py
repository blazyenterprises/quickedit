"""Exercise native dropdown events with the application dispatcher installed."""
import tkinter as tk
from tkinter import ttk
import unittest
from unittest.mock import Mock

from quickedit import QuickEdit
from accessible_combo import bind_combobox
from export_options import choose_options


class ShortcutIsolationTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.errors = []
        self.root.report_callback_exception = lambda *args: self.errors.append(args)
        self.root._posted_menu = lambda: None
        self.root.workspace_mode = 'editor'
        self.root.navigation_step = .1
        self.root.move_cursor = Mock()
        self.root.delete_selection = Mock()
        self.root.toggle_play = Mock()
        self.root._invoke = QuickEdit._invoke
        self.root.bind_all('<KeyPress>', lambda event: QuickEdit._dispatch_key(self.root, event), add='+')

    def test_native_dropdown_does_not_edit_or_play_document(self):
        dialog = tk.Toplevel(self.root)
        dialog.grab_set()
        box = ttk.Combobox(dialog, values=('one', 'two'))
        box.pack(); box.set('one')
        self.root.update(); box.focus_force(); self.root.update()
        box.event_generate('<Down>'); self.root.update()
        listing = self.root.tk.call('focus')
        self.assertEqual(self.root.tk.call('winfo', 'class', listing), 'Listbox')
        for key in ('Right', 'Delete', 'space'):
            self.root.tk.call('event', 'generate', listing, '<' + key + '>')
            self.root.update()
        self.root.move_cursor.assert_not_called()
        self.root.delete_selection.assert_not_called()
        self.root.toggle_play.assert_not_called()
        self.assertEqual(self.errors, [])

    def test_editable_main_window_combo_keeps_editing_keys(self):
        box = ttk.Combobox(self.root, values=('one', 'two'))
        box.pack(); box.set('one')
        self.root.update(); box.focus_force(); self.root.update()
        box.event_generate('<Delete>'); self.root.update()
        self.root.delete_selection.assert_not_called()
        self.assertEqual(self.errors, [])

    def test_document_shortcuts_still_work_when_editor_has_focus(self):
        canvas = tk.Canvas(self.root, takefocus=True)
        canvas.pack(); self.root.update(); canvas.focus_force(); self.root.update()
        canvas.event_generate('<Right>'); self.root.update()
        self.root.move_cursor.assert_called_once_with(.1)
        self.assertEqual(self.errors, [])

    def test_output_popup_escape_and_tab_do_not_save(self):
        self.root.screen_reader = Mock()
        self.root.bind_accessible_combobox = lambda box, label, value: bind_combobox(self.root, box, label, value)
        self.root.accessible_button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
        observations = []
        def navigate():
            dialog = next(child for child in self.root.winfo_children() if isinstance(child, tk.Toplevel))
            box = next(child for child in dialog.winfo_children() if child.winfo_class() == 'TCombobox')
            box.focus_force(); self.root.update()
            box.event_generate('<Down>'); self.root.update()
            listing = self.root.tk.call('focus')
            self.root.tk.call('event', 'generate', listing, '<Escape>'); self.root.update()
            observations.append(bool(dialog.winfo_exists()))
            box.event_generate('<Tab>'); self.root.update()
            observations.append(bool(dialog.winfo_exists()))
            dialog.event_generate('<Escape>')
        self.root.after(100, navigate)
        self.assertIsNone(choose_options(self.root, 'song.wav', (44100, 16, 2, 192)))
        self.assertEqual(observations, [True, True])
        self.assertEqual(self.errors, [])

    def test_online_download_settings_bind_all_three_values(self):
        self.root.online_download_format = '.mp3'
        self.root.online_download_sample_rate = 44100
        self.root.online_download_bitrate = 192
        self.root.accessible_button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
        bindings = []
        self.root.bind_accessible_combobox = lambda box, label, variable: bindings.append((label, variable.get()))
        self.root.wait_window = lambda dialog: dialog.destroy()
        QuickEdit.online_download_settings(self.root)
        self.assertEqual(bindings, [('Download format', 'MP3'), ('Sample rate', '44100'), ('Compressed audio bitrate', '192')])

    def test_cancel_output_settings_restores_underlying_library_modal(self):
        self.root.screen_reader = Mock()
        self.root.bind_accessible_combobox = lambda box, label, value: bind_combobox(self.root, box, label, value)
        self.root.accessible_button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
        library = tk.Toplevel(self.root)
        listing = tk.Listbox(library)
        listing.pack(); library.grab_set(); self.root.update()
        listing.focus_force(); self.root.update()
        def cancel():
            settings = next(child for child in self.root.winfo_children()
                            if isinstance(child, tk.Toplevel) and child is not library)
            settings.destroy()
        self.root.after(100, cancel)
        self.assertIsNone(choose_options(self.root, 'song.wav', (44100, 16, 2, 192)))
        self.root.update()
        self.assertIs(self.root.grab_current(), library)
        self.assertIs(self.root.focus_get(), listing)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main()
