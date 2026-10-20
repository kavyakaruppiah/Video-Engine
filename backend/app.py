from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.engine.interpreter import Interpreter
from backend.engine.persistence import add_snapshot, get_transcript, initialize, list_snapshots, save_transcript
from backend.engine.plans import EditOperation, EditPlan, timeline_hash
from backend.engine.transcription import extract_audio, transcribe

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("VIDEO_ENGINE_DATA", ROOT / "data"))
MEDIA, EXPORTS, AUDIO = DATA / "media", DATA / "exports", DATA / "audio"
DB = DATA / "projects.sqlite3"
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "512")) * 1024 * 1024
for folder in (MEDIA, EXPORTS, AUDIO): folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Engine", version="2.1.0", openapi_url="/api/openapi.json")

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
class PlanRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    asset_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
class TranscriptEdit(BaseModel): payload: dict[str, Any]
class SnapshotRequest(BaseModel): label: str = Field(min_length=1, max_length=100); snapshot: dict[str, Any]
class ExportRequest(BaseModel):
    project_id: str
    asset_ids: list[str] = Field(min_length=1, max_length=50)
    operations: list[EditOperation] = Field(default_factory=list, max_length=30)
    preserve_audio: bool = True

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    initialize(conn)
    conn.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, metadata TEXT NOT NULL)")
    columns = {row[1] for row in conn.execute("PRAGMA table_info(assets)")}
    if "audio_path" not in columns:
        conn.execute("ALTER TABLE assets ADD COLUMN audio_path TEXT")
    conn.commit()
    return conn

def probe(path: Path) -> dict[str, Any]:
    if not shutil.which("ffprobe"):
        raise HTTPException(503, "FFprobe is required and was not found on PATH")
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True)
        info = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "Unable to read media with FFprobe") from exc
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    raw = (video or {}).get("r_frame_rate", "0/1").split("/")
    fps = round(float(raw[0]) / float(raw[1]), 3) if len(raw) == 2 and float(raw[1]) else 0
    duration = float(info.get("format", {}).get("duration") or (video or {}).get("duration") or (audio or {}).get("duration") or 0)
    return {"duration": duration, "width": (video or {}).get("width"), "height": (video or {}).get("height"), "fps": fps, "video_codec": (video or {}).get("codec_name"), "audio_codec": (audio or {}).get("codec_name"), "has_audio": audio is not None, "has_video": video is not None, "aspect_ratio": f"{video['width']}:{video['height']}" if video and video.get('width') and video.get('height') else None}

def project_exists(project_id: str) -> bool:
    return db().execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is not None

def asset_row(asset_id: str, project_id: str | None = None):
    query, args = "SELECT * FROM assets WHERE id=?", [asset_id]
    if project_id:
        query += " AND project_id=?"; args.append(project_id)
    row = db().execute(query, args).fetchone()
    if not row: raise HTTPException(404, "Asset not found in this project")
    return row

def asset_json(row):
    return {"id": row["id"], "name": row["name"], "metadata": json.loads(row["metadata"]), "url": f"/api/assets/{row['id']}/file"}

def srt_time(seconds: float) -> str:
    ms = max(0, int(seconds * 1000)); h, ms = divmod(ms, 3600000); m, ms = divmod(ms, 60000); s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def transcript_srt(payload: dict[str, Any]) -> str:
    lines = []
    for i, segment in enumerate(payload.get("segments", []), 1):
        lines += [str(i), f"{srt_time(segment.get('start', 0))} --> {srt_time(segment.get('end', 0))}", segment.get("text", "").strip(), ""]
    return "\n".join(lines)

@app.get("/api/health")
def health(): return {"status": "ok", "ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe")), "ollama": Interpreter().available}

@app.post("/api/projects")
def create_project(body: ProjectIn):
    project_id = str(uuid.uuid4()); name = body.name.strip(); conn = db(); conn.execute("INSERT INTO projects(id,name) VALUES(?,?)", (project_id, name)); conn.commit(); return {"id": project_id, "name": name}

@app.get("/api/projects")
def list_projects(): return [dict(row) for row in db().execute("SELECT * FROM projects ORDER BY created_at DESC")]

@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    if not project_exists(project_id): raise HTTPException(404, "Project not found")
    project = db().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone(); assets = [asset_json(r) for r in db().execute("SELECT * FROM assets WHERE project_id=? ORDER BY rowid", (project_id,))]
    return {"project": dict(project), "assets": assets, "timeline_hash": timeline_hash([a["id"] for a in assets], [])}

@app.post("/api/projects/{project_id}/assets")
async def upload(project_id: str, files: list[UploadFile] = File(...)):
    if not project_exists(project_id): raise HTTPException(404, "Project not found")
    results = []
    for incoming in files:
        suffix = Path(incoming.filename or "").suffix.lower()
        if suffix not in VIDEO_EXTS | AUDIO_EXTS: raise HTTPException(415, f"Unsupported media type: {suffix or 'unknown'}")
        asset_id = str(uuid.uuid4()); destination = MEDIA / f"{asset_id}{suffix}"; total = 0
        try:
            with destination.open("wb") as out:
                while chunk := await incoming.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD: raise HTTPException(413, "File exceeds configured upload limit")
                    out.write(chunk)
            metadata = probe(destination)
            if not metadata["has_video"] and not metadata["has_audio"]: raise HTTPException(422, "Media has no audio or video stream")
            audio_path = None
            if metadata["has_audio"]:
                extracted = extract_audio(destination, AUDIO / f"{asset_id}.wav")
                audio_path = extracted.get("path") if extracted.get("status") == "completed" else None
            conn = db(); conn.execute("INSERT INTO assets(id,project_id,name,path,metadata,audio_path) VALUES(?,?,?,?,?,?)", (asset_id, project_id, incoming.filename or destination.name, str(destination), json.dumps(metadata), audio_path)); conn.commit()
            results.append(asset_json(db().execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()))
        except Exception:
            destination.unlink(missing_ok=True); raise
        finally: await incoming.close()
    return results

