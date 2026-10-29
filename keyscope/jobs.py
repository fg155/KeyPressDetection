import json
import os
import threading
import time
import traceback
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path
from .config import ROOT, validate_task

class Cancelled(Exception):
    pass

class Job:
    def __init__(self, kind, config):
        self.id = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6]
        self.kind, self.config = kind, config
        self.output = Path(config['output_dir']) / self.id
        self.output.mkdir(parents=True,exist_ok=False)
        self.cancel = threading.Event()
        self.lock = threading.RLock()
        self.state = {'id':self.id,'kind':kind,'status':'running','stage':'Preparing',
            'created_at':datetime.now().isoformat(timespec='seconds'),'progress':0,
            'elapsed':0,'metrics':{},'history':[],'events':[],'artifacts':[],
            'output_dir':str(self.output),'config':config,'error':None,'has_preview':False,'preview_version':0}
        self.logs = deque(maxlen=250)
        self.started = time.perf_counter()
        self.last_save = 0
        self.preview = None
        self.log('Job created.')

    def check(self):
        if self.cancel.is_set():
            raise Cancelled()

    def log(self, message):
        stamp = datetime.now().strftime('%H:%M:%S')
        with self.lock:
            self.logs.append({'time':stamp,'message':str(message)})
            with (self.output/'task.log').open('a',encoding='utf-8') as f:
                f.write(f'[{stamp}] {message}\n')
        print(f'[{self.id}] {message}',flush=True)

    def update(self, **values):
        with self.lock:
            running = self.state['status'] in ('running', 'stopping')
            self.state.update(values)
            if running:
                self.state['elapsed'] = round(time.perf_counter()-self.started,2)

    def add_event(self, row):
        with self.lock:
            self.state['events'].append(row)
            self.state['events'] = self.state['events'][-80:]

    def set_preview(self, image_bytes):
        with self.lock:
            self.preview = image_bytes
            self.state['has_preview'] = True
            self.state['preview_version'] += 1

    def save_preview(self):
        with self.lock:
            if self.preview is None:
                return
            tmp=self.output/'preview.jpg.tmp'
            tmp.write_bytes(self.preview)
            tmp.replace(self.output/'preview.jpg')

    def artifact(self, path, label):
        path = Path(path)
        with self.lock:
            self.state['artifacts'] = [x for x in self.state['artifacts'] if x['name'] != path.name]
            self.state['artifacts'].append({'name':path.name,'label':label,'bytes':path.stat().st_size})

    def discard_inference_outputs(self):
        """Remove only this job's known inference products, after handles close."""
        if self.kind != 'inference':
            return
        from .score import output_stem
        expected = Path(self.config['output_dir']).resolve()/self.id
        if self.output.is_symlink() or self.output.is_junction() or self.output.resolve() != expected:
            raise ValueError('Refusing cleanup outside the job output directory.')
        prefix = output_stem(self.config['video_path'])
        names = [f'{prefix}{suffix}' for suffix in ('_keys.txt','_detections.csv','_key_events.csv','_summary.json')]
        names += [name+'.part' for name in names] + ['preview.jpg','preview.jpg.tmp']
        failures = []
        for name in names:
            try:
                (self.output/name).unlink(missing_ok=True)
            except OSError as exc:
                failures.append(f'{name}: {exc}')
        with self.lock:
            self.preview = None
            self.state.update(artifacts=[],events=[],has_preview=False)
            self.state['metrics']['pressed'] = []
        if failures:
            raise OSError('Cannot remove incomplete output: ' + '; '.join(failures))

    def snapshot(self):
        with self.lock:
            result = json.loads(json.dumps(self.state))
            if result['status'] in ('running', 'stopping'):
                result['elapsed'] = round(time.perf_counter()-self.started,2)
            result['logs'] = list(self.logs)
            return result

    def save(self):
        with self.lock:
            payload = self.snapshot()
            tmp = self.output/'job.json.tmp'
            tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
            os.replace(tmp,self.output/'job.json')
            self.last_save = time.monotonic()

