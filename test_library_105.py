import tempfile
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import library_tools as lib
from quickedit import QuickEdit


class LibraryTests(unittest.TestCase):
    def test_backspace_returns_from_both_group_and_song_lists(self):
        for songs in (False, True):
            with self.subTest(songs=songs), tempfile.TemporaryDirectory() as folder:
                path = str(Path(folder) / 'song.wav'); Path(path).touch()
                app = object.__new__(QuickEdit)
                app._load_library_records = lambda paths, ready, back=None: ready([(p, app._normalized_metadata(app.media.read_metadata(p))) for p in paths])
                app.media = SimpleNamespace(read_metadata=lambda path: {})
                app.library_files = [path]; app.library_sort_mode = 'track'
                app.screen_reader = Mock(); app.accessible_button = Mock()
                dialog = Mock(); back = Mock(); bindings = {}
                dialog.bind.side_effect = lambda key, fn: bindings.update({key: fn})
                with patch('quickedit.tk.Toplevel', return_value=dialog), patch('quickedit.tk.Label'), patch('quickedit.tk.Listbox'), patch('quickedit.tk.Frame'):
                    if songs: app.browse_library('songs', back=back)
                    else: app._library_navigation('Artist', [('Albums', Mock())], back)
                self.assertIs(bindings['<BackSpace>'], bindings['<Alt-Left>'])
                self.assertEqual(bindings['<BackSpace>'](), 'break')
                dialog.destroy.assert_called_once(); back.assert_called_once()

    def test_display_preferences_survive_restart(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder):
            app = object.__new__(QuickEdit)
            app.recent_files = []; app.favorite_files = []
            app.library_display_fields = ['artist', 'title', 'disc']
            app._save_file_history()
            other = object.__new__(QuickEdit)
            other._load_file_history()
            self.assertEqual(other.library_display_fields, ['artist', 'title', 'disc'])

    def test_albums_group_tracks_and_disambiguate_names(self):
        records = [('a', {'album': 'Greatest Hits', 'artist': 'James'}),
                   ('b', {'album': 'Greatest Hits', 'artist': 'James'}),
                   ('c', {'album': 'Greatest Hits', 'artist': 'Other'})]
        self.assertEqual(lib.group_records(records, 'album'),
                         [('Greatest Hits; James', ['a', 'b']), ('Greatest Hits; Other', ['c'])])

    def test_compilation_is_one_album(self):
        records = [(str(i), {'album': 'Collection', 'artist': artist, 'album_artist': 'Various Artists'})
                   for i, artist in enumerate(['One', 'Two'])]
        self.assertEqual(lib.group_records(records, 'album'), [('Collection', ['0', '1'])])

    def test_display_order_and_visibility(self):
        tags = {'title': 'Song', 'artist': 'James', 'album': 'Album', 'track': '2'}
        self.assertEqual(lib.song_label(tags, 'a.wav', ['artist', 'title']), 'James; Song')
        self.assertEqual(lib.song_label({}, 'Fallback.wav', ['title']), 'Fallback')
        self.assertEqual(lib.valid_fields(['artist']), lib.DEFAULT_FIELDS)
        self.assertEqual(lib.valid_fields(['title', {}, 'title']), ['title'])

    def test_folder_scan_recurses_and_deduplicates_overlapping_roots(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); child = root / 'Album'; child.mkdir()
            (root / 'one.WAV').touch(); (child / 'two.mp3').touch(); (child / 'cover.jpg').touch()
            paths, errors = lib.scan_folders([str(root), str(child)])
            self.assertEqual(set(paths), {str(root / 'one.WAV'), str(child / 'two.mp3')})
            self.assertEqual(len(paths), 2); self.assertFalse(errors)

    def test_unavailable_folder_is_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            paths, errors = lib.scan_folders([str(Path(folder) / 'missing')])
            self.assertFalse(paths); self.assertEqual(len(errors), 1)

    def test_artist_navigation_and_back_restore_selection_without_touching_queue(self):
        app = object.__new__(QuickEdit)
        app.media = SimpleNamespace(read_metadata=lambda path: {'artist': path, 'album': 'Album'})
        app._library_navigation = Mock(); app.browse_library = Mock()
        app.library_queue = ['playing']; app.library_queue_index = 0
        app._browse_library_groups('artist', ['James', 'Other'], records=[(p, {'artist': p, 'album': 'Album'}) for p in ['James', 'Other']])
        entries = app._library_navigation.call_args.args[1]
        self.assertEqual([e[0] for e in entries], ['James', 'Other'])
        entries[1][1](1)
        artist_menu = app._library_navigation.call_args
        self.assertEqual(artist_menu.args[0], 'Other')
        artist_menu.args[1][0][1](0)
        self.assertEqual(app.browse_library.call_args.args, ('album', ['Other']))
        artist_menu.args[2]()
        self.assertEqual(app._library_navigation.call_args.args[3], 1)
        self.assertEqual(app.library_queue, ['playing'])
        self.assertEqual(app.library_queue_index, 0)


if __name__ == '__main__':
    unittest.main()
