"""Foreground, loopback-only server. Closing this console ends the application."""
import argparse
import base64
import json
import mimetypes
import os
from pathlib import Path
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, unquote, quote
import webbrowser
from keyscope.config import ROOT, read_settings, save_settings, resolve_path
from keyscope.jobs import JobManager
from keyscope.edition import profile, cuda_enabled

def download_header(name):
    return "attachment; filename=\"download" + Path(name).suffix + "\"; filename*=UTF-8''" + quote(name, safe='')

os.environ['PYTHONUTF8']='1'
if Path(sys.executable).parent==ROOT/'runtime':
    os.environ['TCL_LIBRARY']=str(ROOT/'runtime'/'tcl'/'tcl8.6')
    os.environ['TK_LIBRARY']=str(ROOT/'runtime'/'tcl'/'tk8.6')
for stream in (sys.stdout,sys.stderr):
    if hasattr(stream,'reconfigure'): stream.reconfigure(encoding='utf-8',errors='replace')

class Application:
    def __init__(self):
        self.token=secrets.token_urlsafe(32)
        self.manager=JobManager()
        self.picker_lock=threading.Lock()
        self.settings_lock=threading.Lock()
        self.environment={'loading':True,'python':sys.version.split()[0]}
        threading.Thread(target=self.probe,daemon=True).start()

    def probe(self):
        try:
            import av, onnxruntime
            from keyscope.hardware import directml_status
            from keyscope.backends import cuda_status
            cuda=cuda_status()
            dml=directml_status()
            selected=max(dml['adapters'],key=lambda a:a['dedicated_bytes'],default=None)
            self.environment={'loading':False,'python':sys.version.split()[0],
                'av':av.__version__,'onnxruntime':onnxruntime.__version__,
                'edition':profile(), 'cuda_enabled':cuda['enabled'], 'cuda':cuda['available'], 'cuda_version':cuda['version'], 'torch':cuda['torch'],'cpu_logical_count':os.cpu_count() or 1,
                'device':cuda['device']+' / CUDA' if cuda['available'] else (selected['name']+' / DirectML' if selected else 'CPU / ONNX Runtime'),
                'directml':dml,
                'vram_gb':cuda['vram_gb'] if cuda['available'] else (round(selected['dedicated_bytes']/1024**3,1) if selected else None),
                'root':str(ROOT),'portable':Path(sys.executable).parent==ROOT/'runtime'}
        except Exception as exc:
            self.environment={'loading':False,'error':str(exc),'python':sys.version.split()[0],'device':'Unavailable'}

    def pick(self,kind,language='en'):
        if not self.picker_lock.acquire(blocking=False): raise ValueError('A file picker is already open.')
        root=None
        try:
            import tkinter as tk
            from tkinter import filedialog
            root=tk.Tk()
            root.withdraw()
            root.attributes('-topmost',True)
            from keyscope.localization import PICKER_TITLES
            titles=PICKER_TITLES.get(language,PICKER_TITLES['en'])
            if kind=='directory': path=filedialog.askdirectory(parent=root,title=titles[kind])
            elif kind=='model': path=filedialog.askopenfilename(parent=root,title=titles[kind],filetypes=[('Model','*.pth *.pt *.onnx' if cuda_enabled() else '*.onnx')])
            elif kind=='video': path=filedialog.askopenfilename(parent=root,title=titles[kind],filetypes=[('Video','*.mp4 *.mkv *.avi *.mov *.webm *.m4v'),('All files','*.*')])
            else: raise ValueError('Unknown file picker type.')
            if path:
                try: path=str(Path(path).resolve().relative_to(ROOT))
                except ValueError: pass
            return {'path':path or ''}
        finally:
            if root: root.destroy()
            self.picker_lock.release()

