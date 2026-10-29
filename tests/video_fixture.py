"""Generate test video frames without bundling images or user recordings."""
from pathlib import Path
import av
import numpy as np


def make_video(directory):
    path = Path(directory)/'synthetic.mkv'
    with av.open(str(path), 'w') as container:
        stream = container.add_stream('ffv1', rate=30)
        stream.width, stream.height, stream.pix_fmt = 1920, 1080, 'bgr0'
        for index in range(18):
            pixels = np.zeros((1080, 1920, 3), dtype=np.uint8)
            pixels[100:200, index*30:index*30+100] = (40, 100, 180)
            frame = av.VideoFrame.from_ndarray(pixels, format='rgb24')
            for packet in stream.encode(frame):container.mux(packet)
        for packet in stream.encode():container.mux(packet)
    return str(path)
