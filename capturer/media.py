"""Pull evenly spaced keyframes out of a video using PyAV (no ffmpeg binary needed)."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Frame:
    timestamp_sec: float
    jpeg_b64: str


def frame_timestamps(duration_sec: float, count: int) -> list[float]:
    """Evenly spaced sample points that avoid the very start and very end."""
    if count <= 0 or duration_sec <= 0:
        return []
    if count == 1:
        return [duration_sec / 2]
    step = duration_sec / (count + 1)
    return [round(step * (i + 1), 3) for i in range(count)]


def extract_frames(video_path: Path, count: int = 6, max_width: int = 720, quality: int = 80) -> list[Frame]:
    """Decode ``count`` frames spread across the video and return them as base64 JPEGs."""
    import av  # lazy: heavy native dependency

    frames: list[Frame] = []
    with av.open(str(video_path)) as container:
        if not container.streams.video:
            return frames
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"

        duration = None
        if stream.duration is not None and stream.time_base is not None:
            duration = float(stream.duration * stream.time_base)
        if (not duration or duration <= 0) and container.duration:
            duration = container.duration / av.time_base
        if not duration or duration <= 0:
            return frames

        for ts in frame_timestamps(duration, count):
            target_pts = int(ts / stream.time_base)
            container.seek(target_pts, stream=stream, backward=True, any_frame=False)
            for frame in container.decode(stream):
                if frame.pts is None or frame.pts * stream.time_base >= ts - 0.05:
                    image = frame.to_image()
                    if image.width > max_width:
                        ratio = max_width / image.width
                        image = image.resize((max_width, int(image.height * ratio)))
                    buf = io.BytesIO()
                    image.convert("RGB").save(buf, format="JPEG", quality=quality)
                    frames.append(Frame(timestamp_sec=ts, jpeg_b64=base64.standard_b64encode(buf.getvalue()).decode()))
                    break
    return frames
