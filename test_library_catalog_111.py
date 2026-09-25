import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from library_tools import MetadataCache
from quickedit import QuickEdit

class CatalogTests(unittest.TestCase):
    def test_restart_browsing_never_touches_audio_files(self):
        with tempfile.TemporaryDirectory() as folder:
            song=str(Path(folder)/'song.wav');Path(song).touch()
            database=str(Path(folder)/'library.sqlite3')
            cache=MetadataCache(lambda p: {'album':'Album','title':'Song','track':'2'},dict,database)
            cache.load([song],threading.Event())
            read=Mock(side_effect=AssertionError('Unexpected metadata probe'))
            restored=MetadataCache(read,dict,database)
            with patch('library_tools.os.stat',side_effect=AssertionError('Unexpected file access')):
                records=restored.snapshot([song]);restored.index_async([song])
            self.assertEqual(records[0][1]['track'],'2')
            read.assert_not_called();self.assertIsNone(restored.worker)

    def test_only_new_album_is_indexed_and_duplicates_are_coalesced(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/str(i)) for i in range(3)]
            for p in paths:Path(p).touch()
            started=threading.Event();release=threading.Event()
            def read(p):
                started.set();release.wait(2);return {'title':p}
            read=Mock(side_effect=read);cache=MetadataCache(read,dict)
            cache.store(paths[0],(0,0),{'title':'Existing'})
            cache.index_async(paths);self.assertTrue(started.wait(2))
            worker=cache.worker
            cache.index_async(paths)
            self.assertEqual(len(cache.snapshot(paths)),3)
            release.set();worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual([c.args[0] for c in read.call_args_list],paths[1:])

    def test_explicit_refresh_updates_persistent_tags(self):
        with tempfile.TemporaryDirectory() as folder:
            song=str(Path(folder)/'song.wav');Path(song).touch()
            read=Mock(return_value={'title':'Old'});cache=MetadataCache(read,dict)
            cache.load([song],threading.Event())
            read.return_value={'title':'New'}
            cache.load([song],threading.Event(),refresh=True)
            self.assertEqual(cache.snapshot([song])[0][1]['title'],'New')

    def test_shuffle_builds_paths_and_opens_only_selected_song(self):
        a=object.__new__(QuickEdit)
        a.library_sort_mode='shuffle';a.document=None
        a.screen_reader=Mock();a.accessible_button=Mock()
        a.play_library_from_start=Mock()
        def opened(path,announce=False):
            a.document=SimpleNamespace(source_path=path);return True
        a._open_path=Mock(side_effect=opened)
        choices=Mock();choices.curselection.return_value=(1,)
        callbacks={};choices.bind.side_effect=lambda key,fn,**kwargs:callbacks.update({key:fn})
        records=[(f'{i}.wav',{'title':str(i)}) for i in range(100)]
        with patch('quickedit.tk.Toplevel'),patch('quickedit.tk.Label'),patch('quickedit.tk.Frame'),patch('quickedit.tk.Listbox',return_value=choices),patch('quickedit.random.shuffle',side_effect=lambda items:items.reverse()):
            a._show_library_records('songs',records)
            a._open_path.assert_not_called()
            callbacks['<Return>']()
        a._open_path.assert_called_once_with('98.wav',announce=False)
        self.assertEqual(len(a.library_queue),100)

    def test_next_checks_only_target_even_with_large_queue(self):
        a=object.__new__(QuickEdit)
        a.library_files=[f'{i}.wav' for i in range(10000)]
        a.library_queue=list(a.library_files)
        a.document=SimpleNamespace(source_path='5000.wav')
        a.repeat_mode='off';a._open_path=Mock(return_value=True)
        a.play_library_from_start=Mock();a.announce=Mock()
        with patch('quickedit.os.path.isfile',return_value=True) as exists:
            a.play_adjacent_library_song(1)
        exists.assert_called_once_with('5001.wav')
        a._open_path.assert_called_once_with('5001.wav',announce=False)

    def test_missing_target_is_skipped_without_scanning_other_tracks(self):
        a=object.__new__(QuickEdit);a.library_files=['a','missing','c','d']
        a.library_queue=list(a.library_files);a.document=SimpleNamespace(source_path='a')
        a.repeat_mode='off';a._open_path=Mock(return_value=True)
        a.play_library_from_start=Mock();a.announce=Mock()
        with patch('quickedit.os.path.isfile',side_effect=lambda p:p!='missing') as exists:
            a.play_adjacent_library_song(1)
        self.assertEqual([c.args[0] for c in exists.call_args_list],['missing','c'])
        self.assertEqual(a.library_files,['a','missing','c','d'])
        a._open_path.assert_called_once_with('c',announce=False)

if __name__=='__main__':unittest.main()
