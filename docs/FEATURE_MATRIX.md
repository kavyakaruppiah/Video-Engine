# Feature matrix

| Area | Status | Notes |
|---|---|---|
| Projects and reopening | Implemented | SQLite project and asset metadata |
| Upload validation | Implemented | Extension, size, FFprobe stream checks |
| Audio extraction | Implemented | FFmpeg WAV extraction on upload when audio exists |
| Local transcription | Optional | faster-whisper adapter; install separately and download model |
| Word timestamps | Optional | Provided by faster-whisper when available |
| Editable transcript persistence | Implemented | JSON payload stored per asset |
| Rule-based prompt plans | Implemented | Typed allowlisted plans and honest decisions |
| Ollama plans | Optional | Local `/api/generate`, schema-constrained response |
| Trim, crop/resize, color, fade, text | Implemented | Deterministic FFmpeg export operations |
| Speed change | Implemented | Video PTS adjustment; audio pitch correction pending |
| Audio mute/volume | Planned | Registry accepts intent; renderer must not silently ignore it |
| Timeline snapshots | Implemented | SQLite history snapshots and deterministic hashes |
| Real MP4 export and verification | Implemented | Video stream and requested audio checked |
| Multi-clip concatenation | Pending | Current export selects the first video source |
| SRT/VTT export/import | Pending | Transcript JSON is currently available |
| Scene detection, diarization, captions | Pending/optional | Requires additional dependencies and UI work |
| Streaming render jobs | Pending | Current render endpoint is synchronous |
