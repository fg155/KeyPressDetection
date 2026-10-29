from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import csv
import gc
import io
import json
import os
import time
import av
import numpy as np
from PIL import Image, ImageDraw
from .config import geometry
from .jobs import Cancelled

def clear_cache():
    from .backends import clear_cache as clear_backends
    clear_backends()
    gc.collect()


def video_info(path):
    with av.open(str(path)) as container:
        if not container.streams.video: raise ValueError('No video stream found.')
        stream=container.streams.video[0]
        rate=float(stream.average_rate or stream.guessed_rate or 30)
        duration=float(stream.duration*stream.time_base) if stream.duration is not None else (float(container.duration)/av.time_base if container.duration else None)
        frame=next(container.decode(stream),None)
        if frame is None: raise ValueError('No decodable video frames found.')
        buf=io.BytesIO()
        img=frame.to_image()
        img.thumbnail((1280,720))
        img.save(buf,'JPEG',quality=85)
        return {'width':frame.width,'height':frame.height,'fps':rate,'frames':stream.frames or None,
                'duration':duration,'codec':stream.codec_context.name},buf.getvalue()

def timestamp(frame,stream,index,fps,origin,last):
    value=float(frame.pts*stream.time_base) if frame.pts is not None and stream.time_base else index/fps
    if origin is None: origin=value
    value=max(0.,value-origin)
    if last is not None and value <= last: value=last+1/fps
    return value,origin

def predict(model, arrays, threshold, job):
    job.check()
    return model.predict_arrays(arrays, threshold)


def map_keys(detections,regions,roi):
    pressed={}
    for b in detections:
        cx=(b[0]+b[2])/2+roi[0]
        cy=(b[1]+b[3])/2+roi[1]
        for key,region in regions.items():
            if region[0] <= cx <= region[2] and region[1] <= cy <= region[3]:
                pressed[key]=max(pressed.get(key,0),float(b[4]))
                break
    return {key:pressed[key] for key in regions if key in pressed}

def render_preview(rgb,roi,regions,pressed):
    # Preserve the entire video frame and its aspect ratio.
    image=Image.fromarray(rgb)
    draw=ImageDraw.Draw(image)
    for key,b in regions.items():
        box=tuple(b)
        color='#e49c71' if key in pressed else '#8aab95'
        draw.rectangle(box,outline=color,width=3 if key in pressed else 1)
        draw.text((box[0]+5,box[1]+5),key,fill=color,stroke_width=1)
    image.thumbnail((1100,600))
    buf=io.BytesIO()
    image.save(buf,'JPEG',quality=82)
    return buf.getvalue()

