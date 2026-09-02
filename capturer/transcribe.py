"""Speech-to-text with faster-whisper (runs locally, free)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass
class Transcript:
    text: str
    language: str | None
    segments: list[tuple[float, float, str]]

    def timestamped(self) -> str:
        return "\n".join(f"[{s:06.1f}-{e:06.1f}] {t.strip()}" for s, e, t in self.segments)


@lru_cache(maxsize=2)
def _model(name: str):
    from faster_whisper import WhisperModel  # lazy import

    # int8 on CPU keeps memory low; the model is downloaded on first use (~500MB for "small").
    return WhisperModel(name, device="auto", compute_type="int8")


def transcribe(video_path: Path, model_name: str = "small") -> Transcript:
    """Transcribe the audio track of a video file. Whisper decodes the container itself."""
    model = _model(model_name)
    segments_iter, info = model.transcribe(str(video_path), vad_filter=True, beam_size=5)
    segments = [(float(s.start), float(s.end), s.text) for s in segments_iter]
    text = " ".join(t.strip() for _, _, t in segments).strip()
    return Transcript(text=text, language=getattr(info, "language", None), segments=segments)
