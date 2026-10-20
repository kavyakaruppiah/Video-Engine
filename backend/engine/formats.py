from __future__ import annotations
from typing import Any

def _stamp(seconds: float) -> str:
    total_ms = max(0, round(float(seconds) * 1000))
    hours, total_ms = divmod(total_ms, 3600000)
    minutes, total_ms = divmod(total_ms, 60000)
    secs, millis = divmod(total_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"

def to_vtt(payload: dict[str, Any]) -> str:
    lines = ["WEBVTT", ""]
    for segment in payload.get("segments", []):
        lines.extend([f"{_stamp(segment.get('start', 0))} --> {_stamp(segment.get('end', 0))}", str(segment.get("text", "")).strip(), ""])
    return "\n".join(lines)

def to_text(payload: dict[str, Any]) -> str:
    return "\n".join(str(segment.get("text", "")).strip() for segment in payload.get("segments", []))
