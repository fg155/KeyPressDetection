"""ONNX-only inference: DirectML on supported GPUs, FP32 on CPU."""
import gc
import hashlib
import json
import os
from pathlib import Path
import threading
import time
import uuid
import numpy as np
from .config import ROOT, resolve_path
from .jobs import Cancelled

FORMAT = 'key-press-detection-onnx-v1'
_prepare_lock = threading.Lock()
_session_cache = None


class DirectMLFailure(RuntimeError):
    pass


def fingerprint(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def metadata(path):
    try:
        value = json.loads(Path(str(path)+'.json').read_text('utf-8'))
    except (OSError, ValueError) as exc:
        raise ValueError('Select the FP32 ONNX model with its matching .onnx.json manifest.') from exc
    if (value.get('format') != FORMAT or value.get('batch_size') != 1 or
            value.get('precision') != 'fp32' or value.get('min_size') != 800):
        raise ValueError('Unsupported ONNX model manifest. Select the supplied base FP32 model.')
    return value


def variant_path(base, meta, precision, batch):
    if precision == 'fp32' and batch == 1:
        return base
    name = meta.get('variants', {}).get(f'{precision}_{batch}')
    if not name:
        return None
    path = (base.parent/name).resolve()
    if not path.is_relative_to(base.parent.resolve()) or path.suffix.lower() != '.onnx':
        raise ValueError('Invalid model variant path.')
    if not path.is_file():
        raise ValueError('Model variant is missing: '+path.name)
    return path


def ensure_model(cfg, job, precision, batch):
    """Use supplied graphs, preparing another input scale without PyTorch."""
    base = resolve_path(cfg['model_path'])
    meta = metadata(base)
    path = variant_path(base, meta, precision, batch)
    size = cfg.get('min_size', 800)
    if path is not None and size == 800:
        return path
    with _prepare_lock:
        job.check()
        source = path or variant_path(base, meta, 'fp32', batch)
        if source is None:
            raise ValueError('This ONNX model does not support the requested batch size.')
        import onnx
        raw = onnx.load(source)
        digest = hashlib.sha256(raw.SerializeToString()).hexdigest()
        target = ROOT/'cache/onnx'/f'{digest}-{size}-{precision}.onnx'
        if target.is_file():
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name+'.'+uuid.uuid4().hex+'.tmp')
        resized = temporary.with_suffix('.resize.tmp')
        try:
            job.update(stage='Preparing ONNX model')
            if size != 800:
                changed = 0
                for node in raw.graph.node:
                    if node.op_type != 'Constant' or not node.name.startswith('/detector/transform/'):
                        continue
                    if not node.attribute or node.attribute[0].type != onnx.AttributeProto.TENSOR:
                        continue
                    value = onnx.numpy_helper.to_array(node.attribute[0].t)
                    if value.size == 1 and value.dtype.kind == 'f' and float(value.flat[0]) == 800:
                        node.attribute[0].t.CopyFrom(onnx.numpy_helper.from_array(np.full_like(value, size)))
                        changed += 1
                if changed != batch:
                    raise ValueError('The model preprocessing does not match the supported ONNX export.')
            job.check()
            if path is None:
                from .onnx_precision import convert
                onnx.save(raw, resized)
                del raw
                convert(resized, temporary, check=job.check)
            else:
                onnx.checker.check_model(raw)
                onnx.save(raw, temporary)
            job.check()
            temporary.replace(target)
            job.log(f'ONNX model ready: short edge {size}; {precision}; batch {batch}.')
        finally:
            temporary.unlink(missing_ok=True)
            resized.unlink(missing_ok=True)
    return target


def create_session(path, height, width, adapter_id=None, threads=0):
    import onnxruntime as ort
    options = ort.SessionOptions()
    options.log_severity_level = 3
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.intra_op_num_threads = min(threads, os.cpu_count() or 1) if threads else 0
    options.add_free_dimension_override_by_name('height', height)
    options.add_free_dimension_override_by_name('width', width)
    providers = ['CPUExecutionProvider']
    if adapter_id is not None:
        options.enable_mem_pattern = False
        providers.insert(0, ('DmlExecutionProvider', {'device_id': adapter_id}))
    session = ort.InferenceSession(str(path), sess_options=options, providers=providers)
    session.disable_fallback()
    if adapter_id is not None and 'DmlExecutionProvider' not in session.get_providers():
        raise DirectMLFailure('DirectML session creation fell back to CPU.')
    return session


