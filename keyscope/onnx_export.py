"""Export a custom CUDA checkpoint for ONNX fallback."""
import json
from pathlib import Path
import uuid
from .onnx_backend import fingerprint, FORMAT

def export_model(model_path, destination, min_size=800, log=print, check=lambda: None):
    """FP32, batch 1, dynamic H/W. Does not download or modify source weights."""
    import torch
    import onnx
    from .cuda_backend import new_model, load_checkpoint
    from .torch_ops import fuse_frozen_norms
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = fingerprint(model_path)
    check()
    model = new_model(min_size).eval()
    model.load_state_dict(load_checkpoint(model_path)[0], strict=True)
    fuse_frozen_norms(model.backbone.body)
    from torchvision.models.detection.transform import GeneralizedRCNNTransform
    class ExportTransform(GeneralizedRCNNTransform):
        def resize(self, image, target=None):
            if not torch.jit.is_tracing():
                return super().resize(image, target)
            # Torchvision's tracing branch rounds resize scales to float32,
            # while eager inference computes them as Python doubles. At an
            # integer boundary this can drop one pixel (e.g. 470 -> 480).
            # Preserve eager's double precision and floor before interpolation.
            shape = torch._shape_as_tensor(image)[-2:].to(torch.float64)
            scale = torch.minimum(self.min_size[-1] / shape.min(), self.max_size / shape.max())
            size = torch.floor(shape * scale).to(torch.int64)
            resized = torch.nn.functional.interpolate(image[None], size=(size[0], size[1]),
                        mode='bilinear', align_corners=False)[0]
            return resized, target
    old_transform = model.transform
    model.transform = ExportTransform(old_transform.min_size, old_transform.max_size,
                                     old_transform.image_mean, old_transform.image_std).eval()
    class Export(torch.nn.Module):
        def __init__(self, detector):
            super().__init__()
            self.detector = detector
        def forward(self, images):
            result = self.detector([images[0]])[0]
            return result['boxes'], result['scores'], result['labels']
    wrapped = Export(model).eval()
    # Only image geometry is used for tracing; no training data is required.
    sample = torch.zeros(1, 3, 470, 1200)
    temporary = destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.tmp')
    manifest = Path(str(destination)+'.json')
    manifest_tmp = Path(str(temporary)+'.json')
    try:
        log(f'Exporting ONNX: FP32, batch 1, dynamic ROI size, input short side {min_size}.')
        with torch.inference_mode():
            torch.onnx.export(wrapped, (sample,), str(temporary), opset_version=17, dynamo=False,
                input_names=['images'], output_names=['boxes', 'scores', 'labels'],
                dynamic_axes={'images': {2: 'height', 3: 'width'},
                              'boxes': {0: 'detections'}, 'scores': {0: 'detections'},
                              'labels': {0: 'detections'}})
        check()
        onnx.checker.check_model(str(temporary))
        if fingerprint(model_path) != digest:
            raise ValueError('Model weights changed during ONNX export. Retry with a stable checkpoint.')
        metadata = {'format': FORMAT, 'source_sha256': digest, 'min_size': min_size,
                    'max_size': 1333, 'opset': 17, 'batch_size': 1, 'precision': 'fp32',
                    'dynamic_roi': True, 'onnx_sha256': fingerprint(temporary)}
        manifest_tmp.write_text(json.dumps(metadata, indent=2)+'\n', 'utf-8')
        temporary.replace(destination)
        manifest_tmp.replace(manifest)
        log(f'ONNX export completed: {destination.name}.')
    finally:
        temporary.unlink(missing_ok=True)
        manifest_tmp.unlink(missing_ok=True)
    return destination


