import ctypes
import json
import queue
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.parse import unquote
from unittest.mock import patch, Mock
from keyscope.score import parse_score, decode_score, plan_score, play_events, Event, output_stem, read_score
from keyscope.simulator_launch import list_scores, launch_simulator
from keyscope.keyboard import INPUT, Keyboard
from keyscope.simulator_settings import read_hotkey, save_hotkey, read_hotkeys, save_hotkeys, HOTKEYS, KeyEdge
from keyscope.simulator_ui import Simulator
from server import download_header

class ScoreTests(unittest.TestCase):
    def test_chords_encoding_duplicates_and_comments(self):
        source='# seconds keys\n0.00\tq,N\n0.00 Q,A\n.03 Q\n.10\n'
        for encoded in (source.encode('utf-8-sig'),source.encode('utf-16')):
            rows=parse_score(decode_score(encoded))
            self.assertEqual(rows[0].keys,('Q','N','A'))
            self.assertEqual(rows[-1].keys,())

    def test_reject_invalid_or_empty_score(self):
        for text in ('','0 CTRL,Q','0 QQ','nan Q','-1 Q','inf Q','86401 Q','2 Q\n1 A','oops Q','0','0 😀'):
            with self.subTest(text=text), self.assertRaises(ValueError): parse_score(text)

    def test_merge_continuous_frames_keep_repeats_and_chords(self):
        events,count=plan_score(parse_score('0 Q,N\n.03 Q,N\n.06 Q\n.3 Q'),hold_ms=40,merge_ms=80)
        self.assertEqual(count,3)
        self.assertEqual(events[0],Event(0,('Q','N'),()))
        self.assertIn(Event(.06,(),('N',)),events)
        self.assertIn(Event(.1,(),('Q',)),events)
        self.assertIn(Event(.3,('Q',),()),events)

    def test_missing_key_is_explicit_release(self):
        events,count=plan_score(parse_score('0 Q\n.02 N\n.04 Q'))
        self.assertEqual(count,3)
        self.assertIn(Event(.02,('N',),('Q',)),events)

    def test_per_row_taps_never_overlap_same_key(self):
        events,count=plan_score(parse_score('0 Q\n.01 Q\n.02 Q'),mode='tap')
        self.assertEqual(count,3)
        held=set()
        for e in events:
            held.difference_update(e.up)
            self.assertFalse(held.intersection(e.down))
            held.update(e.down)
        self.assertEqual(held,set())

    def test_speed_scales_first_note_and_release(self):
        events,_=plan_score(parse_score('2 Q'),speed=2)
        self.assertEqual(events,(Event(1,('Q',),()),Event(1.02,(),('Q',))))

    def test_invalid_settings(self):
        for kwargs in ({'speed':0},{'speed':float('nan')},{'hold_ms':0},{'merge_ms':-1},{'mode':'bad'}):
            with self.assertRaises(ValueError): plan_score(parse_score('0 Q'),**kwargs)

    def test_unicode_filename_and_http_disposition(self):
        self.assertEqual(output_stem('乐曲 01.mp4'),'乐曲 01')
        self.assertLessEqual(len(output_stem('a'*300+'.mp4')),100)
        name='乐曲 01_keys.txt'
        header=download_header(name)
        header.encode('ascii')
        self.assertEqual(unquote(header.split("filename*=UTF-8''")[1]),name)

    def test_recursive_txt_list_and_load(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'job').mkdir()
            score=root/'job/乐曲_keys.txt'; score.write_text('0 Q','utf-8')
            (root/'ignore.csv').write_text('csv','utf-8')
            self.assertEqual(list_scores(root)['files'][0]['path'],str(score))
            self.assertEqual(read_score(score)[0].keys,('Q',))
            with self.assertRaises(ValueError): read_score(root/'ignore.csv')