def clear_session():
    global _session_cache
    _session_cache = None


class ONNXModel:
    def __init__(self, cfg, job, adapter=None):
        self.cfg, self.job, self.adapter = cfg, job, adapter
        self.backend = 'directml' if adapter else 'cpu'
        self.device_name = adapter['name'] if adapter else 'CPU'
        base = resolve_path(cfg['model_path'])
        self.meta = metadata(base)
        self.batch_size = 16 if adapter and cfg.get('batch_size',1) >= 16 and 'fp32_16' in self.meta.get('variants', {}) else 1
        self.precision_key = cfg.get('directml_precision', 'fp32') if adapter else 'fp32'
        self.precision = 'FP16 mixed' if self.precision_key == 'fp16_mixed' else 'FP32'
        self.session = self.shape = self.path = None
        self.setup_seconds = 0.
        if self.batch_size != cfg.get('batch_size', 1):
            job.log(f'Using batch {self.batch_size} for this model/device (requested {cfg["batch_size"]}).')
        if not adapter and cfg.get('directml_precision') == 'fp16_mixed':
            job.log('CPU fallback uses the FP32 model.')

    def _session(self, height, width):
        global _session_cache
        if self.session is not None and self.shape == (height, width):
            return self.session
        started = time.perf_counter()
        self.path = self.path or ensure_model(self.cfg, self.job, self.precision_key, self.batch_size)
        self.job.check()
        threads = self.cfg.get('cpu_threads', 0)
        files = [self.path] + list(self.path.parent.glob('*.data'))
        stamp = tuple((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in sorted(files))
        adapter_id = self.adapter['id'] if self.adapter else None
        key = (stamp, height, width, adapter_id, threads)
        if _session_cache and _session_cache[0] == key:
            self.session = _session_cache[1]
            self.job.log('Reusing cached ONNX Runtime session.')
        else:
            self.session = None
            clear_session()
            gc.collect()
            self.job.update(stage='Preparing DirectML session' if self.adapter else 'Preparing CPU session')
            session = create_session(self.path, height, width, adapter_id, threads)
            inputs = session.get_inputs()
            expected = ['boxes','scores','labels'] if self.batch_size == 1 else [f'{name}_{i}' for i in range(16) for name in ('boxes','scores','labels')]
            if (len(inputs) != 1 or inputs[0].name != 'images' or inputs[0].type != 'tensor(float)' or
                    inputs[0].shape != [self.batch_size,3,height,width] or [v.name for v in session.get_outputs()] != expected):
                raise ValueError('ONNX input/output signature does not match this application.')
            self.session = session
            _session_cache = (key, self.session)
        self.shape = (height, width)
        self.setup_seconds += time.perf_counter()-started
        self.job.log(f'ONNX Runtime: {self.adapter["name"] if self.adapter else "CPU"}; ROI {width}x{height}; {self.precision}; batch {self.batch_size}.')
        return self.session

    def _predict_chunk(self, arrays, threshold):
        height, width = arrays[0].shape[:2]
        session = self._session(height, width)
        padded = list(arrays)+[arrays[-1]]*(self.batch_size-len(arrays))
        value = np.ascontiguousarray(np.stack(padded).transpose(0,3,1,2), dtype=np.float32)
        value /= 255.
        output = session.run(None, {'images': value})
        results = []
        for i in range(len(arrays)):
            boxes, scores, labels = output[i*3:i*3+3]
            keep = (labels == 2) & (scores >= threshold)
            results.append(np.concatenate((boxes[keep], scores[keep, None]), axis=1))
        return results

    def predict_arrays(self, arrays, threshold):
        results, index = [], 0
        while index < len(arrays):
            self.job.check()
            count = min(self.batch_size, len(arrays)-index)
            try:
                results.extend(self._predict_chunk(arrays[index:index+count], threshold))
                index += count
            except Cancelled:
                raise
            except Exception as exc:
                self.session = None
                clear_session()
                gc.collect()
                if not self.adapter:
                    raise
                if self.batch_size == 16:
                    self.batch_size = self.job.effective_batch = 1
                    self.path = self.shape = None
                    self.job.log(f'DirectML batch 16 failed: {exc}. Retrying at batch 1.')
                    continue
                raise DirectMLFailure(str(exc)) from exc
        return results
