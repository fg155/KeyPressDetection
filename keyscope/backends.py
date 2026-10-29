"""Select a backend while keeping the video/score pipeline shared."""
import sys
import threading
from .config import ROOT, resolve_path
from .edition import cuda_enabled
from . import hardware
from .jobs import Cancelled
from .onnx_backend import ONNXModel, DirectMLFailure, fingerprint, metadata

_export_lock = threading.Lock()


class CUDAFailure(RuntimeError):
    pass


GPU_FAILURES = (CUDAFailure, DirectMLFailure)


def cuda_status():
    result = {'enabled':cuda_enabled(), 'available':False, 'version':None, 'torch':None, 'device':None, 'vram_gb':None}
    if not result['enabled']:
        return result
    try:
        import torch
        result.update(available=torch.cuda.is_available(),version=torch.version.cuda,torch=torch.__version__)
        if result['available']:
            result.update(device=torch.cuda.get_device_name(0),vram_gb=round(torch.cuda.get_device_properties(0).total_memory/1024**3,1))
    except (ImportError, OSError, RuntimeError) as exc:
        result['error'] = str(exc)
    return result


def clear_cache():
    from .onnx_backend import clear_session
    clear_session()
    module = sys.modules.get('keyscope.cuda_backend')
    if module is not None:
        module.clear_model_cache()


def onnx_config(cfg, job):
    """A bundled checkpoint uses the matching ONNX graph; custom weights export once."""
    source = resolve_path(cfg['model_path'])
    if source.suffix.lower() == '.onnx':
        return cfg
    if not cuda_enabled():
        raise ValueError('Select an ONNX model for the DirectML edition.')
    digest = fingerprint(source)
    for base in (ROOT/'models/faster_rcnn.onnx', source.with_suffix('.onnx')):
        if not base.is_file():
            continue
        try:
            info=metadata(base)
            weights=base.parent/info.get('external_weights','weights.data')
            matched=(info.get('source_sha256')==digest and info.get('onnx_sha256')==fingerprint(base))
            if info.get('external_weights'):
                matched=matched and weights.is_file() and info.get('external_weights_sha256')==fingerprint(weights)
            if matched:
                return {**cfg,'model_path':str(base)}
        except ValueError:
            pass
    target = ROOT/'cache/onnx'/f'{digest}-base.onnx'
    with _export_lock:
        job.check()
        try:
            cached = target.is_file() and metadata(target).get('source_sha256') == digest
        except ValueError:
            cached = False
        if not cached:
            from .onnx_export import export_model
            export_model(source,target,800,job.log,job.check)
    return {**cfg,'model_path':str(target)}


def create_model(cfg, job):
    wanted = cfg.get('device','auto')
    checkpoint = resolve_path(cfg['model_path']).suffix.lower() in ('.pth','.pt')
    if wanted in ('auto','cuda') and checkpoint and cuda_enabled():
        status = cuda_status()
        if status['available']:
            try:
                from .cuda_backend import CUDAModel
                return CUDAModel(cfg,job)
            except Cancelled:
                raise
            except (RuntimeError, OSError) as exc:
                clear_cache()
                job.log(f'CUDA initialization failed: {exc}. Using CPU.')
                wanted = 'cpu'
        elif wanted == 'cuda':
            job.log('CUDA is unavailable. Using CPU.')
            wanted = 'cpu'
    elif wanted == 'cuda':
        raise ValueError('CUDA requires the CUDA edition and a .pth or .pt checkpoint.')
    adapter = hardware.select_directml(cfg.get('directml_adapter',-1)) if wanted != 'cpu' else None
    if not adapter and wanted != 'cpu':
        job.log('No compatible DirectML GPU selected. Using ONNX Runtime CPU.')
    return ONNXModel(onnx_config(cfg,job),job,adapter)
