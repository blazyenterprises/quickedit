import json
import os
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from quickedit import QuickEdit, AudioDocument
from library_tools import bind_first_letter_navigation

class ResumeTests(unittest.TestCase):
    def test_restart_restores_song_position_and_queue_without_playing(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, APPDATA=folder):
            paths=[str(Path(folder)/f'{i}.wav') for i in range(3)]
            for p in paths:Path(p).touch()
            a=object.__new__(QuickEdit)
            a.workspace_mode='library';a.library_queue=[paths[2],paths[0],paths[1]]
            a.document=AudioDocument(1,2,1000,b'\0\0'*10000,paths[0]);a.document.cursor_frame=4321
            a.recent_files=[paths[0]];a.favorite_files=[]
            a._save_file_history()
            b=object.__new__(QuickEdit);b._load_file_history()
            b.refresh_details=Mock();b.announce=Mock();b.play_library_from_start=Mock()
            def opened(path,announce=False):
                b.document=AudioDocument(1,2,1000,b'\0\0'*10000,path)
                b._save_file_history() # Opening normally saves recent-file history.
                return True
            b._open_path=Mock(side_effect=opened)
            b._restore_library_session()
            b._open_path.assert_called_once_with(paths[0],announce=False)
            self.assertEqual(b.document.cursor_frame,4321)
            self.assertEqual(b.library_queue,[paths[2],paths[0],paths[1]])
            self.assertEqual(b.library_queue_index,1)
            self.assertTrue(b.paused)
            b.play_library_from_start.assert_not_called()
            saved=json.loads(Path(b._history_path).read_text())
            self.assertEqual(saved['library_session']['seconds'],4.321)

    def test_unavailable_last_song_does_not_open_or_replace_session(self):
        a=object.__new__(QuickEdit)
        a.library_session={'path':'missing.wav','seconds':5,'queue':['missing.wav']}
        a.announce=Mock();a._open_path=Mock()
        with patch('quickedit.os.path.isfile',return_value=False):a._restore_library_session()
        a._open_path.assert_not_called();self.assertEqual(a.library_session['seconds'],5)

    def test_bad_preferences_are_safe(self):
        self.assertEqual(QuickEdit._validated_library_session(['bad']),{})
        for seconds in ('bad',float('inf'),float('nan'),-4,10**1000):
            self.assertEqual(QuickEdit._validated_library_session({'path':'song','seconds':seconds,'queue':42})['seconds'],0)

    def test_close_captures_current_playback_position_before_stopping(self):
        a=object.__new__(QuickEdit);a.workspace_mode='library';a.playing=True
        a._confirm_document_change=Mock(return_value=True)
        events=[]
        a._sync_transport_cursor=lambda:events.append('sync')
        a._save_file_history=lambda:events.append('save')
        a.stop_effect_preview=Mock();a.stop=lambda **kw:events.append('stop')
        with patch('quickedit.tk.Tk.destroy'):a.destroy()
        self.assertEqual(events,['sync','save','stop'])

class FirstLetterTests(unittest.TestCase):
    def setUp(self):
        self.root=tk.Tk();self.addCleanup(self.root.destroy)
        self.list=tk.Listbox(self.root);self.list.pack()
        for row in ('Track 1; Alpha','Track 2; Ray','Track 3; Roger','Track 4; Zed'):self.list.insert('end',row)
        self.list.selection_set(0);self.list.activate(0)
        self.speak=Mock();self.list.bind('<<ListboxSelect>>',lambda e:self.speak(self.list.get(self.list.curselection()[0])))
        bind_first_letter_navigation(self.list,['Alpha','Ray','Roger','Zed'])
        self.root.update();self.list.focus_force();self.root.update()

    def press(self,key,state=0):
        self.list.event_generate('<KeyPress>',keysym=key,state=state);self.root.update()

    def test_letter_uses_name_and_repeated_letter_cycles_and_wraps(self):
        for index in (1,2,1):
            self.press('r');self.assertEqual(self.list.curselection(),(index,))
        self.assertEqual(self.speak.call_count,3)
        self.assertEqual(self.speak.call_args.args[0],'Track 2; Ray')

    def test_uppercase_and_arrow_and_unmatched_letter(self):
        self.press('Z',1);self.assertEqual(self.list.curselection(),(3,))
        self.press('x');self.assertEqual(self.list.curselection(),(3,))
        self.press('Up');self.assertEqual(self.list.curselection(),(2,))

    def test_control_shortcuts_do_not_navigate(self):
        self.press('r',4);self.assertEqual(self.list.curselection(),(0,))

if __name__=='__main__':unittest.main()
