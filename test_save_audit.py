import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from quickedit import QuickEdit, AudioDocument
from media_backend import MediaBackend, MediaError, replace_file


class SaveAuditTests(unittest.TestCase):
    def test_brief_windows_lock_is_retried(self):
        with patch('media_backend.os.replace', side_effect=[PermissionError('sharing lock'), None]) as replace, patch('media_backend.time.sleep'):
            replace_file('staged', 'destination')
        self.assertEqual(replace.call_count, 2)

    def app(self):
        app = object.__new__(QuickEdit)
        app.document = AudioDocument(1, 2, 44100, b'\0\0' * 100, 'original.wav')
        app.document.save_path = 'original.wav'
        app._mark_document_saved()
        app.export_sample_rate = app.export_bit_depth = app.export_channels = None
        app.export_bitrate = 192
        app.stop = Mock(); app.refresh_details = Mock(); app.title = Mock(); app.announce = Mock()
        app.undo_stack = []; app.redo_stack = []
        return app

    def test_failed_wav_save_preserves_original_and_dirty_state(self):
        app = self.app(); app.document.frames += b'\0\0'
        def fail(path, frames):
            Path(path).write_bytes(b'partial'); raise OSError('disk full')
        app._write_wav = fail
        with tempfile.TemporaryDirectory() as folder, patch('quickedit.messagebox.showerror'):
            path = Path(folder) / 'important.wav'; path.write_bytes(b'original')
            self.assertFalse(app._save_to(str(path)))
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(list(Path(folder).iterdir()), [path])
            self.assertTrue(app._document_has_changes())

    def test_failed_encoder_preserves_destination(self):
        backend = object.__new__(MediaBackend)
        def fail(source, target, *args):
            Path(target).write_bytes(b'partial'); raise MediaError('encoder failed')
        backend._encode_direct = fail
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'important.mp3'; path.write_bytes(b'original')
            with self.assertRaises(MediaError): backend.encode('source.wav', str(path))
            self.assertEqual(path.read_bytes(), b'original')
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_successful_save_marks_clean(self):
        app = self.app(); app.document.frames += b'\0\0'
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'saved.wav')
            self.assertTrue(app._save_to(path))
            self.assertFalse(app._document_has_changes())
            self.assertEqual(app.document.save_path, path)

    def test_undo_redo_preserve_save_as_destination(self):
        app = self.app(); before = copy.deepcopy(app.document)
        app.document.frames += b'\0\0'
        app.undo_stack.append(before)
        app.document.save_path = 'edited-copy.wav'
        app._mark_document_saved()
        app.undo()
        self.assertEqual(app.document.save_path, 'edited-copy.wav')
        self.assertTrue(app._document_has_changes())
        app.redo()
        self.assertEqual(app.document.save_path, 'edited-copy.wav')
        self.assertFalse(app._document_has_changes())

    def test_cancel_or_failed_save_prevents_replacement(self):
        app = self.app(); app.document.metadata['title'] = 'Unsaved title'
        original = app.document
        with patch('quickedit.messagebox.askyesnocancel', return_value=None):
            app.new_file()
        self.assertIs(app.document, original)
        app.save = Mock(return_value=False)
        with patch('quickedit.messagebox.askyesnocancel', return_value=True):
            self.assertFalse(app._confirm_document_change())
        app.save.assert_called_once()

    def test_cancel_prevents_open_and_close(self):
        app = self.app(); app.document.frames += b'\0\0'
        with patch('quickedit.messagebox.askyesnocancel', return_value=None), patch('quickedit.tk.Tk.destroy') as destroy:
            self.assertFalse(app._open_path('other.wav'))
            app.destroy()
        destroy.assert_not_called()

    def test_cursor_and_selection_do_not_mark_audio_dirty(self):
        app = self.app()
        app.document.cursor_frame = 42; app.document.selection_start = 1; app.document.selection_end = 50
        self.assertFalse(app._document_has_changes())

    def test_discard_new_file_starts_clean(self):
        app = self.app(); app.document.frames += b'\0\0'
        with patch('quickedit.messagebox.askyesnocancel', return_value=False): app.new_file()
        self.assertFalse(app._document_has_changes())
        self.assertEqual(app.document.frames, b'')


if __name__ == '__main__': unittest.main()