class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.active = None
        self.jobs = {}
        self.index_path = ROOT/'history.json'
        self.index = []
        try:
            self.index = json.loads(self.index_path.read_text('utf-8'))
        except (OSError,ValueError):
            pass
        for entry in self.index:
            try:
                p = self._entry_path(entry)
                saved = json.loads(p.read_text('utf-8'))
                if saved['status'] in ('running','stopping'):
                    saved.update(status='interrupted',stage='Server stopped',error='The server stopped before this job finished. Incomplete inference results were not saved.')
                    p.write_text(json.dumps(saved,ensure_ascii=False,indent=2),encoding='utf-8')
            except (OSError,ValueError,KeyError):
                continue

    def _entry_path(self, entry):
        p = Path(entry['path'])
        return p if p.is_absolute() else ROOT/p

    def start(self, kind, data):
        cfg = validate_task(kind,data)
        with self.lock:
            if self.active:
                raise ValueError('A job is already running. Wait for it to finish or stop it first.')
            job = Job(kind,cfg)
            self.jobs[job.id] = job
            self.active = job.id
            p = job.output/'job.json'
            try: p = p.relative_to(ROOT)
            except ValueError: pass
            self.index.insert(0,{'id':job.id,'path':str(p)})
            tmp = self.index_path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.index,ensure_ascii=False),encoding='utf-8')
            tmp.replace(self.index_path)
            job.save()
            threading.Thread(target=self._run,args=(job,),daemon=True,name='KeyPressDetection-worker').start()
            return job.snapshot()

    def _run(self,job):
        try:
            from .engine import run_inference
            if job.kind != 'inference':
                raise ValueError('Only inference jobs are supported. Training has been removed.')
            run_inference(job)
            # Finish and stop are serialized so a late stop cannot publish results.
            with self.lock:
                job.check()
                job.update(status='completed',stage='Completed',progress=1)
            job.log('Job completed. Results saved.')
        except Cancelled:
            job.update(status='cancelled',stage='Stopped')
            if job.kind == 'inference':
                try:
                    job.discard_inference_outputs()
                    job.log('Inference stopped. Incomplete outputs discarded.')
                except (OSError,ValueError) as exc:
                    job.update(error=str(exc))
                    job.log(str(exc))
        except Exception as exc:
            message = str(exc)
            if 'out of memory' in message.lower():
                message = 'Inference out of memory. Reduce batch size or input size. ' + message[:250]
            job.update(status='failed',stage='Job failed',error=message)
            job.log(message)
            (job.output/'error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        finally:
            job.save()
            with self.lock:
                self.active = None

    def get(self, job_id):
        with self.lock:
            if job_id in self.jobs:
                return self.jobs[job_id].snapshot()
            entry = next((e for e in self.index if e['id']==job_id),None)
            if not entry: raise ValueError('Job not found.')
            result = json.loads(self._entry_path(entry).read_text('utf-8'))
            result['output_dir'] = str(self._entry_path(entry).parent)
            return result

    def list(self):
        results=[]
        for entry in self.index[:100]:
            try:
                job=self.get(entry['id'])
                if job['kind'] != 'inference': continue
                summary={k:job[k] for k in ('id','kind','status','stage','created_at','progress','metrics','elapsed')}
                summary['video']=Path(job.get('config',{}).get('video_path','')).name
                results.append(summary)
            except (OSError,ValueError,KeyError): pass
        return results

    def stop(self, job_id):
        with self.lock:
            if job_id != self.active or self.jobs[job_id].state['status'] not in ('running','stopping'):
                raise ValueError('This job has already finished.')
            self.jobs[job_id].cancel.set()
            self.jobs[job_id].update(status='stopping',stage='Stopping after current batch')
            return self.jobs[job_id].snapshot()

    def delete_scores(self, directory, files):
        from .score_library import delete_scores
        with self.lock:
            protected = [self.jobs[self.active].output] if self.active else []
            result = delete_scores(directory, files, protected)
            removed = {Path(path).resolve() for path in result['deleted']}
            removed_jobs = [entry['id'] for entry in self.index
                            if any(self._entry_path(entry).resolve().is_relative_to(folder) for folder in removed)]
            if removed_jobs:
                self.index = [entry for entry in self.index if entry['id'] not in removed_jobs]
                for job_id in removed_jobs:
                    self.jobs.pop(job_id, None)
                tmp = self.index_path.with_suffix('.tmp')
                tmp.write_text(json.dumps(self.index, ensure_ascii=False), encoding='utf-8')
                tmp.replace(self.index_path)
            result['removed_jobs'] = removed_jobs
            return result
