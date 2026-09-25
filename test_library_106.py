import os
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import library_tools as lib
from media_backend import MediaBackend, MediaError


class CacheTests(unittest.TestCase):
    def test_reuses_tags_and_refreshes_changed_files(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'song.wav'; path.write_bytes(b'one')
            read = Mock(return_value={'title': 'First'})
            cache = lib.MetadataCache(read, dict); cancel = threading.Event()
            self.assertEqual(cache.load([str(path)], cancel)[0][1]['title'], 'First')
            cache.load([str(path)], cancel)
            read.assert_called_once()
            path.write_bytes(b'changed'); read.return_value = {'title': 'Updated'}
            self.assertEqual(cache.load([str(path)], cancel)[0][1]['title'], 'Updated')
            self.assertEqual(read.call_count, 2)
            path.unlink()
            self.assertEqual(cache.load([str(path)], cancel), [])

    def test_cancel_stops_remaining_probes(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / str(i)) for i in range(4)]
            for path in paths: Path(path).touch()
            cancelled = threading.Event()
            def read(path): cancelled.set(); return {}
            reader = Mock(side_effect=read)
            lib.MetadataCache(reader, dict).load(paths, cancelled)
            reader.assert_called_once()

    def test_bad_tags_do_not_abort_other_tracks(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = [str(Path(folder) / str(i)) for i in range(2)]
            for path in paths: Path(path).touch()
            read = Mock(side_effect=[MediaError('bad tags'), {'title': 'Good'}])
            records = lib.MetadataCache(read, dict).load(paths, threading.Event())
            self.assertEqual(records, [(paths[0], {}), (paths[1], {'title': 'Good'})])

    def test_metadata_probe_has_timeout(self):
        backend = object.__new__(MediaBackend); backend.ffprobe = 'probe'
        backend._run = Mock(side_effect=subprocess.TimeoutExpired('probe', 10))
        with self.assertRaises(MediaError): backend.read_metadata('song.wav')
        self.assertEqual(backend._run.call_args.kwargs['timeout'], 10)


class RealTkTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk(); self.root.withdraw()
        self.root.announce = Mock()
        self.root.accessible_button = lambda parent, text, command: tk.Button(parent, text=text, command=command)
        self.root._normalized_metadata = dict
        self.addCleanup(self.root.destroy)

    def pump_until(self, condition, timeout=3):
        deadline = time.monotonic() + timeout
        while not condition() and time.monotonic() < deadline:
            self.root.update(); time.sleep(.005)
        self.assertTrue(condition(), 'Timed out waiting for Tk event loop')

    def test_slow_metadata_does_not_block_ui_and_cancel_prevents_late_view(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'song.wav'); Path(path).touch()
            started = threading.Event(); release = threading.Event(); done = threading.Event()
            self.addCleanup(release.set)
            def read(path):
                started.set(); release.wait(3); done.set(); return {'title': 'Song'}
            self.root.media = SimpleNamespace(read_metadata=read)
            ready = Mock(); tick = Mock()
            start = time.monotonic()
            lib.load_library_records(self.root, [path], ready)
            self.assertLess(time.monotonic() - start, 1)
            self.root.after(10, tick)
            self.pump_until(lambda: started.is_set() and tick.called)
            ready.assert_not_called()
            self.root._library_load['cancel']()
            release.set(); self.assertTrue(done.wait(2))
            settled = Mock()
            self.root.after(100, settled)
            self.pump_until(lambda: settled.called)
            ready.assert_not_called()

    def test_latest_view_wins_and_cached_view_does_not_probe_again(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder) / 'song.wav'); Path(path).touch()
            release = threading.Event(); started = threading.Event()
            self.addCleanup(release.set)
            def read(path): started.set(); release.wait(3); return {'title': 'Song'}
            read = Mock(side_effect=read)
            self.root.media = SimpleNamespace(read_metadata=read)
            old, new, cached = Mock(), Mock(), Mock()
            lib.load_library_records(self.root, [path], old)
            self.pump_until(started.is_set)
            lib.load_library_records(self.root, [path], new)
            release.set(); self.pump_until(lambda: new.called)
            old.assert_not_called(); read.assert_called_once()
            lib.load_library_records(self.root, [path], cached)
            self.pump_until(lambda: cached.called)
            read.assert_called_once()

    def test_shift_selection_speaks_current_folder_even_after_four(self):
        self.root.deiconify()
        widget = tk.Listbox(self.root, selectmode='extended', exportselection=False)
        widget.pack()
        for i in range(7): widget.insert('end', f'Album {i}')
        widget.selection_set(0); widget.selection_anchor(0); widget.activate(0)
        speak = Mock(); lib.bind_folder_announcements(widget, 'Folders', speak)
        self.root.update(); widget.focus_force(); self.root.update(); speak.reset_mock()
        for i in range(1, 6):
            widget.event_generate('<Shift-Down>')
            widget.event_generate('<KeyRelease-Down>', state=1)
            self.root.update()
            self.assertEqual(widget.index('active'), i)
            self.assertEqual(len(widget.curselection()), i + 1)
            self.assertEqual(speak.call_args.args[0], f'Album {i}. {i + 1} folders selected.')
        widget.event_generate('<Shift-Up>'); widget.event_generate('<KeyRelease-Up>', state=1)
        self.root.update()
        self.assertEqual(speak.call_args.args[0], 'Album 4. 5 folders selected.')


if __name__ == '__main__': unittest.main()
