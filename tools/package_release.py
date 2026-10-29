"""Build shared source, CUDA/DirectML portable editions and standalone model assets."""
import argparse
import hashlib
import io
import json
import os
import re
import sys
from pathlib import Path
import time
import zipfile
try:
    from .runtime_files import collect, runtime_needed
except ImportError:
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from runtime_files import collect, runtime_needed

ROOT=Path(__file__).resolve().parents[1]
APP_FILES=('server.py','simulator.py','start.cmd','start-simulator.cmd','README.md','README.zh-CN.md',
           'USER_GUIDE.md','THIRD_PARTY_NOTICES.txt')
SOURCE_FILES=('.gitignore','install.cmd','requirements.txt','requirements-directml.txt','requirements-cuda.txt',
              'requirements-directml.lock.txt','requirements-cuda.lock.txt','models/README.md','dependencies/README.md')
MODELS=('faster_rcnn.onnx','faster_rcnn.onnx.json','faster_rcnn_mixed.onnx',
        'faster_rcnn_batch16.onnx','faster_rcnn_batch16_mixed.onnx','weights.data')


def app_files(root=ROOT):
    return [root/n for n in APP_FILES]+list((root/'keyscope').glob('*.py'))+[
        p for p in (root/'web').iterdir() if p.suffix in ('.html','.js','.css','.svg')]+list((root/'docs').glob('*.md'))+[
        p for p in (root/'docs/media').glob('*') if p.is_file() and p.suffix in ('.png','.gif','.mp4','.txt')]


def source_files(root=ROOT):
    return app_files(root)+[root/n for n in SOURCE_FILES]+[
        p for folder in ('tests','tools') for p in (root/folder).iterdir() if p.suffix in ('.py','.js','.ps1','.cmd')]


def private_markers(root=ROOT, other_roots=()):
    values={str(root.resolve()),root.resolve().as_posix()}
    for path in other_roots:values.update((str(path.resolve()),path.resolve().as_posix()))
    profile=os.environ.get('USERPROFILE')
    if profile:values.add(profile)
    for path in (root,*other_roots):
        parts=path.resolve().parts
        for i,part in enumerate(parts[:-1]):
            if part.lower()=='users':values.update((parts[i+1],str(Path(*parts[:i+2]))))
    return tuple({value.lower().encode(enc) for value in values if len(value)>=5 for enc in ('utf-8','utf-16-le')})


def source_fingerprint(root=ROOT):
    digest=hashlib.sha256()
    for path in sorted(set(source_files(root))):
        digest.update(path.relative_to(root).as_posix().encode()+b'\0')
        digest.update(path.read_bytes());digest.update(b'\0')
    return digest.hexdigest()


