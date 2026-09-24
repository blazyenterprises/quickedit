import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from quickedit import QuickEdit

class QueuePositionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.paths = [str(Path(self.folder.name) / (name + '.wav')) for name in ('A','B','C')]
        for p in self.paths: Path(p).touch()
        self.app = object.__new__(QuickEdit)
        a = self.app
        a.library_files = self.paths.copy()
        a.library_queue = self.paths.copy()
        a.library_queue_index = 0
        a.document = SimpleNamespace(source_path=self.paths[2])
        a.repeat_mode = 'off'
        a.announce = Mock()
        a.play_library_from_start = Mock()
        def open_path(path, announce=False):
            a.document = SimpleNamespace(source_path=path)
            return True
        a._open_path = Mock(side_effect=open_path)

    def test_previous_uses_current_file_not_stale_first_index(self):
        self.app.play_adjacent_library_song(-1)
        self.assertEqual(self.app.document.source_path, self.paths[1])
        self.assertEqual(self.app.library_queue_index, 1)
        self.app.play_adjacent_library_song(1)
        self.assertEqual(self.app.document.source_path, self.paths[2])

    def test_new_current_song_outside_old_queue_is_located_in_library(self):
        self.app.library_queue = self.paths[:2]
        self.app.play_adjacent_library_song(-1)
        self.assertEqual(self.app.document.source_path, self.paths[1])
        self.assertEqual(self.app.library_queue_index, 1)

    def test_missing_preceding_file_does_not_shift_current_identity(self):
        Path(self.paths[0]).unlink()
        self.app.play_adjacent_library_song(-1)
        self.assertEqual(self.app.document.source_path, self.paths[1])
        self.assertEqual(self.app.library_queue_index, 0)

    def test_failed_open_keeps_current_position(self):
        self.app._open_path.side_effect = None
        self.app._open_path.return_value = False
        self.app.play_adjacent_library_song(-1)
        self.assertEqual(self.app.library_queue_index, 2)
        self.app.play_library_from_start.assert_not_called()

    def test_unknown_song_does_not_jump_from_first_or_stale_index(self):
        self.app.document.source_path = 'unrelated.wav'
        self.app.play_adjacent_library_song(1)
        self.app._open_path.assert_not_called()
        self.assertEqual(self.app.library_queue_index, -1)

    def test_repeat_wraps_and_boundaries_are_directional(self):
        self.app.document.source_path = self.paths[0]
        self.app.play_adjacent_library_song(-1)
        self.assertIn('beginning', self.app.announce.call_args.args[0])
        self.app.repeat_mode = 'all'
        self.app.play_adjacent_library_song(-1)
        self.assertEqual(self.app.document.source_path, self.paths[2])

    def test_add_preserves_queue_order_and_current_position(self):
        self.app.library_files = self.paths[:2]
        self.app.library_queue = self.paths[:2][::-1]
        self.app.document.source_path = self.paths[1]
        self.app._save_file_history = Mock()
        self.app.browse_library = Mock()
        with patch('quickedit.filedialog.askopenfilenames', return_value=[self.paths[2]]):
            self.app.add_files_to_library()
        self.assertEqual(self.app.library_queue, [self.paths[1],self.paths[0],self.paths[2]])
        self.assertEqual(self.app.library_queue_index, 0)
        self.app.browse_library.assert_called_once_with('songs', focus_path=self.paths[2])

    def test_browser_highlights_current_or_new_file_after_sorting(self):
        a=self.app
        a.library_sort_mode='title'
        a.media=SimpleNamespace(read_metadata=lambda path: {})
        a.screen_reader=Mock()
        a.accessible_button=Mock()
        a.wait_window=Mock()
        for focus,expected in [(None,2),(self.paths[1],1)]:
            choices=Mock()
            with patch('quickedit.tk.Toplevel'),patch('quickedit.tk.Label'),patch('quickedit.tk.Frame'),patch('quickedit.tk.Listbox',return_value=choices):
                a.browse_library('songs',focus_path=focus)
            choices.selection_set.assert_called_once_with(expected)
            choices.see.assert_called_once_with(expected)

    def test_add_select_new_song_then_previous_and_next(self):
        a=self.app
        a.library_files=self.paths[:2]
        a.library_queue=self.paths[:2]
        a.document.source_path=self.paths[0]
        a.library_sort_mode='title'
        a.media=SimpleNamespace(read_metadata=lambda path: {})
        a.screen_reader=Mock()
        a.accessible_button=Mock()
        a._save_file_history=Mock()
        choices=Mock()
        selected=[0]
        choices.selection_set.side_effect=lambda i: selected.__setitem__(0,i)
        choices.curselection.side_effect=lambda: (selected[0],)
        callbacks={}
        choices.bind.side_effect=lambda key, callback: callbacks.update({key:callback})
        a.wait_window=lambda dialog: callbacks['<Return>']()
        with patch('quickedit.filedialog.askopenfilenames',return_value=[self.paths[2]]),patch('quickedit.tk.Toplevel'),patch('quickedit.tk.Label'),patch('quickedit.tk.Frame'),patch('quickedit.tk.Listbox',return_value=choices):
            a.add_files_to_library()
            callbacks['<Return>']()
        self.assertEqual(a.document.source_path,self.paths[2])
        self.assertEqual(a.library_queue_index,2)
        a.play_adjacent_library_song(-1)
        self.assertEqual(a.document.source_path,self.paths[1])
        a.play_adjacent_library_song(1)
        self.assertEqual(a.document.source_path,self.paths[2])

if __name__ == '__main__': unittest.main()
