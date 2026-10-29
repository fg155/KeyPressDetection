"""TXT playback inventory and version-checked deletion of output folders."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from .config import ROOT, resolve_path


def version(stat):
    return f'{stat.st_mtime_ns}:{stat.st_size}'


def list_scores(directory):
    root = resolve_path(directory)
    if not root.exists():
        return {'directory':str(root), 'files':[]}
    if not root.is_dir():
        raise ValueError('Select an output directory.')
    files = []
    for current, dirs, names in os.walk(root, followlinks=False):
        folder = Path(current)
        dirs[:] = [d for d in dirs if not (folder/d).is_symlink() and not (folder/d).is_junction()]
        is_job = 'job.json' in names
        if is_job:
            try:
                state = json.loads((folder/'job.json').read_text('utf-8'))
                if state['status'] in ('running','stopping','failed','interrupted'):
                    dirs[:] = []
                    continue
            except (OSError,ValueError,KeyError):
                dirs[:] = []
                continue
        for name in names:
            file = folder/name
            if file.suffix.lower() != '.txt' or file.is_symlink() or (is_job and name=='error.txt'):
                continue
            try:
                stat = file.stat()
                files.append({'path':str(file), 'name':name, 'relative':str(file.relative_to(root)),
                              'bytes':stat.st_size, 'modified':stat.st_mtime, 'version':version(stat)})
            except OSError:
                continue
            if len(files) >= 5000:
                raise ValueError('Too many TXT files. Select a smaller directory.')
    files.sort(key=lambda file:file['modified'], reverse=True)
    return {'directory':str(root), 'files':files}


def _linked(path):
    return path.is_symlink() or path.is_junction()


def _app_data_only(path):
    """Do not offer application code, dependencies, or their ancestors for deletion."""
    app = ROOT.resolve()
    if app.is_relative_to(path):
        return False
    if path.is_relative_to(app):
        return path.relative_to(app).parts[0] not in ('runtime','models','keyscope','web','tools',
                                                    'tests','dependencies','examples','cache','.venv','.git')
    return True


def _folder_record(path, root):
    digest = hashlib.sha256()
    size = count = 0
    modified = path.stat().st_mtime
    for current, dirs, names in os.walk(path, followlinks=False):
        folder = Path(current)
        for child in [folder, *(folder/n for n in sorted(dirs + names))]:
            if _linked(child):
                raise ValueError('Linked output folders cannot be deleted.')
            stat = child.stat()
            digest.update(json.dumps([str(child.relative_to(path)), stat.st_mtime_ns,
                                      stat.st_size, stat.st_ino], ensure_ascii=True).encode())
            modified = max(modified, stat.st_mtime)
            if child.is_file():
                size += stat.st_size
                count += 1
        dirs.sort()
    scores = sorted(p.name for p in path.glob('*.txt') if p.name != 'error.txt')
    return {'path':str(path), 'name':scores[0] if len(scores)==1 else path.name,
            'relative':str(path.relative_to(root)), 'bytes':size, 'modified':modified,
            'version':digest.hexdigest(), 'file_count':count, 'type':'folder'}


def list_score_folders(directory):
    root = resolve_path(directory)
    result = {'directory':str(root), 'files':[]}
    if not root.exists():
        return result
    if not root.is_dir():
        raise ValueError('Select an output directory.')
    for current, dirs, names in os.walk(root, followlinks=False):
        folder = Path(current)
        dirs[:] = sorted(d for d in dirs if not _linked(folder/d) and _app_data_only(folder/d))
        if folder == root or not _app_data_only(folder):
            continue
        is_job = 'job.json' in names
        if not is_job and not any(n.lower().endswith('.txt') for n in names):
            continue
        dirs[:] = []
        if is_job:
            try:
                state = json.loads((folder/'job.json').read_text('utf-8'))
                if state.get('kind','inference') != 'inference' or state['status'] in ('running','stopping'):
                    continue
            except (OSError,ValueError,KeyError):
                continue
        try:
            result['files'].append(_folder_record(folder, root))
        except (OSError,ValueError):
            continue
        if len(result['files']) > 5000:
            raise ValueError('Too many output folders. Select a smaller directory.')
    result['files'].sort(key=lambda f:f['modified'], reverse=True)
    return result


def delete_scores(directory, files, protected=()):
    if not isinstance(files,list) or not 1 <= len(files) <= 5000:
        raise ValueError('Select at least one output folder.')
    root = resolve_path(directory)
    inventory = {Path(f['path']):f for f in list_score_folders(root)['files']}
    protected = [Path(p).resolve() for p in protected]
    selected = {}

    def validate(path, expected):
        if path == root or not path.is_relative_to(root) or not _app_data_only(path):
            raise ValueError('Output folder must be inside the selected directory.')
        for part in (path, *path.parents):
            if part == root:
                break
            if _linked(part):
                raise ValueError('Linked output folders cannot be deleted.')
        if path.resolve() != path or not path.is_dir():
            raise ValueError('Output folder is unavailable. Refresh the list.')
        if any(path.is_relative_to(p) or p.is_relative_to(path) for p in protected):
            raise ValueError('Cannot delete outputs of a running job.')
        if _folder_record(path, root)['version'] != expected:
            raise ValueError('Output folder changed. Refresh the list before deleting.')

    # Validate every selected tree before removing any contents.
    for item in files:
        if not isinstance(item,dict) or not isinstance(item.get('path'),str):
            raise ValueError('Invalid score selection.')
        path = Path(os.path.abspath(item['path']))
        record = inventory.get(path)
        if record is None or record['version'] != item.get('version'):
            raise ValueError('Output folder changed or is unavailable. Refresh the list before deleting.')
        validate(path, record['version'])
        selected[path] = record['version']
    result = {'deleted':[], 'errors':[]}
    for path, expected in selected.items():
        try:
            validate(path, expected)
            shutil.rmtree(path)
            result['deleted'].append(str(path))
        except (OSError,ValueError) as exc:
            result['errors'].append({'path':str(path), 'error':str(exc)})
    return result
