import json
import os
import tempfile
import unittest
from unittest.mock import patch

from quickedit import QuickEdit


class SettingsAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        env = patch.dict(os.environ, {"APPDATA": self.directory.name})
        env.start(); self.addCleanup(env.stop)
        self.app = object.__new__(QuickEdit)
        self.app.recent_files = []
        self.app.favorite_files = []
        self.app.library_files = []
        os.makedirs(os.path.dirname(self.app._history_path))

    def write(self, data):
        with open(self.app._history_path, 'w', encoding='utf-8') as output:
            json.dump(data, output)

    def read(self):
        with open(self.app._history_path, encoding='utf-8') as source:
            return json.load(source)

    def test_invalid_top_level_does_not_crash_load_or_save(self):
        for data in ([], None, 'broken', 12):
            with self.subTest(data=data):
                self.write(data)
                self.app._load_file_history()
                self.app._save_file_history()
                self.assertIsInstance(self.read(), dict)

    def test_bad_fields_do_not_prevent_loading_valid_preferences(self):
        self.write({
            'recent_files': None, 'favorite_files': 'not a list',
            'online_download_sample_rate': 'bad', 'online_download_bitrate': {},
            'keyboard_sample_root': None, 'library_display_fields': [{}],
            'muted_midi_channels': ['²', {}, 3, '4', 99],
            'library_playlists': {'valid': ['song.wav', {}], 'broken': None},
            'library_files': ['song.wav', None], 'saved_streams': [None, {'url': []}],
            'workspace_mode': 'library', 'output_device': 'chosen-device',
            'repeat_mode': 'all', 'keyboard_instrument_mode': 'sample',
        })
        self.app._load_file_history()
        self.assertEqual(self.app.output_device, 'chosen-device')
        self.assertEqual(self.app.workspace_mode, 'library')
        self.assertEqual(self.app.library_files, ['song.wav'])
        self.assertEqual(self.app.library_playlists, {'valid': ['song.wav']})
        self.assertEqual(self.app.muted_midi_channels, {3, 4})
        self.assertEqual(self.app.online_download_sample_rate, 44100)
        self.assertEqual(self.app.online_download_bitrate, 192)
        self.assertEqual(self.app.keyboard_sample_root, 60)
        self.assertEqual(self.app.keyboard_instrument_mode, 'sample')

    def test_successful_write_keeps_unknown_preferences(self):
        self.write({'future_setting': {'enabled': True}})
        self.app._save_file_history()
        self.assertEqual(self.read()['future_setting'], {'enabled': True})
        self.assertEqual(os.listdir(os.path.dirname(self.app._history_path)), ['settings.json'])

    def test_streams_without_labels_get_safe_browser_defaults(self):
        self.write({'saved_streams': [{'url': 'https://example.com/radio'},
                                      {'url': 'https://example.com/other', 'name': '', 'provider': ''}]})
        self.app._load_file_history()
        self.assertEqual(len(self.app.saved_streams), 2)
        for stream in self.app.saved_streams:
            self.assertEqual(stream['name'], stream['url'])
            self.assertEqual(stream['provider'], 'Direct link')

    def test_failed_atomic_replace_preserves_existing_settings_and_reports(self):
        previous = {'library_files': ['old.wav'], 'future_setting': True}
        self.write(previous)
        with patch('quickedit.os.replace', side_effect=OSError('disk failure')), patch('quickedit.messagebox.showwarning') as warning:
            self.app._remember_recent('new.wav')
        self.assertEqual(self.read(), previous)
        self.assertTrue(self.app.recent_files[0].endswith('new.wav'))
        warning.assert_called_once()
        self.assertEqual(os.listdir(os.path.dirname(self.app._history_path)), ['settings.json'])


if __name__ == '__main__':
    unittest.main()
