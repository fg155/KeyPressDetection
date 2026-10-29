"""Distribution profile; source checkouts detect their installed dependencies."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def profile():
    path = ROOT/'edition.json'
    if path.is_file():
        value = json.loads(path.read_text('utf-8')).get('edition')
        if value not in ('cuda', 'directml'):
            raise ValueError('Invalid edition.json profile.')
        return value
    return 'cuda' if importlib.util.find_spec('torch') is not None else 'directml'


def cuda_enabled():
    return profile() == 'cuda'
