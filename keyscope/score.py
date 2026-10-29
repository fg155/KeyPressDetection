"""TXT score parsing and timing; no GUI or keyboard side effects."""
from dataclasses import dataclass
import math
from pathlib import Path
import re

KEYS = 'QWERTYUASDFGHJZXCVBNM'
MAX_BYTES = 8 * 1024 * 1024
MAX_ROWS = 200_000


class Debouncer:
    """Per-key fixed window, anchored to the first accepted timestamp."""
    def __init__(self, milliseconds=50):
        self.window=milliseconds/1000
        self.first={}

    def accept(self, stamp, keys):
        accepted=[]
        for key in keys:
            previous=self.first.get(key)
            if previous is None or self.window==0 or stamp-previous>self.window+1e-9:
                self.first[key]=stamp
                accepted.append(key)
        return tuple(accepted)

@dataclass(frozen=True)
class Row:
    time: float
    keys: tuple[str, ...]

@dataclass(frozen=True)
class Event:
    time: float
    down: tuple[str, ...] = ()
    up: tuple[str, ...] = ()

def decode_score(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError('TXT exceeds 8 MiB.')
    if raw.startswith((b'\xff\xfe', b'\xfe\xff')):
        return raw.decode('utf-16')
    try:
        return raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        return raw.decode('gb18030')

def parse_score(text):
    rows = []
    previous = -1.0
    for line_number, line in enumerate(text.splitlines(), 1):
        line = line.strip().lstrip('\ufeff')
        if not line or line.startswith('#'):
            continue
        parts = line.split(maxsplit=1)
        try:
            stamp = float(parts[0])
        except ValueError:
            raise ValueError(f'Line {line_number}: invalid timestamp.') from None
        if not math.isfinite(stamp) or not 0 <= stamp <= 86400:
            raise ValueError(f'Line {line_number}: time must be between 0 and 86400 seconds.')
        if stamp < previous:
            raise ValueError(f'Line {line_number}: timestamps must be in ascending order.')
        previous = stamp
        names = tuple(dict.fromkeys(re.split(r'[,;\s]+', parts[1].upper()))) if len(parts) == 2 else ()
        if any(name not in KEYS or len(name) != 1 for name in names):
            raise ValueError(f'Line {line_number}: only Q W E R T Y U A S D F G H J Z X C V B N M are supported.')
        if rows and rows[-1].time == stamp:
            rows[-1] = Row(stamp, tuple(dict.fromkeys(rows[-1].keys + names)))
        else:
            rows.append(Row(stamp, names))
        if len(rows) > MAX_ROWS:
            raise ValueError('TXT exceeds 200000 timestamp rows.')
    if not rows or not any(row.keys for row in rows):
        raise ValueError('TXT contains no key events.')
    return rows

def read_score(path):
    path = Path(path)
    if path.suffix.lower() != '.txt':
        raise ValueError('Select a TXT file.')
    with path.open('rb') as stream:
        return parse_score(decode_score(stream.read(MAX_BYTES + 1)))

def plan_score(rows, hold_ms=40, merge_ms=80, speed=1.0, mode='merge'):
    for name, value, low, high in (('hold_ms', hold_ms, 5, 1000), ('merge_ms', merge_ms, 0, 1000), ('speed', speed, .25, 4)):
        if not isinstance(value, (float, int)) or not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f'{name} must be between {low} and {high}.')
    if mode not in ('merge', 'tap'):
        raise ValueError('Unknown playback mode.')
    # A present row lacking a key is an explicit release boundary. Missing rows
    # in inference TXT require a configurable maximum gap between detections.
    intervals = {key: [] for key in KEYS}
    active = {}
    for row in rows:
        for key in tuple(active):
            start, last = active[key]
            if key not in row.keys or row.time-last > merge_ms/1000 + 1e-8 or mode == 'tap':
                intervals[key].append((start, min(last+hold_ms/1000, row.time)))
                del active[key]
        for key in row.keys:
            active[key] = (active.get(key, (row.time,))[0], row.time)
    for key, (start, last) in active.items():
        intervals[key].append((start, last+hold_ms/1000))
    timeline = {}
    count = 0
    for key, spans in intervals.items():
        for index, (start, end) in enumerate(spans):
            # Leave a real up interval between repeated taps even at high speed.
            if index+1 < len(spans):
                end = min(end, start+(spans[index+1][0]-start)*.8)
            if end <= start:
                continue
            timeline.setdefault(round(start/speed, 9), [[], []])[0].append(key)
            timeline.setdefault(round(end/speed, 9), [[], []])[1].append(key)
            count += 1
    events = tuple(Event(t, tuple(down), tuple(up)) for t, (down, up) in sorted(timeline.items()))
    return events, count

def play_events(events, sink, stop, *, clock, wait, guard=lambda: None, progress=lambda t: None,
                pause=None, resume_ready=lambda: False, on_pause=lambda: None, on_resume=lambda: None,
                tick=lambda t: None):
    """Freeze the score clock while paused and release physical keys immediately.

    Logical held notes are restored on resume for their remaining duration.
    The input sink is injectable so timing and release behavior can be tested
    without sending actual keyboard input.
    """
    started = clock()
    held = set()
    physical = set()
    try:
        for event in events:
            while not stop.is_set():
                guard()
                if pause is not None and pause.is_set():
                    paused_at=clock()
                    if physical:
                        sink.send((),tuple(sorted(physical)))
                        physical.clear()
                    on_pause()
                    while pause.is_set() and not stop.is_set():
                        guard()
                        if resume_ready():
                            pause.clear()
                            break
                        wait(.01)
                    started+=clock()-paused_at
                    if stop.is_set(): break
                    # Recheck focus before restoring a held chord.
                    guard()
                    if pause.is_set(): continue
                    if held:
                        physical.update(held)
                        sink.send(tuple(sorted(held)),())
                    on_resume()
                elapsed=clock()-started
                tick(elapsed)
                remaining = event.time-elapsed
                if remaining <= 1e-9:
                    break
                wait(min(remaining, .01))
            if stop.is_set():
                break
            # Include intended downs before sending, so partial SendInput failure
            # also releases any keys that Windows may already have accepted.
            physical.update(event.down)
            sink.send(event.down, event.up)
            held.difference_update(event.up)
            held.update(event.down)
            physical.difference_update(set(event.up)-set(event.down))
            progress(event.time)
    finally:
        if physical:
            sink.send((), tuple(sorted(physical)))

def output_stem(video):
    # Leave room for suffixes and job directories on Windows; retain Unicode.
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', Path(video).stem).rstrip('. ')[:100].rstrip('. ')
    return stem or 'video'
