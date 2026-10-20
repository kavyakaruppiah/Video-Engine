from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def extract_audio(source: Path, destination: Path) -> dict[str, Any]:
    if not shutil.which("ffmpeg"):
        return {"status": "unavailable", "reason": "FFmpeg is not installed"}
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(destination)], capture_output=True, text=True, timeout=180, check=True)
        return {"status": "completed", "path": str(destination), "format": "wav", "sample_rate": 16000, "channels": 1}
    except subprocess.CalledProcessError as exc:
        return {"status": "failed", "reason": exc.stderr[-1000:]}

def transcribe(audio_path: Path, language: str | None = None) -> dict[str, Any]:
    model_name = os.getenv("WHISPER_MODEL", "small")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return {"status": "unavailable", "reason": "Install faster-whisper to enable local transcription", "segments": [], "words": []}
    try:
        model = WhisperModel(model_name, device=os.getenv("WHISPER_DEVICE", "cpu"), compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"))
        segments, info = model.transcribe(str(audio_path), language=language, word_timestamps=True)
        output_segments, words = [], []
        for segment in segments:
            segment_words = []
            for word in segment.words or []:
                item = {"id": f"w-{len(words):06d}", "text": word.word, "start": word.start, "end": word.end, "confidence": word.probability}
                words.append(item); segment_words.append(item)
            output_segments.append({"id": f"s-{len(output_segments):04d}", "text": segment.text, "start": segment.start, "end": segment.end, "words": segment_words})
        return {"status": "completed", "language": getattr(info, "language", language), "segments": output_segments, "words": words}
    except Exception as exc:
        return {"status": "failed", "reason": str(exc), "segments": [], "words": []}

def save_transcript(transcript: dict[str, Any], target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
