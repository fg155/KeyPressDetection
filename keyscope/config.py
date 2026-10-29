from pathlib import Path
import json
import math
from .edition import cuda_enabled

ROOT = Path(__file__).resolve().parents[1]
KEYS = {
    'Q': [398,608,519,736], 'W': [564,609,687,736], 'E': [737,610,854,735],
    'R': [902,611,1021,736], 'T': [1073,614,1189,738], 'Y': [1235,612,1357,740],
    'U': [1402,615,1524,739], 'A': [398,750,520,872], 'S': [568,751,687,875],
    'D': [736,747,858,867], 'F': [900,753,1022,870], 'G': [1073,752,1185,871],
    'H': [1236,751,1358,872], 'J': [1400,751,1520,870], 'Z': [397,883,519,1002],
    'X': [569,885,686,1006], 'C': [734,880,857,1003], 'V': [901,882,1019,1005],
    'B': [1073,882,1193,1008], 'N': [1236,881,1358,1009], 'M': [1400,880,1522,1008]
}
DEFAULTS = {
    'model_path': 'models/faster_rcnn.pth' if cuda_enabled() else 'models/faster_rcnn.onnx', 'output_dir': 'runs',
    'device': 'auto', 'batch_size': 16 if cuda_enabled() else 1, 'threshold': 0.8, 'stride': 1,
    'min_size': 800, 'amp': True, 'tf32': False,
    'disabled_keys': [], 'debounce_ms': 50, 'cpu_threads': 0, 'directml_adapter': -1,
    'directml_precision': 'fp32',
    'reference_size': [1920,1080], 'roi': [350,550,1550,1020], 'regions': KEYS,
}

def resolve_path(value):
    p = Path(str(value).strip().strip('"')).expanduser()
    return (ROOT / p).resolve() if not p.is_absolute() else p.resolve()

def read_settings():
    result = json.loads(json.dumps(DEFAULTS))
    p = ROOT / 'settings.json'
    if p.is_file():
        try:
            result.update({k:v for k,v in json.loads(p.read_text('utf-8')).items() if k in DEFAULTS})
        except (ValueError, OSError):
            pass
    return result

def save_settings(data):
    settings = read_settings()
    settings.update({k:v for k,v in data.items() if k in DEFAULTS})
    validate_geometry(settings)
    validate_controls(settings)
    if settings['device'] not in (('auto','cpu','directml','cuda') if cuda_enabled() else ('auto','cpu','directml')):
        raise ValueError('Invalid compute device.')
    model=resolve_path(settings['model_path'])
    if not model.is_file() or model.suffix.lower() not in (('.onnx','.pth','.pt') if cuda_enabled() else ('.onnx',)):
        raise ValueError('Select an existing model for this edition.')
    for key in ('model_path','output_dir'):
        path=resolve_path(settings[key])
        try: settings[key]=path.relative_to(ROOT).as_posix()
        except ValueError: settings[key]=str(path)
    tmp = ROOT / 'settings.json.tmp'
    tmp.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(ROOT / 'settings.json')
    return settings

def number(data, key, default, low, high, integer=False):
    try:
        value = float(data.get(key, default))
    except (ValueError, TypeError):
        raise ValueError(f'{key} must be a number.')
    if not math.isfinite(value) or not low <= value <= high or (integer and not value.is_integer()):
        raise ValueError(f'{key} must be between {low} and {high}' + (' and must be an integer.' if integer else ''))
    return int(value) if integer else value

def validate_geometry(data):
    ref = data.get('reference_size', DEFAULTS['reference_size'])
    if not isinstance(ref, list) or len(ref) != 2 or any(not isinstance(n,(int,float)) or not math.isfinite(n) or n < 1 or n > 32768 for n in ref):
        raise ValueError('Invalid reference resolution.')
    def rect(box):
        return isinstance(box,list) and len(box)==4 and all(isinstance(n,(int,float)) and math.isfinite(n) for n in box) and 0 <= box[0] < box[2] <= ref[0] and 0 <= box[1] < box[3] <= ref[1]
    if not rect(data.get('roi',DEFAULTS['roi'])):
        raise ValueError('ROI must be inside the reference frame with positive width and height.')
    regions = data.get('regions',KEYS)
    if not isinstance(regions,dict) or set(regions) != set(KEYS) or not all(rect(v) for v in regions.values()):
        raise ValueError('All 21 key regions must be present and inside the reference frame.')

