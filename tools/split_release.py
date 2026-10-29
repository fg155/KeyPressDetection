"""Split an existing ZIP into GitHub Release assets below 2 GiB."""
from pathlib import Path
import argparse
import hashlib
import json


def split(source, part_bytes=1800*1024**2):
    source=Path(source).resolve(strict=True)
    if not source.is_file() or source.suffix.lower()!='.zip':
        raise ValueError('Source must be a ZIP file.')
    if not 1 <= part_bytes < 2*1024**3:
        raise ValueError('Part size must be positive and below 2 GiB.')
    count=max(1,(source.stat().st_size+part_bytes-1)//part_bytes)
    parts=[source.with_name(f'{source.name}.part{i:03d}') for i in range(1,count+1)]
    manifest=source.with_name(source.name+'.parts.json')
    if any(p.exists() for p in [*parts,manifest]):
        raise FileExistsError('Release parts already exist. Use a new ZIP filename.')
    whole=hashlib.sha256(); rows=[]
    with source.open('rb') as src:
        for target in parts:
            digest=hashlib.sha256(); size=0
            with target.open('xb') as dst:
                while size<part_bytes:
                    block=src.read(min(8*1024**2,part_bytes-size))
                    if not block:break
                    dst.write(block);digest.update(block);whole.update(block);size+=len(block)
            rows.append({'name':target.name,'bytes':size,'sha256':digest.hexdigest()})
            print(f'{target.name}: {size} bytes',flush=True)
    result={'file':source.name,'bytes':sum(p['bytes'] for p in rows),'sha256':whole.hexdigest(),'parts':rows}
    with manifest.open('x',encoding='utf-8') as f:json.dump(result,f,indent=2)
    print(f'Manifest: {manifest.name}',flush=True)
    return manifest


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive',type=Path)
    args=parser.parse_args()
    split(args.archive)
