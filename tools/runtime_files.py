"""Select a portable Python runtime from the edition's locked distributions."""
import importlib.metadata
from pathlib import Path
import re


def normalize(name):
    return re.sub(r'[-_.]+','-',name).lower()


def runtime_needed(relative):
    parts=relative.parts
    if '__pycache__' in parts or relative.suffix in ('.pyc','.pyo','.tmp','.bak','.pdb'):
        return False
    if relative.name=='direct_url.json':return False
    if parts[:3]==('runtime','Lib','site-packages'):
        package=parts[3:]
        if not package:return True
        if package[0]=='bin' or 'tests' in package:return False
        if package[0]=='onnxruntime' and len(package)>1 and package[1] in ('tools','transformers','quantization','datasets','backend'):return False
        if package[:2] in (('onnx','test'),('torch','include'),('torch','share')):return False
        if package[:4]==('onnx','backend','test','data'):return False
        if package[:2]==('torch','lib') and relative.suffix=='.lib':return False
    return True


def collect(runtime, lockfile):
    runtime=Path(runtime).resolve(strict=True)
    expected={normalize(m[1]):m[2] for line in Path(lockfile).read_text('utf-8').splitlines()
              if (m:=re.fullmatch(r'([A-Za-z0-9_.-]+)==([^\s]+)',line.strip()))}
    if not expected:raise ValueError('The dependency lockfile is empty.')
    found={};entries={}
    site=runtime/'Lib/site-packages'
    for p in runtime.rglob('*'):
        if p.is_file() and not p.is_relative_to(site) and runtime_needed(Path('runtime')/p.relative_to(runtime)):
            entries[(Path('runtime')/p.relative_to(runtime)).as_posix()]=p
    for dist in importlib.metadata.distributions(path=[str(site)]):
        name=normalize(dist.metadata['Name'])
        if name not in expected:continue
        if dist.version!=expected[name]:raise ValueError(f'{name}: expected {expected[name]}, found {dist.version}.')
        found[name]=dist.version
        for entry in dist.files or []:
            p=Path(dist.locate_file(entry)).resolve()
            if not p.is_relative_to(runtime) or not p.is_file():continue
            rel=Path('runtime')/p.relative_to(runtime)
            if runtime_needed(rel):entries[rel.as_posix()]=p
    missing=set(expected)-set(found)
    if missing:raise ValueError('Runtime is missing locked packages: '+', '.join(sorted(missing)))
    for name in ('runtime/python.exe','runtime/pythonw.exe','runtime/python312.dll','runtime/python312._pth','runtime/tcl/tk8.6/tk.tcl','runtime/Lib/site-packages/onnxruntime/capi/DirectML.dll'):
        if name not in entries:raise ValueError('Incomplete portable runtime: '+name)
    return entries
