# Video Engine

A runnable AI-assisted video editor built with FastAPI, SQLite, FFmpeg/FFprobe, and a browser workspace.

## Requirements

- Python 3.11+
- FFmpeg 6+ with `ffmpeg` and `ffprobe` on `PATH`
- Optional Ollama for a future provider integration; the current planner is deterministic and works without paid AI keys

## Run

```bash
git clone https://github.com/kavyakaruppiah/Video-Engine.git
cd Video-Engine
git checkout feature/ai-video-editor
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app:app --reload
```

Open `http://127.0.0.1:8000`. API documentation is available at `/docs`.

## Tests

```bash
pytest -q
```

The test suite covers startup, project persistence, invalid upload types, prompt validation, unsupported operations, invalid timestamps, synthetic media upload, FFprobe metadata, and a real FFmpeg MP4 export when FFmpeg is installed. Without FFmpeg, the integration test is skipped rather than falsely reported as passing.

## Supported workflow

1. Create or reopen a project.
2. Import video/audio files. The server validates extensions, size, and actual FFprobe streams.
3. Select a video to preview it and inspect duration, dimensions, frame rate, codecs, aspect ratio, and audio presence.
4. Enter a prompt and review the typed allowlisted plan.
5. Use the timeline to select, order visually, delete, undo, and redo clips.
6. Export an MP4. The server validates project ownership, operation bounds, stream mapping, output readability, dimensions, and audio preservation.

Supported deterministic operations are trimming, aspect-ratio-safe crop/resize with padding, brightness/contrast adjustment, text overlay, and fades. Unsupported effects are reported instead of executed. No model-generated shell command is ever run.

## Environment variables

| Variable | Default | Purpose |
|---|---:|---|
| `VIDEO_ENGINE_DATA` | `./data` | Media, exports, and SQLite location |
| `MAX_UPLOAD_MB` | `512` | Maximum upload size |

## Known limitations

The current first version exports the selected video asset; it does not yet concatenate multiple source clips, persist timeline operation JSON, show streaming render progress, or provide transcription/captions, motion tracking, complex transitions, or music generation. Ollama provider wiring is not enabled; the deterministic planner is the safe fallback.