def geometry(data, width, height):
    validate_geometry(data)
    rw,rh = data.get('reference_size',DEFAULTS['reference_size'])
    sx,sy = width/rw,height/rh
    def scale(b):
        return [round(b[0]*sx),round(b[1]*sy),round(b[2]*sx),round(b[3]*sy)]
    roi = scale(data.get('roi',DEFAULTS['roi']))
    if roi[2] <= roi[0] or roi[3] <= roi[1]:
        raise ValueError('Video resolution is too small: the ROI is empty.')
    disabled=set(data.get('disabled_keys',[]))
    regions={k:scale(v) for k,v in data.get('regions',KEYS).items() if k not in disabled}
    # Moving a key beyond the saved crop must not silently make it undetectable.
    for box in regions.values():
        roi=[min(roi[0],box[0]),min(roi[1],box[1]),max(roi[2],box[2]),max(roi[3],box[3])]
    return roi,regions


def validate_controls(data):
    disabled=data.get('disabled_keys',[])
    if not isinstance(disabled,list) or any(not isinstance(k,str) or k not in KEYS for k in disabled):
        raise ValueError('Disabled keys must be a list of supported keys.')
    data['disabled_keys']=list(dict.fromkeys(disabled))
    data['debounce_ms']=number(data,'debounce_ms',50,0,500,True)
    data['cpu_threads']=number(data,'cpu_threads',0,0,256,True)
    data['directml_adapter']=number(data,'directml_adapter',-1,-1,31,True)
    precision=data.get('directml_precision','fp32')
    if precision not in ('fp32','fp16_mixed'):
        raise ValueError('DirectML precision must be fp32 or fp16_mixed.')
    data['directml_precision']=precision
    for key in ('amp','tf32'):
        if not isinstance(data.get(key,DEFAULTS[key]),bool):
            raise ValueError(f'{key} must be a boolean.')

def validate_task(kind, data):
    cfg = read_settings()
    cfg.update(data)
    validate_controls(cfg)
    if kind != 'inference':
        raise ValueError('Only inference jobs are supported. Training has been removed.')
    model = resolve_path(cfg.get('model_path',''))
    if not model.is_file() or model.suffix.lower() not in (('.onnx','.pth','.pt') if cuda_enabled() else ('.onnx',)):
        raise ValueError('Select a valid model for this edition.')
    cfg['model_path'] = str(model)
    if cfg.get('device') not in (('auto','cpu','directml','cuda') if cuda_enabled() else ('auto','cpu','directml')):
        raise ValueError('Invalid device for this edition.')
    if cfg.get('device')=='cuda' and model.suffix.lower()=='.onnx':
        raise ValueError('Select a .pth or .pt checkpoint for CUDA, or use DirectML for ONNX.')
    cfg['min_size'] = number(cfg,'min_size',800,256,1024,True)
    out = resolve_path(cfg.get('output_dir') or 'runs')
    if out.exists() and not out.is_dir():
        raise ValueError('Output path must be a directory.')
    cfg['output_dir'] = str(out)
    video = resolve_path(cfg.get('video_path',''))
    if not video.is_file():
        raise ValueError('Select an existing video file.')
    cfg['video_path'] = str(video)
    cfg['batch_size'] = number(cfg,'batch_size',DEFAULTS['batch_size'],1,256 if cuda_enabled() else 16,True)
    if not cuda_enabled() and cfg['batch_size'] not in (1,16):
        raise ValueError('Batch size must be 1 or 16.')
    cfg['stride'] = number(cfg,'stride',1,1,120,True)
    cfg['threshold'] = number(cfg,'threshold',0.8,0.01,0.99)
    validate_geometry(cfg)
    return cfg
