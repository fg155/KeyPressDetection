"""Small portable preferences; no changes to system keyboard settings."""
import json
from pathlib import Path
import uuid
from .config import ROOT

HOTKEYS={**{f'F{i}':0x6f+i for i in range(1,13)},
         'Insert':0x2d,'Home':0x24,'End':0x23,'PageUp':0x21,'PageDown':0x22,'Pause':0x13}
SETTINGS_PATH=ROOT/'simulator_settings.json'

def read_hotkeys(path=None):
    try:
        values=json.loads(Path(path or SETTINGS_PATH).read_text('utf-8'))
        toggle,stop=values.get('toggle_hotkey','F6'),values.get('stop_hotkey','F8')
        if not isinstance(toggle,str) or toggle not in HOTKEYS:toggle='F6'
        if not isinstance(stop,str) or stop not in HOTKEYS:stop='F8'
        if stop==toggle:stop='F6' if toggle=='F8' else 'F8'
        return toggle,stop
    except (OSError,ValueError,TypeError,AttributeError):
        return 'F6','F8'

def save_hotkeys(toggle,stop,path=None):
    if any(not isinstance(value,str) or value not in HOTKEYS for value in (toggle,stop)):
        raise ValueError('Unsupported hotkey.')
    if toggle==stop:
        raise ValueError('Start/Pause and Stop must use different hotkeys.')
    path=Path(path or SETTINGS_PATH)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps({'toggle_hotkey':toggle,'stop_hotkey':stop},indent=2),'utf-8')
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def read_hotkey(path=None):
    return read_hotkeys(path)[0]

def save_hotkey(value,path=None):
    save_hotkeys(value,read_hotkeys(path)[1],path)

class KeyEdge:
    """One action per physical press, including across settings changes."""
    def __init__(self,down=False): self.down=down
    def update(self,down):
        rising=down and not self.down
        self.down=bool(down)
        return rising