class PlaybackTests(unittest.TestCase):
    def replay(self,events,send,guard=lambda:None,stop=None):
        now=[0.0]
        class Sink:
            def send(self,down,up):send(down,up)
        play_events(events,Sink(),stop or threading.Event(),clock=lambda:now[0],
                    wait=lambda n:now.__setitem__(0,now[0]+n),guard=guard)

    def test_timing_and_simultaneous_keys(self):
        calls=[]
        self.replay((Event(2,('Q','N')),Event(2.04,(),('Q','N'))),lambda d,u:calls.append((d,u)))
        self.assertEqual(calls,[(('Q','N'),()),((),('Q','N'))])

    def test_stop_releases_held_keys(self):
        stop=threading.Event(); calls=[]
        def send(down,up): calls.append((down,up)); stop.set()
        self.replay((Event(0,('Q','N')),Event(10,(),('Q','N'))),send,stop=stop)
        self.assertEqual(set(calls[-1][1]),{'Q','N'})
        self.assertEqual(len(calls),2)

    def test_partial_input_error_still_attempts_release(self):
        calls=[]
        def send(down,up):
            calls.append((down,up))
            if down: raise OSError('partial input')
        with self.assertRaises(OSError): self.replay((Event(0,('Q','N')),),send)
        self.assertEqual(set(calls[-1][1]),{'Q','N'})

    def test_focus_loss_releases_held_keys(self):
        calls=[]
        def guard():
            if calls: raise InterruptedError('focus lost')
        with self.assertRaises(InterruptedError):
            self.replay((Event(0,('Q',)),Event(10,(),('Q',))),lambda d,u:calls.append((d,u)),guard)
        self.assertEqual(calls[-1],((),('Q',)))

    def test_cancel_before_first_note_sends_nothing(self):
        stop=threading.Event(); stop.set(); calls=[]
        self.replay((Event(2,('Q',)),),lambda d,u:calls.append((d,u)),stop=stop)
        self.assertEqual(calls,[])

    def test_pause_freezes_clock_and_restores_held_chord(self):
        now=[0.0]; pause=threading.Event(); stop=threading.Event(); calls=[]; did_pause=[False]
        class Sink:
            def send(self,down,up):calls.append((round(now[0],3),down,up))
        def guard():
            if now[0]>=.1 and not did_pause[0]:pause.set(); did_pause[0]=True
        def resume():return now[0]>=.6
        play_events((Event(0,('Q','N')),Event(.3,(),('Q','N')),Event(.5,('A',)),Event(.54,(),('A',))),Sink(),stop,
            clock=lambda:now[0],wait=lambda n:now.__setitem__(0,round(now[0]+n,6)),guard=guard,pause=pause,resume_ready=resume)
        self.assertEqual(calls[1],(.1,(),('N','Q')))
        self.assertEqual(calls[2],(.6,('N','Q'),()))
        self.assertEqual(calls[3],(.8,(),('Q','N')))
        self.assertEqual(calls[4],(1.0,('A',),()))
        self.assertFalse(pause.is_set())

    def test_stop_while_paused_does_not_restore_keys(self):
        now=[0.0]; pause=threading.Event(); stop=threading.Event(); calls=[]
        class Sink:
            def send(self,down,up):
                calls.append((down,up))
                if down:pause.set()
        def wait(n):now[0]+=n; stop.set()
        play_events((Event(0,('Q',)),Event(10,(),('Q',))),Sink(),stop,clock=lambda:now[0],wait=wait,pause=pause)
        self.assertEqual(calls,[(('Q',),()),((),('Q',))])

    def test_pause_before_first_note_has_no_input_until_resume(self):
        now=[0.0]; pause=threading.Event(); pause.set(); calls=[]
        class Sink:
            def send(self,down,up):calls.append((round(now[0],3),down,up))
        play_events((Event(.2,('Q',)),Event(.24,(),('Q',))),Sink(),threading.Event(),clock=lambda:now[0],
            wait=lambda n:now.__setitem__(0,round(now[0]+n,6)),pause=pause,resume_ready=lambda:now[0]>=1)
        self.assertEqual(calls[0],(1.2,('Q',),()))

    def test_hotkey_edges_and_portable_persistence(self):
        key=KeyEdge()
        self.assertEqual([key.update(v) for v in (False,True,True,False,True)],[False,True,False,False,True])
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'settings.json'
            self.assertEqual(read_hotkey(path),'F6')
            save_hotkey('F10',path)
            self.assertEqual(read_hotkey(path),'F10')
            with self.assertRaises(ValueError):save_hotkey('F8',path)
            self.assertEqual(read_hotkey(path),'F10')

    def test_windows_input_layout_and_dry_run(self):
        self.assertEqual(ctypes.sizeof(INPUT),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)
        keyboard=Keyboard(dry_run=True)
        with patch.object(keyboard.user,'SendInput',side_effect=AssertionError('Real input must never be sent')):
            keyboard.send(('Q','N'),())
            keyboard.send((),('Q','N'))

    def test_both_hotkeys_persist_and_can_swap_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'settings.json'
            self.assertEqual(read_hotkeys(path),('F6','F8'))
            save_hotkeys('F8','F6',path)
            self.assertEqual(read_hotkeys(path),('F8','F6'))
            for pair in (('F10','F10'),('unknown','F7'),('F6',[])):
                with self.assertRaises(ValueError):save_hotkeys(*pair,path)
                self.assertEqual(read_hotkeys(path),('F8','F6'))
            self.assertEqual(list(Path(temp).iterdir()),[path])

    def test_legacy_and_corrupt_hotkey_settings(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'settings.json'
            for values,expected in (
                ({'toggle_hotkey':'F10'},('F10','F8')),
                ({'toggle_hotkey':'F8','stop_hotkey':'F8'},('F8','F6')),
                ({'toggle_hotkey':[],'stop_hotkey':{}},('F6','F8')),
                ([],('F6','F8')),
            ):
                path.write_text(json.dumps(values),'utf-8')
                self.assertEqual(read_hotkeys(path),expected)
            path.write_text('invalid json','utf-8')
            self.assertEqual(read_hotkeys(path),('F6','F8'))

    def simulator_stub(self):
        ui=Simulator.__new__(Simulator)
        ui.hotkeys=('F6','F10'); ui.hotkey_edge=KeyEdge()
        ui.keyboard=Mock(); ui.keyboard.pressed.return_value=False
        ui.worker=Mock(); ui.worker.is_alive.return_value=True
        ui.stop=threading.Event(); ui.pause=threading.Event(); ui.queue=queue.Queue()
        ui.phase='waiting'; ui.status='idle'; ui.resume_at=None
        ui.settings_window=None; ui.closing=False; ui.root=Mock()
        ui.status_label=Mock(); ui.start_button=Mock(); ui.stop_button=Mock(); ui.hint=Mock()
        return ui

    def test_stop_guard_uses_new_binding_and_releases_held_keys(self):
        ui=self.simulator_stub(); held=set()
        ui.keyboard.pressed.side_effect=lambda key:key in held
        held.add(HOTKEYS['F8'])
        ui.guard()  # The former stop key no longer interrupts playback.
        calls=[]
        def send(down,up):
            calls.append((down,up))
            if down:held.add(HOTKEYS['F10'])
        with self.assertRaisesRegex(InterruptedError,'F10'):
            self.replay((Event(0,('Q',)),Event(10,(),('Q',))),send,guard=ui.guard)
        self.assertEqual(calls,[(('Q',),()),((),('Q',))])

    def test_stop_poll_has_priority_over_start_and_works_while_paused(self):
        ui=self.simulator_stub(); ui.render_state=Mock(); ui.toggle_playback=Mock()
        ui.pause.set()
        ui.keyboard.pressed.side_effect=lambda key:key==HOTKEYS['F8']
        ui.poll(); self.assertFalse(ui.stop.is_set())
        ui.keyboard.pressed.side_effect=lambda key:key in (HOTKEYS['F6'],HOTKEYS['F10'])
        ui.poll(); self.assertTrue(ui.stop.is_set())
        ui.toggle_playback.assert_not_called()

    def test_stop_caption_tracks_binding_in_both_languages(self):
        ui=self.simulator_stub()
        for language in ('zh','en'):
            ui.language=language; ui.render_state()
            self.assertIn('F10',ui.stop_button.configure.call_args.kwargs['text'])
            self.assertIn('F10',ui.hint.configure.call_args.kwargs['text'])
            self.assertNotIn('F8',ui.hint.configure.call_args.kwargs['text'])

    def test_elevated_launch_contract_and_cancellation(self):
        class Function:
            def __init__(self,callback): self.callback=callback
            def __call__(self,*args): return self.callback(*args)
        class Library: pass
        shell,kernel=Library(),Library(); observed={}
        def execute(pointer):
            info=pointer._obj
            observed.update(verb=info.lpVerb,file=info.lpFile,args=info.lpParameters,directory=info.lpDirectory,flags=info.fMask)
            info.hProcess=123
            return True
        shell.ShellExecuteExW=Function(execute)
        kernel.GetProcessId=Function(lambda h:456)
        kernel.CloseHandle=Function(lambda h:True)
        with patch('keyscope.simulator_launch.ctypes.WinDLL',side_effect=lambda name,**kw:shell if name=='shell32' else kernel):
            self.assertEqual(launch_simulator('runs',language='en')['pid'],456)
            self.assertEqual(observed['verb'],'runas')
            self.assertTrue(observed['file'].endswith('pythonw.exe'))
            self.assertIn('--language en',observed['args'])
            self.assertFalse(observed['flags'] & 0x8000)  # no parent console inheritance
            shell.ShellExecuteExW=Function(lambda info:False)
            with patch('keyscope.simulator_launch.ctypes.get_last_error',return_value=1223), self.assertRaisesRegex(OSError,'cancelled'):
                launch_simulator()

if __name__=='__main__': unittest.main()