@app.get("/api/assets/{asset_id}/file")
def serve_asset(asset_id: str):
    row = asset_row(asset_id); return FileResponse(row["path"], filename=row["name"])

@app.get("/api/assets/{asset_id}/probe")
def get_probe(asset_id: str): return json.loads(asset_row(asset_id)["metadata"])

@app.post("/api/assets/{asset_id}/transcribe")
def transcribe_asset(asset_id: str, language: str | None = None):
    row = asset_row(asset_id)
    if not row["audio_path"]: raise HTTPException(422, "This asset has no audio stream or extraction failed")
    result = transcribe(Path(row["audio_path"]), language); save_transcript(db(), asset_id, result); return result

@app.get("/api/assets/{asset_id}/transcript")
def read_transcript(asset_id: str):
    asset_row(asset_id); return get_transcript(db(), asset_id) or {"status": "not_started", "segments": [], "words": []}

@app.put("/api/assets/{asset_id}/transcript")
def edit_transcript(asset_id: str, body: TranscriptEdit):
    asset_row(asset_id); save_transcript(db(), asset_id, body.payload); return body.payload

@app.get("/api/assets/{asset_id}/transcript.srt")
def download_srt(asset_id: str):
    asset_row(asset_id); payload = get_transcript(db(), asset_id) or {"segments": []}
    target = DATA / "downloads"; target.mkdir(exist_ok=True); path = target / f"{asset_id}.srt"; path.write_text(transcript_srt(payload), encoding="utf-8")
    return FileResponse(path, media_type="application/x-subrip", filename=f"{asset_id}.srt")

@app.post("/api/plan", response_model=EditPlan)
def plan(body: PlanRequest): return Interpreter().interpret(body.prompt, body.asset_id, body.context)

@app.post("/api/projects/{project_id}/history")
def create_snapshot(project_id: str, body: SnapshotRequest):
    if not project_exists(project_id): raise HTTPException(404, "Project not found")
    return {"id": add_snapshot(db(), project_id, body.label, body.snapshot), "label": body.label}

@app.get("/api/projects/{project_id}/history")
def history(project_id: str):
    if not project_exists(project_id): raise HTTPException(404, "Project not found")
    return list_snapshots(db(), project_id)

@app.post("/api/export")
def export(body: ExportRequest):
    if not shutil.which("ffmpeg"): raise HTTPException(503, "FFmpeg is required and was not found on PATH")
    if not project_exists(body.project_id): raise HTTPException(404, "Project not found")
    rows = [asset_row(asset_id, body.project_id) for asset_id in body.asset_ids]; source = Path(rows[0]["path"]); metadata = json.loads(rows[0]["metadata"])
    if not metadata.get("has_video"): raise HTTPException(422, "The selected source must contain a video stream")
    duration = float(metadata.get("duration") or 0); video_filters = []; audio_filters = []; trim = None
    for operation in body.operations:
        if operation.type == "trim":
            if operation.end > duration: raise HTTPException(422, "Trim end exceeds source duration")
            trim = operation
        elif operation.type == "crop_resize": video_filters.append(f"scale={operation.width}:{operation.height}:force_original_aspect_ratio=decrease,pad={operation.width}:{operation.height}:(ow-iw)/2:(oh-ih)/2")
        elif operation.type == "color": video_filters.append(f"eq=brightness={operation.amount or 0}:contrast={1 + (operation.amount or 0)}")
        elif operation.type == "fade": video_filters.append("fade=t=in:st=0:d=1,fade=t=out:st=0:d=1")
        elif operation.type == "text_overlay": video_filters.append("drawtext=text='" + operation.text.replace("'", "\\'") + "':x=(w-text_w)/2:y=h-100:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.5")
        elif operation.type == "speed": video_filters.append(f"setpts=PTS/{operation.factor}")
        elif operation.type == "mute": audio_filters.append("volume=0")
        elif operation.type == "volume": audio_filters.append(f"volume={max(0, operation.amount or 1)}")
    output = EXPORTS / f"{uuid.uuid4()}.mp4"; cmd = ["ffmpeg", "-y"]
    if trim: cmd += ["-ss", str(trim.start), "-to", str(trim.end)]
    cmd += ["-i", str(source)]
    if video_filters: cmd += ["-vf", ",".join(video_filters)]
    if audio_filters: cmd += ["-af", ",".join(audio_filters)]
    cmd += ["-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    cmd += ["-map", "0:a:0?", "-c:a", "aac"] if body.preserve_audio and metadata.get("has_audio") else ["-an"]
    cmd += ["-movflags", "+faststart", str(output)]
    try: subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    except subprocess.CalledProcessError as exc: raise HTTPException(422, f"Export failed: {exc.stderr[-1000:]}") from exc
    verified = probe(output)
    if not verified.get("has_video") or (body.preserve_audio and metadata.get("has_audio") and not verified.get("has_audio")): raise HTTPException(422, "Export verification failed")
    return {"id": output.stem, "url": f"/api/exports/{output.name}", "metadata": verified, "status": "completed", "timeline_hash": timeline_hash(body.asset_ids, body.operations)}

@app.get("/api/exports/{filename}")
def serve_export(filename: str):
    path = EXPORTS / Path(filename).name
    if not path.exists(): raise HTTPException(404, "Export not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)

app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
