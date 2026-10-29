"""Standalone Tk desktop UI; playback does not depend on the HTTP server."""
import queue
import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog
from .score import read_score, plan_score, play_events, Event
from .simulator_launch import list_scores, is_admin
from .keyboard import Keyboard, playback_lock
from .simulator_settings import HOTKEYS, KeyEdge, read_hotkeys, save_hotkeys
from .simulator_theme import COLORS, apply_theme

from .localization import LABELS, LANGUAGE_NAMES

class Simulator:
    def __init__(self, root, directory, score=None, language='zh', dry_run=False):
        self.root, self.language, self.dry_run = root, language, dry_run
        self.keyboard = Keyboard(dry_run)
        self.queue = queue.Queue()
        self.stop = threading.Event()
        self.pause = threading.Event()
        self.resume_at = None
        self.target = None
        self.phase = 'waiting'
        self.pause_reason = ''
        self.auto_paused_at = -1.0
        self.hotkeys = read_hotkeys()
        self.hotkey_edge = KeyEdge(self.keyboard.pressed(HOTKEYS[self.hotkey]))
        self.settings_window = None
        self.worker = None
        self.closing = False
        self.rows, self.files, self.path = [], [], None
        self.status = 'idle'
        self.labels = []
        self.controls = []
        self.directory = tk.StringVar(value=str(directory))
        self.speed, self.hold, self.merge, self.countdown = [tk.StringVar(value=s) for s in ('1.0', '40', '80', '3')]
        root.geometry('900x680')
        root.minsize(760, 620)
        apply_theme(root)
        body = ttk.Frame(root, padding=22)
        body.pack(fill='both', expand=True)
        body.columnconfigure(0, weight=1)
        body.rowconfigure(9, weight=1)
        top = ttk.Frame(body); top.grid(row=0, column=0, sticky='ew', pady=(0,18))
        self.status_label = ttk.Label(top,style='Status.TLabel'); self.status_label.pack(side='left')
        self.lang_button = ttk.Button(top, command=self.toggle_language, width=8); self.lang_button.pack(side='right')
        self.permission_label = ttk.Label(top,style='Muted.TLabel'); self.permission_label.pack(side='right', padx=16)
        self.button(top,'settings',self.open_settings,controlled=False).pack(side='right')
        self.label(body, 'directory').grid(row=1, column=0, sticky='w')
        pathrow = ttk.Frame(body); pathrow.grid(row=2, column=0, sticky='ew', pady=(5,14)); pathrow.columnconfigure(0,weight=1)
        self.entry = ttk.Entry(pathrow, textvariable=self.directory); self.entry.grid(row=0,column=0,sticky='ew'); self.controls.append(self.entry)
        self.button(pathrow,'browse',self.browse_directory).grid(row=0,column=1,padx=(8,0))
        self.button(pathrow,'refresh',self.refresh).grid(row=0,column=2,padx=(8,0))
        self.label(body,'score').grid(row=3,column=0,sticky='w')
        scorerow=ttk.Frame(body); scorerow.grid(row=4,column=0,sticky='ew',pady=(5,6)); scorerow.columnconfigure(0,weight=1)
        self.select=ttk.Combobox(scorerow,state='readonly'); self.select.grid(row=0,column=0,sticky='ew'); self.controls.append(self.select)
        self.select.bind('<<ComboboxSelected>>',lambda e:self.load(self.files[self.select.current()]['path']))
        self.button(scorerow,'open',self.open_file).grid(row=0,column=1,padx=(8,0))
        self.info=ttk.Label(body,style='Muted.TLabel'); self.info.grid(row=5,column=0,sticky='w',pady=(0,16))
        options=ttk.Frame(body); options.grid(row=6,column=0,sticky='ew')
        for column,(key,variable) in enumerate((('speed',self.speed),('hold',self.hold),('merge',self.merge),('countdown',self.countdown))):
            options.columnconfigure(column,weight=1)
            self.label(options,key).grid(row=0,column=column,sticky='w',padx=(0,10))
            entry=ttk.Entry(options,textvariable=variable,width=10); entry.grid(row=1,column=column,sticky='ew',padx=(0,10),pady=(5,12)); self.controls.append(entry)
        self.label(options,'mode').grid(row=2,column=0,sticky='w')
        self.mode=ttk.Combobox(options,state='readonly',width=24); self.mode.grid(row=2,column=1,columnspan=2,sticky='ew',padx=(0,10)); self.controls.append(self.mode)
        actions=ttk.Frame(body); actions.grid(row=7,column=0,sticky='ew',pady=(18,8))
        self.start_button=self.button(actions,'start',self.toggle_playback,controlled=False,style='Start.TButton'); self.start_button.pack(side='left')
        self.stop_button=self.button(actions,'stop',lambda:self.stop.set(),controlled=False,style='Stop.TButton'); self.stop_button.pack(side='left',padx=8); self.stop_button.state(['disabled'])
        self.elapsed=ttk.Label(actions,text='0.00 s'); self.elapsed.pack(side='right')
        self.hint=ttk.Label(body,wraplength=810,style='Muted.TLabel'); self.hint.grid(row=8,column=0,sticky='w',pady=(0,12))
        logframe=ttk.Frame(body); logframe.grid(row=9,column=0,sticky='nsew'); logframe.columnconfigure(0,weight=1); logframe.rowconfigure(1,weight=1)
        self.label(logframe,'log').grid(row=0,column=0,sticky='w',pady=(0,5))
        self.log_widget=tk.Text(logframe,height=7,wrap='word',state='disabled',
            bg=COLORS['slate_900'],fg=COLORS['nav_text'],insertbackground=COLORS['surface'],
            selectbackground=COLORS['highlight_dark'],selectforeground=COLORS['surface'],
            highlightthickness=1,highlightbackground=COLORS['line'],highlightcolor=COLORS['highlight'],
            relief='flat',font=('Consolas',9),padx=10,pady=8)
        self.log_widget.grid(row=1,column=0,sticky='nsew')
        scroll=ttk.Scrollbar(logframe,command=self.log_widget.yview); scroll.grid(row=1,column=1,sticky='ns'); self.log_widget.configure(yscrollcommand=scroll.set)
        for variable in (self.speed,self.hold,self.merge): variable.trace_add('write',lambda *args:self.render_info())
        self.mode.bind('<<ComboboxSelected>>',lambda e:self.render_info())
        self.translate()
        self.refresh()
        if score: self.load(score)
        self.log('Simulator ready. No keys are sent until Start is pressed.')
        if dry_run: self.log('DRY RUN: keyboard input is disabled.')
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.after(40,self.poll)

    def t(self,key): return LABELS[key][self.language=='en']

    @property
    def hotkey(self): return self.hotkeys[0]

    @property
    def stop_hotkey(self): return self.hotkeys[1]

    def label(self,parent,key):
        widget=ttk.Label(parent,style='Muted.TLabel'); self.labels.append((widget,key)); return widget

    def button(self,parent,key,command,controlled=True,**kwargs):
        widget=ttk.Button(parent,command=command,**kwargs); self.labels.append((widget,key))
        if controlled: self.controls.append(widget)
        return widget

    def translate(self):
        self.root.title('Key Press Detection - '+self.t('title'))
        for widget,key in self.labels: widget.configure(text=self.t(key))
        self.lang_button.configure(text=LANGUAGE_NAMES['zh' if self.language=='en' else 'en'])
        self.permission_label.configure(text=self.t('dry' if self.dry_run else 'admin' if is_admin() else 'standard'))
        mode=max(0,self.mode.current()); self.mode.configure(values=self.t('modes')); self.mode.current(mode)
        self.render_state(); self.render_info()

    def toggle_language(self):
        self.language='en' if self.language=='zh' else 'zh'; self.translate()

    def log(self,message):
        self.log_widget.configure(state='normal')
        self.log_widget.insert('end',f'{time.strftime("%H:%M:%S")}  {message}\n')
        if int(self.log_widget.index('end-1c').split('.')[0])>600: self.log_widget.delete('1.0','101.0')
        self.log_widget.see('end'); self.log_widget.configure(state='disabled')

    def refresh(self):
        try:
            self.files=list_scores(self.directory.get())['files']
            self.select.configure(values=[f['relative'] for f in self.files])
            if self.path:
                found=next((i for i,f in enumerate(self.files) if Path(f['path'])==self.path),None)
                if found is not None: self.select.current(found)
                else: self.select.set(str(self.path))
            elif self.files: self.select.current(0); self.load(self.files[0]['path'])
            else: self.select.set(self.t('empty'))
        except (ValueError,OSError) as exc: self.log(f'ERROR: {exc}')

    def browse_directory(self):
        path=filedialog.askdirectory(parent=self.root,title=self.t('directory'))
        if path: self.directory.set(path); self.path=None; self.rows=[]; self.refresh(); self.render_info()

    def open_file(self):
        path=filedialog.askopenfilename(parent=self.root,title=self.t('open'),filetypes=[('TXT','*.txt')])
        if path: self.load(path)

    def load(self,path):
        try:
            rows=read_score(path)
            self.path=Path(path).resolve(); self.rows=rows
            self.select.set(str(self.path)); self.render_info()
            self.log(f'Loaded {self.path.name}: {len(rows)} timestamp rows.')
        except (ValueError,OSError) as exc:
            self.rows=[]; self.path=None; self.render_info(); self.log(f'ERROR: {exc}')

    def plan(self):
        return plan_score(self.rows,float(self.hold.get()),float(self.merge.get()),float(self.speed.get()),'tap' if self.mode.current()==1 else 'merge')

    def render_info(self):
        if not self.rows: self.info.configure(text=self.t('selected')); return
        try:
            events,count=self.plan()
            self.info.configure(text=self.t('info').format(rows=len(self.rows),notes=count,seconds=events[-1].time if events else 0))
        except ValueError: self.info.configure(text='—')

    def render_state(self):
        active=self.status in ('waiting','playing','paused')
        if active and self.pause.is_set():
            state='waiting' if self.resume_at is not None else 'paused'
        else: state=self.status
        caption=self.t(state)
        if active and self.resume_at is not None:
            caption+=f' {max(0,self.resume_at-time.perf_counter()):.1f} s'
        self.status_label.configure(text=caption)
        button='resume' if state=='paused' else 'pause' if active else 'start'
        self.start_button.configure(text=self.t(button))
        self.stop_button.configure(text=self.t('stop').format(stop_hotkey=self.stop_hotkey))
        self.hint.configure(text=self.t('hint').format(hotkey=self.hotkey,stop_hotkey=self.stop_hotkey))

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift(); return
        window=tk.Toplevel(self.root); self.settings_window=window
        window.configure(bg=COLORS['paper'])
        window.title(self.t('settings')); window.resizable(False,False); window.transient(self.root)
        panel=ttk.Frame(window,padding=22); panel.pack(fill='both',expand=True)
        ttk.Label(panel,text=self.t('hotkey')).pack(anchor='w')
        choice=ttk.Combobox(panel,values=list(HOTKEYS),state='readonly',width=25)
        choice.set(self.hotkey); choice.pack(fill='x',pady=(8,10))
        ttk.Label(panel,text=self.t('stop_hotkey')).pack(anchor='w')
        stop_choice=ttk.Combobox(panel,values=list(HOTKEYS),state='readonly',width=25)
        stop_choice.set(self.stop_hotkey); stop_choice.pack(fill='x',pady=(8,10))
        error=ttk.Label(panel,style='Error.TLabel'); error.pack(anchor='w',pady=(0,10))
        def save():
            try:
                toggle,stop=choice.get(),stop_choice.get()
                if toggle==stop:
                    error.configure(text=self.t('hotkey_conflict')); return
                save_hotkeys(toggle,stop)
                self.hotkey_edge=KeyEdge(self.keyboard.pressed(HOTKEYS[toggle]))
                self.hotkeys=(toggle,stop)
                self.log(f'Hotkeys saved: Start/Pause = {toggle}; Stop = {stop}.')
                window.destroy(); self.settings_window=None; self.render_state()
            except (OSError,ValueError) as exc:
                error.configure(text=self.t('settings_error')); self.log(f'ERROR: {exc}')
        ttk.Button(panel,text=self.t('save'),command=save,style='Start.TButton').pack(anchor='e')

    def request_pause(self,reason='Paused by user.',automatic=False):
        if self.pause.is_set(): return
        self.resume_at=None; self.pause_reason=reason
        if automatic:self.auto_paused_at=time.perf_counter()
        self.pause.set()

    def toggle_playback(self,source='button'):
        if not (self.worker and self.worker.is_alive()):
            self.start(); return
        if self.pause.is_set() and self.resume_at is None:
            # A click that focuses this window can trigger automatic pause before
            # the button command arrives. Do not turn that same click into Resume.
            if source=='button' and time.perf_counter()-self.auto_paused_at<.3:return
            delay=float(self.countdown.get()) if source=='button' else 0
            self.resume_at=time.perf_counter()+delay
            self.log(f'Resume requested: {delay:g} s countdown.')
        elif self.resume_at is not None:
            self.resume_at=None
            self.log('Resume cancelled; playback remains paused.')
        else:self.request_pause()
        self.render_state()

    def start(self):
        if self.worker and self.worker.is_alive(): return
        try:
            if not self.rows: raise ValueError('Select a valid TXT score first.')
            events,count=self.plan(); delay=float(self.countdown.get())
            if not 1<=delay<=30: raise ValueError('Countdown must be between 1 and 30 seconds.')
        except ValueError as exc: self.log(f'ERROR: {exc}'); return
        self.stop.clear(); self.pause.clear(); self.resume_at=None; self.target=None
        self.status=self.phase='waiting'; self.pause_reason=''; self.auto_paused_at=-1
        for control in self.controls: control.state(['disabled'])
        self.stop_button.state(['!disabled']); self.render_state()
        self.log(f'Start requested: {count} key presses, speed {self.speed.get()}, countdown {delay:g} s.')
        self.worker=threading.Thread(target=self.run,args=(events,delay),name='Keyboard-playback',daemon=False)
        self.worker.start()

    def guard(self):
        stop=self.stop_hotkey
        if self.keyboard.pressed(HOTKEYS[stop]): raise InterruptedError(f'Stopped by {stop}.')
        if self.phase=='playing' and self.target is not None:
            reason=self.keyboard.pause_reason(self.target)
            if reason:self.request_pause(reason,automatic=True)

    def resume_ready(self):
        deadline=self.resume_at
        if deadline is None or time.perf_counter()<deadline:return False
        self.resume_at=None
        try:
            if self.phase=='playing':
                if self.target is None:self.target=self.keyboard.target()
                reason=self.keyboard.pause_reason(self.target)
                if reason:raise ValueError('Focus the original game window and press the Start/Pause hotkey to resume.')
        except ValueError as exc:
            self.queue.put(('log',str(exc))); self.queue.put(('status','paused')); return False
        return True

    def run(self,events,delay):
        status='completed'
        last_tick=[-1.0]
        def tick(value):
            now=time.perf_counter()
            if now-last_tick[0]>=.05:
                last_tick[0]=now; self.queue.put(('time',value))
        def paused():
            self.queue.put(('status','paused')); self.queue.put(('log',self.pause_reason or 'Playback paused.'))
        def resumed():
            self.queue.put(('status',self.phase)); self.queue.put(('log','Playback resumed.'))
        options=dict(clock=time.perf_counter,wait=self.stop.wait,guard=self.guard,pause=self.pause,
                     resume_ready=self.resume_ready,on_pause=paused,on_resume=resumed)
        try:
            with playback_lock():
                play_events((Event(delay),),self.keyboard,self.stop,tick=lambda t:tick(t-delay),**options)
                if not self.stop.is_set():
                    self.phase='playing'
                    try:self.target=self.keyboard.target()
                    except ValueError:
                        self.request_pause('Paused: focus the game and press the Start/Pause hotkey.',automatic=True)
                    self.queue.put(('status','playing'))
                    self.queue.put(('log',f'Playback ready. {self.hotkey} toggles pause; {self.stop_hotkey} stops.'))
                    play_events(events,self.keyboard,self.stop,tick=tick,progress=lambda t:self.queue.put(('time',t)),**options)
                if self.stop.is_set():status='stopped'
        except InterruptedError as exc: status='stopped'; self.queue.put(('log',str(exc)))
        except Exception as exc: status='failed'; self.queue.put(('log',f'ERROR: {exc}'))
        finally:self.queue.put(('done',status))

    def poll(self):
        # High-bit edge detection: holding a hotkey never repeatedly toggles it.
        toggle,stop=self.hotkeys
        pressed=self.keyboard.pressed(HOTKEYS[toggle])
        stopping=self.keyboard.pressed(HOTKEYS[stop])
        if self.hotkey_edge.update(pressed) and not stopping and not self.closing and not (self.settings_window and self.settings_window.winfo_exists()):
            self.toggle_playback('hotkey')
        if self.worker and self.worker.is_alive() and stopping:self.stop.set()
        while True:
            try:kind,value=self.queue.get_nowait()
            except queue.Empty:break
            if kind=='log':self.log(value)
            elif kind=='time':self.elapsed.configure(text=f'{value:.2f} s')
            elif kind in ('status','done'):
                self.status=value
                if kind=='done':
                    self.pause.clear(); self.resume_at=None
                    for control in self.controls:control.state(['!disabled'])
                    self.stop_button.state(['disabled']); self.log(f'Playback {value}.')
        self.render_state()
        if self.closing and not (self.worker and self.worker.is_alive()):self.root.destroy(); return
        self.root.after(20,self.poll)

    def close(self):
        self.closing=True; self.stop.set()