class Handler(BaseHTTPRequestHandler):
    server_version='KeyPressDetection/1.0'
    def log_message(self,*args): pass

    @property
    def app(self): return self.server.app

    def respond(self,status,payload,kind='application/json; charset=utf-8',download=None):
        if not isinstance(payload,bytes): payload=json.dumps(payload,ensure_ascii=False,allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type',kind)
        self.send_header('Content-Length',str(len(payload)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        if download: self.send_header('Content-Disposition',download_header(download))
        self.end_headers()
        try: self.wfile.write(payload)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass

    def check_host(self):
        host=self.headers.get('Host','')
        return host in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}')

    def do_GET(self):
        if not self.check_host(): return self.respond(403,{'error':'Local access only.'})
        path=unquote(urlsplit(self.path).path)
        try:
            if path=='/api/bootstrap':
                return self.respond(200,{'token':self.app.token,'settings':read_settings(),
                    'environment':self.app.environment,'active':self.app.manager.active})
            if path=='/api/status':
                return self.respond(200,{'environment':self.app.environment,'active':self.app.manager.active})
            if path=='/api/jobs': return self.respond(200,self.app.manager.list())
            parts=path.strip('/').split('/')
            if len(parts)>=3 and parts[:2]==['api','jobs']:
                job_id=parts[2]
                job=self.app.manager.get(job_id)
                if len(parts)==3: return self.respond(200,job)
                if len(parts)==4 and parts[3]=='preview':
                    live=self.app.manager.jobs.get(job_id)
                    if live and live.preview: return self.respond(200,live.preview,'image/jpeg')
                    saved=Path(job['output_dir'])/'preview.jpg'
                    if saved.is_file(): return self.respond(200,saved.read_bytes(),'image/jpeg')
                    raise ValueError('Preview is not available yet.')
                if len(parts)==5 and parts[3]=='files':
                    name=parts[4]
                    if job['kind']=='inference' and job['status'] in ('running','stopping'):
                        raise ValueError('Inference outputs are available after completion.')
                    if not any(f['name']==name for f in job['artifacts']): raise ValueError('Output file not found.')
                    file=Path(job['output_dir'])/name
                    if file.resolve().parent!=Path(job['output_dir']).resolve(): raise ValueError('Invalid path.')
                    return self.send_file(file,True)
            relative='index.html' if path=='/' else path.lstrip('/')
            file=(ROOT/'web'/relative).resolve()
            if not file.is_relative_to(ROOT/'web') or not file.is_file():
                return self.respond(404,{'error':'Page not found.'})
            return self.send_file(file)
        except (ValueError,OSError,KeyError) as exc:
            return self.respond(404,{'error':str(exc)})

    def send_file(self,path,download=False):
        kind=mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
        if not download: return self.respond(200,path.read_bytes(),kind)
        # Models may be several hundred MB; stream instead of reading into RAM.
        self.send_response(200)
        self.send_header('Content-Type','application/octet-stream')
        self.send_header('Content-Length',str(path.stat().st_size))
        self.send_header('Content-Disposition',download_header(path.name))
        self.send_header('X-Content-Type-Options','nosniff')
        self.end_headers()
        try:
            with path.open('rb') as f:
                while block:=f.read(1024*1024): self.wfile.write(block)
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError): pass

    def do_POST(self):
        if not self.check_host() or not secrets.compare_digest(self.headers.get('X-KeyPressDetection-Token',self.headers.get('X-KeyScope-Token','')),self.app.token):
            return self.respond(403,{'error':'Session expired. Refresh the page.'})
        origin=self.headers.get('Origin')
        if origin and origin not in (f'http://127.0.0.1:{self.server.server_port}',f'http://localhost:{self.server.server_port}'):
            return self.respond(403,{'error':'Invalid origin.'})
        try:
            path=urlsplit(self.path).path
            length=int(self.headers.get('Content-Length','0'))
            limit=12*1024*1024 if path in ('/api/simulator/upload','/api/score/convert','/api/scores/delete') else 256000
            if length<=0 or length>limit: raise ValueError('Invalid request size.')
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError('Request must be a JSON object.')
            path=urlsplit(self.path).path
            if path=='/api/pick': result=self.app.pick(data.get('kind'),data.get('language','en'))
            elif path=='/api/settings':
                with self.app.settings_lock: result=save_settings(data)
                if 'disabled_keys' in data:
                    job=self.app.manager.jobs.get(self.app.manager.active)
                    if job and job.kind=='inference':
                        with job.lock:job.config['disabled_keys']=list(result['disabled_keys'])
                        job.log('Disabled keys updated: '+(','.join(result['disabled_keys']) or 'none')+'. Applied from the next processed batch.')
            elif path=='/api/video':
                from keyscope.engine import video_info
                video=resolve_path(data.get('path',''))
                if not video.is_file(): raise ValueError('Video not found. Select a different file.')
                info,preview=video_info(video)
                result={**info,'preview':'data:image/jpeg;base64,'+base64.b64encode(preview).decode('ascii')}
            elif path=='/api/jobs': result=self.app.manager.start(data.pop('kind','inference'),data)
            elif path=='/api/stop': result=self.app.manager.stop(data.get('id'))
            elif path=='/api/simulator/files':
                from keyscope.simulator_launch import list_scores
                result=list_scores(data.get('directory') or read_settings()['output_dir'])
            elif path=='/api/scores/list':
                from keyscope.score_library import list_score_folders
                result=list_score_folders(data.get('directory') or read_settings()['output_dir'])
            elif path=='/api/scores/delete':
                result=self.app.manager.delete_scores(data.get('directory') or read_settings()['output_dir'],data.get('files'))
            elif path=='/api/simulator/upload':
                from keyscope.score import decode_score, parse_score, output_stem
                name=data.get('name','')
                if not isinstance(name,str) or Path(name).suffix.lower()!='.txt': raise ValueError('Select a TXT file.')
                raw=base64.b64decode(data.get('content',''),validate=True)
                parse_score(decode_score(raw))
                folder=ROOT/'scores'/secrets.token_hex(6); folder.mkdir(parents=True,exist_ok=False)
                score=folder/(output_stem(name)+'.txt')
                score.write_bytes(raw)
                result={'path':str(score),'name':name}
            elif path=='/api/score/convert':
                from keyscope.score import decode_score,read_score,MAX_BYTES,output_stem
                from keyscope.converter import convert_score
                if 'content' in data:
                    name=str(data.get('name','score.txt'))
                    if Path(name).suffix.lower()!='.txt':raise ValueError('Select a TXT file.')
                    raw=base64.b64decode(data['content'],validate=True)
                else:
                    score=resolve_path(data.get('path',''))
                    if not score.is_file() or score.suffix.lower()!='.txt':raise ValueError('Select a TXT file.')
                    name=score.name
                    with score.open('rb') as f:raw=f.read(MAX_BYTES+1)
                result=convert_score(decode_score(raw),**{k:data[k] for k in ('format','bpm','beats','denominator','start','bars_per_line','debounce_ms') if k in data})
                result['name']=output_stem(name)+'_formatted.txt'
            elif path=='/api/simulator/launch':
                from keyscope.simulator_launch import launch_simulator
                result=launch_simulator(data.get('directory') or read_settings()['output_dir'],data.get('score'),data.get('language','zh'))
            elif path=='/api/open-output':
                job=self.app.manager.get(data.get('id'))
                os.startfile(job['output_dir'])
                result={'ok':True}
            else: return self.respond(404,{'error':'Endpoint not found.'})
            return self.respond(200,result)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            return self.respond(400,{'error':str(exc)})
        except Exception as exc:
            return self.respond(500,{'error':str(exc)})

def main():
    parser=argparse.ArgumentParser(description='Key Press Detection local server')
    parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    app=Application()
    server=None
    for port in range(args.port,args.port+20):
        try:
            server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
            break
        except OSError: continue
    if server is None: raise SystemExit('No port available. Use --port to select another port.')
    server.daemon_threads=True
    server.app=app
    url=f'http://127.0.0.1:{server.server_port}'
    print(f'\n  Key Press Detection / {profile()}',flush=True)
    print(f'  {url}\n\n  Keep this CMD window open. Closing it stops the server.\n  Press Ctrl+C to stop.\n',flush=True)
    if not args.no_browser: threading.Timer(.7,lambda:webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=.3)
    except KeyboardInterrupt:
        print('\nStopping server...',flush=True)
    finally:
        if app.manager.active:
            job=app.manager.jobs[app.manager.active]
            job.cancel.set()
            deadline=time.monotonic()+8
            while app.manager.active and time.monotonic()<deadline: time.sleep(.1)
        server.server_close()
        # Compute jobs end here. The independent simulator survives server exit.
        os._exit(0)

if __name__=='__main__': main()
