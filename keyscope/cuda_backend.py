"""Optional CUDA implementation. Imported only when the profile enables PyTorch."""
from contextlib import nullcontext
from pathlib import Path
import gc
import os
import threading
import numpy as np
import torch
from torchvision.models.detection import FasterRCNN
from torchvision.models.detection.backbone_utils import resnet_fpn_backbone
from torchvision.ops import FrozenBatchNorm2d
from .jobs import Cancelled
from .backends import CUDAFailure


class CUDAModel:
    backend = 'cuda'
    setup_seconds = 0.

    def __init__(self, cfg, job):
        self.cfg, self.job = cfg, job
        self.device = device_for({**cfg,'device':'cuda'})
        self.model = inference_model(cfg,self.device,job)
        self.device_name = torch.cuda.get_device_name(0)
        self.batch_size = cfg['batch_size']
        self.precision = 'FP16 mixed' if cfg.get('amp',True) else 'FP32'

    def predict_arrays(self, arrays, threshold):
        self.job.check()
        try:
            result = predict(self.model,arrays,self.device,self.cfg.get('amp',True),threshold,self.job)
            self.batch_size = self.job.effective_batch
            return result
        except Cancelled:
            raise
        except RuntimeError as exc:
            message = str(exc)
        self.model = None
        clear_model_cache()
        raise CUDAFailure(message)

_cache = None
_init_lock=threading.Lock()
_initialized=False

def initialize():
    global _initialized
    with _init_lock:
        if not _initialized:
            torch.set_num_threads(min(8,max(1,(os.cpu_count() or 4)//2)))
            torch.set_num_interop_threads(2)
            _initialized=True

def device_for(config):
    initialize()
    wanted=config.get('device','auto')
    cuda=torch.cuda.is_available()
    if wanted=='cuda' and not cuda: raise ValueError('CUDA is unavailable. Select Auto or CPU, or check the NVIDIA driver.')
    device=torch.device('cuda' if cuda and wanted!='cpu' else 'cpu')
    threads=min(os.cpu_count() or 1,int(config.get('cpu_threads',0)) or (os.cpu_count() or 1)) if device.type=='cpu' else min(8,os.cpu_count() or 1)
    torch.set_num_threads(max(1,threads))
    torch.backends.cudnn.benchmark=device.type=='cuda'
    torch.backends.cuda.matmul.allow_tf32=bool(config.get('tf32',False))
    torch.backends.cudnn.allow_tf32=bool(config.get('tf32',False))
    return device

def amp_context(device,enabled):
    return torch.amp.autocast('cuda',dtype=torch.float16) if device.type=='cuda' and enabled else nullcontext()

def new_model(min_size=800,trainable_layers=3):
    # The supplied model was trained from COCO_V1, which uses FrozenBatchNorm.
    # weights=None alone switches torchvision to ordinary BN and changes training.
    backbone=resnet_fpn_backbone(backbone_name='resnet50',weights=None,
        norm_layer=FrozenBatchNorm2d,trainable_layers=trainable_layers)
    return FasterRCNN(backbone,num_classes=3,min_size=min_size,max_size=1333)

def load_checkpoint(path):
    checkpoint=torch.load(path,map_location='cpu',weights_only=True)
    if not isinstance(checkpoint,dict): raise ValueError('Expected a state_dict or a training checkpoint.')
    state=checkpoint.get('model_state_dict',checkpoint.get('state_dict',checkpoint))
    if not isinstance(state,dict): raise ValueError('Invalid model weights format.')
    if all(k.startswith('module.') for k in state): state={k[7:]:v for k,v in state.items()}
    return state,checkpoint

def inference_model(cfg,device,job):
    global _cache
    p=Path(cfg['model_path'])
    key=(str(p),p.stat().st_mtime_ns,p.stat().st_size,str(device),cfg['min_size'])
    if _cache and _cache[0]==key:
        job.log('Reusing cached model.')
        return _cache[1]
    clear_model_cache()
    from .onnx_backend import clear_session
    clear_session()
    job.log('Loading model from disk.')
    state,_=load_checkpoint(p)
    model=new_model(cfg['min_size'])
    model.load_state_dict(state,strict=True)
    model.to(device).eval()
    from .torch_ops import optimize_inference_model
    fused=optimize_inference_model(model)
    job.log(f'Inference optimization: fused {fused} fixed normalization layers; channels-last layout enabled.')
    _cache=(key,model)
    return model

def clear_model_cache():
    global _cache
    _cache=None
    gc.collect()
    if torch.cuda.is_available(): torch.cuda.empty_cache()

def _predict_batch(model,arrays,device,amp,threshold):
    # Keep tensor lifetimes inside this helper so an OOM retry releases all of
    # the failed batch, including partial results, after its traceback exits.
    batch=torch.from_numpy(np.stack(arrays)).permute(0,3,1,2).contiguous()
    if device.type=='cuda': batch=batch.pin_memory()
    inputs=batch.to(device,non_blocking=device.type=='cuda').float().div_(255)
    with torch.inference_mode(),amp_context(device,amp):
        outputs=model(list(inputs))
    # Boolean indexing on CUDA calls nonzero and synchronizes per image. The
    # detector already caps results at 100 boxes/image: copy these few KB once
    # and perform the final label/threshold filter on the CPU instead.
    sizes=[len(out['scores']) for out in outputs]
    packed=torch.cat([torch.cat((out['boxes'].float(),out['scores'][:,None].float(),
                                out['labels'][:,None].float()),dim=1)
                      for out in outputs],dim=0).cpu().numpy()
    frames=np.split(packed,np.cumsum(sizes)[:-1])
    return [frame[(frame[:,5]==2)&(frame[:,4]>=threshold),:5] for frame in frames]


def predict(model,arrays,device,amp,threshold,job):
    """Batched inference with a single result transfer and OOM recovery."""
    job.check()
    if hasattr(model,'predict_arrays'):
        return model.predict_arrays(arrays,threshold)
    limit=max(1,getattr(job,'effective_batch',len(arrays)))
    if len(arrays)>limit:
        # A decoded batch may already be queued when CUDA lowers the limit.
        # Respect that limit before allocating again instead of repeating OOM.
        return [result for start in range(0,len(arrays),limit)
                for result in predict(model,arrays[start:start+limit],device,amp,threshold,job)]
    try:
        return _predict_batch(model,arrays,device,amp,threshold)
    except torch.cuda.OutOfMemoryError:
        if len(arrays)==1: raise
    # The exception frame is gone, so its tensors can be freed before retrying.
    gc.collect()
    torch.cuda.empty_cache()
    job.log(f'CUDA out of memory: splitting a batch of {len(arrays)} frames.')
    middle=len(arrays)//2
    job.effective_batch=min(getattr(job,'effective_batch',len(arrays)),middle)
    return predict(model,arrays[:middle],device,amp,threshold,job)+predict(model,arrays[middle:],device,amp,threshold,job)

