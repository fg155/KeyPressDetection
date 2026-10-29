"""Readable bar notation from timestamped scores; spaces are visual rests."""
import math
from .score import Debouncer,parse_score


def convert_score(text, *, format='fingertip', **options):
    converters = {'fingertip': convert_fingertip}
    if not isinstance(format, str) or format not in converters:
        raise ValueError('Unsupported score format.')
    return {**converters[format](text, **options), 'format': format}


def convert_fingertip(text, *, bpm=120, beats=4, denominator=4, start=0, bars_per_line=4, debounce_ms=50):
    values={'bpm':(bpm,20,400),'beats':(beats,1,16),'start':(start,0,86400),
            'bars_per_line':(bars_per_line,1,16),'debounce_ms':(debounce_ms,0,500)}
    for name,(value,low,high) in values.items():
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
            raise ValueError(f'{name} must be between {low} and {high}.')
    if beats!=int(beats) or bars_per_line!=int(bars_per_line) or denominator not in (2,4,8,16):
        raise ValueError('Invalid time signature or line length.')
    debounce=Debouncer(debounce_ms);notes=[]
    for row in parse_score(text):
        keys=debounce.accept(row.time,row.keys)
        if keys:notes.append((row.time,keys))
    beat_seconds=60/bpm*4/denominator
    bar_seconds=beat_seconds*beats
    # Shorter observed inter-note distances establish a visual spacing scale.
    # It is never used to quantize timestamps, form chords, or move barlines.
    gaps=sorted(b[0]-a[0] for a,b in zip(notes,notes[1:]) if b[0]-a[0]>1e-6)
    unit=min(beat_seconds,max(.03,gaps[(len(gaps)-1)//4] if gaps else beat_seconds/2))
    grouped={}
    for stamp,keys in notes:
        index=math.floor((stamp-start)/bar_seconds+1e-8)
        grouped.setdefault(index,[]).append((stamp,keys))
    first=min(0,min(grouped));last=max(grouped)
    if last-first+1>10000:raise ValueError('Too many bars. Check BPM, time signature, and first-bar time.')
    bars=[]
    for index in range(first,last+1):
        tokens=[];previous=start+index*bar_seconds
        for stamp,keys in grouped.get(index,[]):
            gap=stamp-previous
            if gap>unit*1.5:
                tokens.append(' '*min(3,max(1,round(gap/unit)-1)))
            tokens.append(keys[0] if len(keys)==1 else '('+''.join(keys)+')')
            previous=stamp
        bars.append((''.join(tokens) if tokens else '   ')+'/')
    width=int(bars_per_line)
    return {'text':'\n\n'.join(''.join(bars[i:i+width]) for i in range(0,len(bars),width))+'\n',
            'events':len(notes),'bars':len(bars),'bpm':bpm,'beats':beats,'denominator':denominator}
