import os
import tempfile
import threading
import unittest
import wave
from types import SimpleNamespace
from unittest.mock import Mock, patch

from quickedit import QuickEdit
from library_tools import MetadataCache
from media_backend import MediaError


class PlaybackAuditTests(unittest.TestCase):
    def app(self):
        app = object.__new__(QuickEdit)
        app.document = SimpleNamespace(cursor_frame=100, seconds_at=lambda f: f / 10)
        app.playing = True
        app.play_direction = 1
        app.repeat_mode = 'off'
        app.workspace_mode = 'library'
        app.library_queue = ['a.wav', 'b.wav']
        app._library_track_playback = True
        app._current_library_index = Mock(return_value=0)
        app._sync_transport_cursor = Mock(return_value=True)
        for name in ('refresh_details', 'stop', 'announce', 'play_adjacent_library_song', 'master_play', 'play_library_from_start'):
            setattr(app, name, Mock())
        return app

    def test_repeat_off_advances_remaining_tracks(self):
        app = self.app()
        with patch('quickedit.os.path.isfile', return_value=True):
            app._transport_tick()
        app.play_adjacent_library_song.assert_called_once_with(1)

    def test_repeat_off_stops_at_boundary(self):
        app = self.app()
        app._current_library_index.return_value = 1
        with patch('quickedit.os.path.isfile', return_value=True):
            app._transport_tick()
        app.play_adjacent_library_song.assert_not_called()
        app.announce.assert_called_once()

    def test_repeat_all_wraps_library_but_not_editor_selection(self):
        app = self.app()
        app.repeat_mode = 'all'
        app._current_library_index.return_value = 1
        with patch('quickedit.os.path.isfile', return_value=True):
            app._transport_tick()
        app.play_adjacent_library_song.assert_called_once_with(1)
        app.play_adjacent_library_song.reset_mock()
        app.workspace_mode = 'editor'
        app._transport_tick()
        app.play_adjacent_library_song.assert_not_called()
        app.master_play.assert_called_once()

    def test_library_selection_does_not_advance_queue(self):
        app = self.app()
        app._library_track_playback = False
        app._transport_tick()
        app.play_adjacent_library_song.assert_not_called()

    def test_failed_player_exit_stops_without_repeat_or_queue_advance(self):
        for repeat in ('off', 'one', 'all'):
            with self.subTest(repeat=repeat):
                app = self.app()
                app.repeat_mode = repeat
                app.play_process = Mock()
                app.play_process.poll.return_value = 1
                app._transport_tick()
                app.stop.assert_called_once_with(announce=False)
                app._sync_transport_cursor.assert_not_called()
                app.play_adjacent_library_song.assert_not_called()
                app.play_library_from_start.assert_not_called()
                app.master_play.assert_not_called()
                self.assertIn('Playback failed', app.announce.call_args.args[0])

    def test_successful_player_exit_early_is_normal_completion(self):
        app = self.app()
        app.document.frame_count = 120
        app.play_target_frame = 120
        app.play_process = Mock()
        app.play_process.poll.return_value = 0
        app._sync_transport_cursor.return_value = False
        with patch('quickedit.os.path.isfile', return_value=True):
            app._transport_tick()
        self.assertEqual(app.document.cursor_frame, 120)
        app.play_adjacent_library_song.assert_called_once_with(1)
        app.announce.assert_not_called()

    def test_failed_tags_do_not_prevent_valid_audio_open(self):
        app = self.app()
        app.media = SimpleNamespace(read_metadata=Mock(side_effect=MediaError('Tag timeout')))
        app.undo_stack = []
        app.redo_stack = []
        app.title = Mock()
        app._remember_recent = Mock()
        app._confirm_discard_changes = Mock(return_value=True)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'audio.wav')
            with wave.open(path, 'wb') as output:
                output.setparams((1, 2, 8000, 0, 'NONE', ''))
                output.writeframes(b'\0\0' * 800)
            with patch('quickedit.messagebox.showerror') as error:
                self.assertTrue(app._open_path(path))
            error.assert_not_called()
            self.assertEqual(app.document.metadata, {})

    def test_failed_cache_probe_retries_without_file_change(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, 'audio.wav')
            open(path, 'wb').close()
            probe = Mock(side_effect=[MediaError('Tag timeout'), {'artist': 'Recovered'}])
            cache = MetadataCache(probe, dict)
            self.assertEqual(cache.load([path], threading.Event()), [(path, {})])
            self.assertEqual(cache.load([path], threading.Event()), [(path, {'artist': 'Recovered'})])

    def test_launch_failure_cleans_temporary_audio_and_reports_error(self):
        app = self.app()
        app.stop = QuickEdit.stop.__get__(app)
        app.play_process = None
        app.transport_timer = None
        app.temp_play_path = None
        app.playback_preset_one_shot = False
        app.playback_pitch_semitones = 0
        app.playback_speed = 1
        app.output_device = 'auto'
        app.playback_volume = 100
        app.media = SimpleNamespace(start_playback=Mock(side_effect=OSError('Player missing')))
        created = []
        app._write_wav = lambda path, frames: created.append(path)
        with patch('quickedit.winsound.PlaySound'), patch('quickedit.messagebox.showerror') as error:
            app._play_frames(b'\0\0', 0, 1, 'Playing')
        self.assertFalse(app.playing)
        self.assertIsNone(app.temp_play_path)
        self.assertTrue(created)
        self.assertFalse(os.path.exists(created[0]))
        error.assert_called_once()


if __name__ == '__main__':
    unittest.main()