def write_archive(destination,prefix,entries,markers):
    destination=Path(destination);destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_suffix('.zip.tmp');started=time.monotonic()
    try:
        with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=1,allowZip64=True) as z:
            for i,(name,value) in enumerate(sorted(entries.items())):
                rel=Path(name)
                if rel.is_absolute() or '..' in rel.parts or rel.parts[0] in ('runs','scores','cache','data','examples'):
                    raise ValueError('Invalid release path.')
                if isinstance(value,bytes):stream=io.BytesIO(value);size=len(value)
                else:
                    if value.is_symlink() or value.is_junction():raise ValueError('Linked release input: '+name)
                    stream=value.open('rb');size=value.stat().st_size
                info=zipfile.ZipInfo(f'{prefix}/{rel.as_posix()}',date_time=(1980,1,1,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED;info.external_attr=0o100644<<16
                info._compresslevel=9 if prefix.endswith('-source') else 1
                tail=b''
                with stream,z.open(info,'w',force_zip64=size>=2**31) as target:
                    while block:=stream.read(8*1024**2):
                        probe=(tail+block).lower()
                        if any(marker in probe for marker in markers):raise ValueError('Local identity/path found in release input: '+name)
                        tail=block[-2048:];target.write(block)
                if i and i%2000==0:print(f'{destination.name}: {i}/{len(entries)} files',flush=True)
        temporary.replace(destination)
        with destination.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
        destination.with_suffix('.sha256').write_text(f'{digest}  {destination.name}\n','ascii')
        print(f'{destination.name}: {len(entries)} files, {destination.stat().st_size} bytes, {time.monotonic()-started:.1f}s',flush=True)
        return destination
    finally:temporary.unlink(missing_ok=True)


def build(destination,prefix,paths,root=ROOT,overrides=None):
    root=root.resolve();entries={}
    for path in paths:
        path=path.resolve()
        if not path.is_relative_to(root):raise ValueError('Release input escaped source root.')
        name=path.relative_to(root).as_posix();entries[name]=(overrides or {}).get(name,path)
    return write_archive(destination,prefix,entries,private_markers(root))


def onnx_entries(models):
    models=Path(models).resolve(strict=True);entries={}
    for name in MODELS:
        path=models/name
        if not path.is_file():raise ValueError('Missing model file: '+name)
        entries[name]=path
    manifest=json.loads((models/'faster_rcnn.onnx.json').read_text('utf-8'))
    if manifest.get('format')!='key-press-detection-onnx-v1':raise ValueError('Use the shared ONNX model bundle.')
    for name,key in (('faster_rcnn.onnx','onnx_sha256'),('weights.data','external_weights_sha256')):
        with (models/name).open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if manifest.get(key)!=digest:raise ValueError('Model bundle hash mismatch: '+name)
    return entries,manifest


def model_archives(output,models,checkpoint=None,model_format='both',model_name='FasterRCNN',root=ROOT):
    if model_format not in ('onnx','pytorch','both'):raise ValueError('Unknown model format.')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}',model_name):raise ValueError('Use a short filename-safe model name.')
    bundles={};manifest={};roots=[Path(models)]
    if model_format in ('onnx','both'):
        bundles['ONNX'],manifest=onnx_entries(models)
    if model_format in ('pytorch','both'):
        checkpoint=Path(checkpoint or Path(models)/'faster_rcnn.pth').resolve(strict=True)
        if checkpoint.suffix.lower() not in ('.pth','.pt'):raise ValueError('Select a PyTorch checkpoint.')
        with checkpoint.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if model_format=='both' and manifest.get('source_sha256')!=digest:
            raise ValueError('The ONNX bundle and PyTorch checkpoint must match.')
        bundles['PyTorch']={'faster_rcnn.pth':checkpoint};roots.append(checkpoint.parent)
    archives=[]
    for label,entries in bundles.items():
        entries['README.md']=root/'models/README.md'
        hashes={}
        for name,path in entries.items():
            if name=='README.md':continue
            with path.open('rb') as stream:hashes[name]=hashlib.file_digest(stream,'sha256').hexdigest()
        entries[label.lower()+'-package.json']=(json.dumps({'name':model_name,'format':label,'files':hashes},indent=2)+'\n').encode()
        archives.append(write_archive(Path(output)/f'KeyPressDetection-Model-{model_name}-{label}.zip','models',entries,private_markers(root,roots)))
    return archives


def portable_entries(edition,runtime,models,checkpoint=None,root=ROOT):
    if edition not in ('cuda','directml'):raise ValueError('Unknown edition.')
    runtime=Path(runtime).resolve(strict=True);models=Path(models).resolve(strict=True)
    entries={p.relative_to(root).as_posix():p for p in app_files(root)}
    lock=root/f'requirements-{edition}.lock.txt'
    entries.update(collect(runtime,lock));entries['requirements.lock.txt']=lock
    model_files,manifest=onnx_entries(models)
    entries.update({'models/'+name:path for name,path in model_files.items()})
    entries['models/README.md']=root/'models/README.md'
    if edition=='cuda':
        checkpoint=Path(checkpoint or models/'faster_rcnn.pth').resolve(strict=True)
        entries['models/faster_rcnn.pth']=checkpoint
        # Only pair checkpoints whose exporter-recorded source digest agrees.
        with checkpoint.open('rb') as stream:digest=hashlib.file_digest(stream,'sha256').hexdigest()
        if manifest.get('source_sha256')!=digest:
            raise ValueError('The ONNX bundle manifest must record the matching checkpoint source_sha256.')
        if 'runtime/Lib/site-packages/torch/lib/torch_cuda.dll' not in entries:raise ValueError('CUDA runtime libraries are missing.')
    else:
        if any(n.startswith(('runtime/Lib/site-packages/torch/','runtime/Lib/site-packages/torchvision/')) for n in entries):
            raise ValueError('The DirectML lockfile includes PyTorch.')
    entries['edition.json']=(json.dumps({'edition':edition,'source_sha256':source_fingerprint(root)},indent=2)+'\n').encode()
    return entries


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind',choices=('source','portable','models','all'),default='all')
    parser.add_argument('--edition',choices=('cuda','directml'),default='directml')
    parser.add_argument('--runtime',type=Path)
    parser.add_argument('--models',type=Path,default=ROOT/'models')
    parser.add_argument('--checkpoint',type=Path)
    parser.add_argument('--model-format',choices=('onnx','pytorch','both'),default='both')
    parser.add_argument('--model-name',default='FasterRCNN',help='Name or version used in standalone model asset filenames.')
    parser.add_argument('--output',type=Path,default=ROOT/'dist')
    parser.add_argument('--split',action='store_true',help='Also create parts of a portable ZIP larger than 2 GiB.')
    args=parser.parse_args()
    if args.kind in ('all','portable') and args.runtime is None:parser.error('--runtime is required for a portable build')
    if args.kind in ('all','source'):
        build(args.output/'KeyPressDetection-Source.zip','KeyPressDetection-source',source_files())
    if args.kind=='models':
        model_archives(args.output,args.models,args.checkpoint,args.model_format,args.model_name)
    if args.kind in ('all','portable'):
        entries=portable_entries(args.edition,args.runtime,args.models,args.checkpoint)
        label='CUDA' if args.edition=='cuda' else 'DirectML'
        path=args.output/f'KeyPressDetection-{label}-Windows-x64-Portable.zip'
        roots=[args.runtime,args.models]
        if args.checkpoint:roots.append(args.checkpoint.parent)
        write_archive(path,f'KeyPressDetection-{label}',entries,private_markers(ROOT,roots))
        if args.split and path.stat().st_size>=2*1024**3:
            from split_release import split
            split(path)
            import shutil
            shutil.copyfile(ROOT/'tools/join-release.cmd',path.parent/'join-release.cmd')


if __name__=='__main__':main()
