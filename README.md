# Video Engine

A runnable AI-assisted video editor built with FastAPI, SQLite, FFmpeg/FFprobe, and a browser workspace.

## Requirements

- Python 3.11+
- FFmpeg 6+ (`ffmpeg` and `ffprobe` on PATH)
- Optional Ollama for richer prompt planning (`OLLAMA_URL`, `OLLAMA_MODEL`)

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

Open http://127.0.0.1:8000. The API docs are at `/docs`.

## Tests

```bash
pytest -q
```

Tests use a temporary SQLite database and generate a short synthetic MP4 with FFmpeg when available.

## Features

- Project create/list/reopen with SQLite metadata
- Multi-file video/audio upload with size/type validation
- FFprobe metadata inspection
- Browser video preview, seeking, volume, media library, timeline selection
- Natural-language prompt parsing into validated typed plans
- Deterministic trimming, ordering, crop/resize, color, text overlay, fades, and audio preservation
- MP4 export with progress and downloadable output
- Undo/redo timeline history in the client

## Environment

| Variable | Default | Purpose |
|---|---:|---|
| `VIDEO_ENGINE_DATA` | `./data` | Media, exports, and SQLite location |
| `MAX_UPLOAD_MB` | `512` | Maximum upload size |
| `OLLAMA_URL` | unset | Optional local Ollama endpoint |
| `OLLAMA_MODEL` | `llama3.2` | Optional Ollama model |

## Limitations

The first version intentionally supports a safe allowlist of operations. Complex transitions, motion tracking, captions/transcription, music generation, and arbitrary model-generated FFmpeg expressions are reported as unsupported. The server never executes model-provided shell commands.
