import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from quickedit import QuickEdit

class AlbumOrderTests(unittest.TestCase):
    def test_album_order_and_transport_ignore_global_title_order(self):
        with tempfile.TemporaryDirectory() as folder:
            a=object.__new__(QuickEdit)
            a.library_sort_mode='title'; a.repeat_mode='off'
            a.screen_reader=Mock(); a.accessible_button=Mock(); a.announce=Mock()
            a.play_library_from_start=Mock(); a.document=None
            records=[]
            for filename,tags in [
                ('06 Alpha.wav',{'disc':'1','track':'6','title':'Alpha','artist':'A'}),
                ('01 Zulu.wav',{'disc':'1','track':'1','title':'Zulu','artist':'Z'}),
                ('02 Beta.wav',{'title':'Beta','artist':'B'}),
                ('disc2.wav',{'disc':'2','track':'1','title':'AAA','artist':'A'})]:
                p=str(Path(folder)/filename);Path(p).touch();records.append((p,tags))
            a.library_files=[r[0] for r in records]
            def opened(path,announce=False):
                a.document=SimpleNamespace(source_path=path);return True
            a._open_path=opened
            choices=Mock(); choices.curselection.return_value=(0,)
            callbacks={};choices.bind.side_effect=lambda key,fn,**kwargs: callbacks.update({key:fn})
            with patch('quickedit.tk.Toplevel'),patch('quickedit.tk.Label'),patch('quickedit.tk.Frame'),patch('quickedit.tk.Listbox',return_value=choices):
                a._show_library_records('Album tracks',records,album_tracks=True)
                callbacks['<Return>']()
            expected=[records[i][0] for i in (1,2,0,3)]
            self.assertEqual(a.library_queue,expected)
            for path in expected:
                self.assertEqual(a.document.source_path,path)
                a.play_adjacent_library_song(1)
            a.play_adjacent_library_song(-1)
            self.assertEqual(a.document.source_path,expected[-2])

    def test_album_navigation_explicitly_requests_track_order(self):
        a=object.__new__(QuickEdit);a._library_navigation=Mock();a.browse_library=Mock()
        a._browse_library_groups('album',['song'],records=[('song',{'album':'Album'})])
        a._library_navigation.call_args.args[1][0][1](0)
        self.assertTrue(a.browse_library.call_args.kwargs['album_tracks'])

if __name__=='__main__':unittest.main()
