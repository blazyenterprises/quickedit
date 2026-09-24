import json
from pathlib import Path
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from quickedit import QuickEdit, AudioDocument
from media_backend import AudioDevice, MediaError
from online_backend import OnlineBackend, OnlineResult

class RegressionTests(unittest.TestCase):
    def editor(self):
        app = object.__new__(QuickEdit)
        app.recent_files = []
        app.favorite_files = []
        app.input_device = None
        app.output_device = 'auto'
        app.library_files = []
        app.workspace_mode = 'library'
        app.announce = Mock()
        return app

    def test_devices_survive_restart_and_unrelated_settings_save(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder):
            app = self.editor()
            app.media = SimpleNamespace(input_devices=lambda: [], output_devices=lambda: [])
            app._choose_device = Mock(return_value=AudioDevice('mic-id', 'Microphone', 'dshow'))
            app.choose_input_device()
            app._choose_device.return_value = AudioDevice('wasapi/speakers-id', 'Speakers')
            app.choose_output_device()
            other = self.editor()
            other._load_file_history()
            self.assertEqual(other.input_device, app.input_device)
            self.assertEqual(other.output_device, app.output_device)
            other._save_file_history()
            saved = json.loads(Path(other._history_path).read_text())
            self.assertEqual(saved['output_device'], 'wasapi/speakers-id')

    def test_library_open_adds_multiple_files_and_shows_saved_library(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder):
            app = self.editor()
            paths = [os.path.join(folder, 'one.wav'), os.path.join(folder, 'two.wav')]
            app.browse_library = Mock()
            with patch('quickedit.filedialog.askopenfilenames', return_value=paths + paths[:1]):
                app.open_file()
            self.assertEqual(app.library_files, paths)
            self.assertEqual(app.library_queue, paths)
            app.browse_library.assert_called_once_with('songs', focus_path=paths[-1])
            other = self.editor()
            other._load_file_history()
            self.assertEqual(other.library_files, paths)

    def test_play_announces_metadata_title_and_artist(self):
        app = self.editor()
        app.document = AudioDocument(1, 2, 44100, b'\x00\x00' * 100, 'file.wav', metadata={'title': 'My song', 'artist': 'An artist'})
        app.require_document = lambda: app.document
        app.refresh_details = Mock()
        app._play_frames = Mock()
        app.master_play()
        self.assertIn('My song by An artist', app._play_frames.call_args.args[3])
        app._play_forward_from_cursor()
        self.assertIn('My song by An artist', app._play_frames.call_args.args[3])

    def test_failed_song_switch_does_not_replay_old_song(self):
        app = self.editor()
        app.document = AudioDocument(1, 2, 44100, b'\x00\x00', 'one.wav')
        app.library_queue = ['one.wav', 'two.wav']
        app.library_queue_index = 0
        app.repeat_mode = 'off'
        app._open_path = Mock(return_value=False)
        app.play_library_from_start = Mock()
        with patch('quickedit.os.path.isfile', return_value=True):
            app.play_adjacent_library_song(1)
        app.play_library_from_start.assert_not_called()

    def test_failed_online_import_preserves_document_and_workspace(self):
        app = self.editor()
        old = app.document = object()
        app.online = SimpleNamespace(download_source=Mock(side_effect=MediaError('Temporary network failure')))
        app._load_online_wav = Mock()
        with patch('quickedit.messagebox.showerror'):
            self.assertFalse(app._import_online_result(OnlineResult('Song', 'https://example.test', 'YouTube')))
        self.assertIs(app.document, old)
        self.assertEqual(app.workspace_mode, 'library')
        app._load_online_wav.assert_not_called()

    def test_invalid_online_wav_reports_failure(self):
        app = self.editor()
        with tempfile.NamedTemporaryFile(suffix='.wav') as f, patch('quickedit.messagebox.showerror'):
            self.assertFalse(app._load_online_wav(f.name, 'Song'))

    def test_online_results_stay_open_after_failure_and_close_after_success(self):
        app = self.editor()
        app.preview_process = None
        app.screen_reader = Mock()
        app.accessible_button = Mock()
        app._import_online_result = Mock(side_effect=[False, True])
        dialog, choices = Mock(), Mock()
        choices.curselection.return_value = (0,)
        callbacks = {}
        choices.bind.side_effect = lambda key, callback: callbacks.update({key: callback})
        def interact(window):
            callbacks["<Return>"]()
            dialog.destroy.assert_not_called()
            self.assertEqual(app.workspace_mode, "library")
            callbacks["<Return>"]()
            dialog.destroy.assert_called_once()
        app.wait_window = interact
        with patch('quickedit.tk.Toplevel', return_value=dialog), patch('quickedit.tk.Listbox', return_value=choices), patch('quickedit.tk.Label'), patch('quickedit.tk.Frame'), patch('quickedit.tk.StringVar'):
            app._choose_online_result([OnlineResult('Song', 'https://example.test', 'YouTube')], 'Results')

    def test_youtube_uses_bundled_runtime_and_ignores_external_config(self):
        backend = OnlineBackend(os.getcwd())
        with patch('online_backend.os.path.isfile', return_value=True), patch('online_backend.subprocess.run', return_value=SimpleNamespace(returncode=0, stdout='https://example.test/audio\n')) as run:
            self.assertEqual(backend.preview_url('https://example.test/video?list=x'), 'https://example.test/audio')
        args = run.call_args.args[0]
        self.assertIn('--ignore-config', args)
        self.assertIn('--no-playlist', args)
        self.assertIn('node:' + os.path.join(os.path.dirname(backend.ytdlp), 'node.exe'), args)

if __name__ == '__main__':
    unittest.main()