def run_inference(job):
    cfg=job.config
    from .backends import create_model, GPU_FAILURES
    model = create_model(cfg, job)
    job.effective_batch = model.batch_size
    job.log(f'Inference device: {model.device_name} / {model.backend}; {model.precision}; batch {model.batch_size}.')
    job.update(stage='Model loaded, preparing first batch')
    job.check()
    from .score import output_stem,Debouncer
    debounce=Debouncer(cfg.get('debounce_ms',50))
    prefix=output_stem(cfg['video_path'])
    log_path=job.output/f'{prefix}_keys.txt'
    csv_path=job.output/f'{prefix}_detections.csv'
    events_path=job.output/f'{prefix}_key_events.csv'
    processed=decoded=event_count=0
    counts={k:0 for k in cfg['regions']}
    origin=last=None
    active={}
    processed_stamp=None
    start=time.perf_counter()
    last_preview=0
    timing={'decode_wait':0.,'inference':0.,'results_preview':0.,'first_batch':None}
    # Scores and CSV rows are small; keep them in memory until success.
    log, csv_file, event_file = io.StringIO(), io.StringIO(newline=''), io.StringIO(newline='')
    with av.open(cfg['video_path']) as container:
        if not container.streams.video: raise ValueError('No video stream found.')
        stream=container.streams.video[0]
        # PyAV options {'hwaccel': 'dxva2'} do not prove hardware decoding is active.
        # Use reliable threaded software decoding, overlapped with GPU inference.
        stream.thread_type='AUTO'
        stream.codec_context.thread_count=min(4,os.cpu_count() or 1)
        fps=float(stream.average_rate or stream.guessed_rate or 30)
        duration=float(stream.duration*stream.time_base) if stream.duration is not None else (float(container.duration)/av.time_base if container.duration else None)
        estimated=stream.frames or (round(duration*fps) if duration else 0)
        writer=csv.writer(csv_file)
        writer.writerow(['frame','time_seconds','keys','confidence'])
        ew=csv.writer(event_file)
        ew.writerow(['key','start_seconds','end_seconds','duration_seconds'])
        roi,all_regions=geometry({**cfg,'disabled_keys':[]},stream.width,stream.height)
        regions={k:r for k,r in all_regions.items() if k not in cfg.get('disabled_keys',[])}
        job.log(f'Video: {stream.width}x{stream.height}, {fps:.3f} fps; ROI: {roi}; stride: {cfg["stride"]}.')
        def batches():
            nonlocal origin,last,decoded
            chunk=[]
            for index,frame in enumerate(container.decode(stream)):
                job.check()
                decoded=index+1
                stamp,origin=timestamp(frame,stream,index,fps,origin,last)
                last=stamp
                if index%cfg['stride']: continue
                rgb=frame.to_ndarray(format='rgb24')
                crop=np.ascontiguousarray(rgb[roi[1]:roi[3],roi[0]:roi[2]])
                chunk.append((index,stamp,crop))
                if len(chunk)>=job.effective_batch:
                    # Only the final full-size frame is used for preview. Keep
                    # cropped inputs for the rest, especially for large batches.
                    yield chunk,rgb
                    chunk=[]
            if chunk: yield chunk,rgb
        iterator=iter(batches())
        try:
            with ThreadPoolExecutor(max_workers=1,thread_name_prefix='video-decode') as pool:
                future=pool.submit(next,iterator,None)
                while True:
                    tick=time.perf_counter()
                    decoded_batch=future.result()
                    timing['decode_wait']+=time.perf_counter()-tick
                    if decoded_batch is None: break
                    chunk,rgb=decoded_batch
                    future=pool.submit(next,iterator,None)
                    tick=time.perf_counter()
                    try:
                        outputs=predict(model,[v[2] for v in chunk],cfg['threshold'],job)
                    except GPU_FAILURES as exc:
                        job.check()
                        job.log(f'{model.backend} failed: {exc}. Retrying this batch on CPU; remaining frames will use CPU.')
                        clear_cache()
                        model=create_model({**cfg,'device':'cpu'},job)
                        job.effective_batch=1
                        outputs=predict(model,[v[2] for v in chunk],cfg['threshold'],job)
                    batch_seconds=time.perf_counter()-tick
                    timing['inference']+=batch_seconds
                    if timing['first_batch'] is None: timing['first_batch']=batch_seconds
                    tick=time.perf_counter()
                    regions={k:r for k,r in all_regions.items() if k not in cfg.get('disabled_keys',[])}
                    for (index,stamp,crop),dets in zip(chunk,outputs):
                        pressed=map_keys(dets,regions,roi)
                        processed_stamp=stamp
                        processed+=1
                        for key in list(active):
                            if key not in pressed:
                                began=active.pop(key)
                                ew.writerow([key,f'{began:.6f}',f'{stamp:.6f}',f'{stamp-began:.6f}'])
                        for key in pressed:
                            if key not in active: active[key]=stamp; event_count+=1
                            counts[key]+=1
                        notes=debounce.accept(stamp,pressed)
                        if notes:
                            log.write(f'{stamp:.2f}\t{",".join(notes)}\n')
                            job.add_event({'time':round(stamp,3),'keys':list(notes)})
                        writer.writerow([index,f'{stamp:.6f}',','.join(pressed),';'.join(f'{k}:{v:.4f}' for k,v in pressed.items())])
                    now=time.perf_counter()
                    if now-last_preview>0.7:
                        job.set_preview(render_preview(rgb,roi,regions,pressed))
                        last_preview=now
                    elapsed=now-start
                    progress=min(.995,(index+1)/estimated) if estimated else None
                    speed=processed/max(elapsed,.001)
                    job.update(stage='Running inference',progress=progress,metrics={
                        'processed_frames':processed,'source_frame':index+1,'total_frames':estimated or None,
                        'fps':round(speed,2),'video_time':round(stamp,2),'key_events':event_count,
                        'batch_size':job.effective_batch,'pressed':list(pressed),'counts':counts.copy(),
                        'device':model.backend,
                        'device_name':model.device_name,
                        'precision':model.precision,
                        'cpu_threads':(cfg.get('cpu_threads',0) or None) if model.backend!='cuda' else None,
                        'directml_setup_seconds':round(model.setup_seconds,4) if model.backend=='directml' else None,
                        'disabled_keys':cfg.get('disabled_keys',[]),'debounce_ms':cfg.get('debounce_ms',50),
                        'eta':round(((estimated-index-1)/cfg['stride'])/speed,1) if estimated and speed else None})
                    timing['results_preview']+=time.perf_counter()-tick
                if processed:
                    job.set_preview(render_preview(rgb,roi,regions,pressed))
        finally:
            end=(processed_stamp or 0)+cfg['stride']/fps if job.cancel.is_set() else (last or 0)+1/fps
            for key,began in active.items():
                ew.writerow([key,f'{began:.6f}',f'{end:.6f}',f'{end-began:.6f}'])
            log.flush(); csv_file.flush(); event_file.flush()
    job.check()
    for p,buffer,encoding,label in ((log_path,log,'utf-8','Detection log'),(csv_path,csv_file,'utf-8-sig','Frame detections (CSV)'),(events_path,event_file,'utf-8-sig','Key intervals (CSV)')):
        job.check()
        p.write_text(buffer.getvalue(),encoding=encoding,newline='')
        buffer.close()
        job.artifact(p,label)
    summary=job.output/f'{prefix}_summary.json'
    metrics=job.snapshot()['metrics']
    metrics['timing_seconds']={k:round(v,4) if v is not None else None for k,v in timing.items()}
    job.update(metrics=metrics)
    job.log(f'Pipeline timing: decode wait {timing["decode_wait"]:.3f}s; inference {timing["inference"]:.3f}s; results/preview {timing["results_preview"]:.3f}s. First batch {timing["first_batch"] or 0:.3f}s (included in inference).')
    summary.write_text(json.dumps(job.snapshot()['metrics'],ensure_ascii=False,indent=2),encoding='utf-8')
    job.artifact(summary,'Inference summary')
    job.check()
    job.save_preview()
