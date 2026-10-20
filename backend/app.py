from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("VIDEO_ENGINE_DATA", ROOT / "data"))
MEDIA = DATA / "media"
EXPORTS = DATA / "exports"
DB = DATA / "projects.sqlite3"
for folder in (MEDIA, EXPORTS): folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Engine", version="1.0.0")

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)

class PlanRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    asset_id: str | None = None

class Operation(BaseModel):
    type: str
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0, le=4096)
    height: int | None = Field(default=None, gt=0, le=4096)
    text: str | None = Field(default=None, max_length=200)
    amount: float | None = Field(default=None, ge=-1, le=1)

class ExportRequest(BaseModel):
    project_id: str
    asset_ids: list[str] = Field(min_length=1, max_length=50)
    operations: list[Operation] = Field(default_factory=list, max_length=30)
    preserve_audio: bool = True

ALLOWED = {"trim", "crop_resize", "color", "text_overlay", "fade", "split"}
VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, project_id TEXT, name TEXT, path TEXT, metadata TEXT)")
    conn.commit()
    return conn

def probe(path: Path) -> dict[str, Any]:
    if shutil.which("ffprobe") is None:
        raise HTTPException(503, "FFprobe is required and was not found on PATH")
    cmd = ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    try:
        raw = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=True)
        info = json.loads(raw.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise HTTPException(422, f"Unable to read media: {exc}") from exc
    streams = info.get("streams", [])
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(info.get("format", {}).get("duration") or (video or {}).get("duration") or 0)
    fps_raw = (video or {}).get("r_frame_rate", "0/1").split("/")
    fps = round(float(fps_raw[0]) / float(fps_raw[1]), 3) if len(fps_raw) == 2 and float(fps_raw[1]) else 0
    return {"duration": duration, "width": (video or {}).get("width"), "height": (video or {}).get("height"), "fps": fps, "video_codec": (video or {}).get("codec_name"), "audio_codec": (audio or {}).get("codec_name"), "has_audio": audio is not None, "aspect_ratio": f"{video.get('width')}:{video.get('height')}" if video else None}

def asset_row(asset_id: str):
    row = db().execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
    if not row: raise HTTPException(404, "Asset not found")
    return row

@app.get("/api/health")
def health(): return {"status": "ok", "ffmpeg": shutil.which("ffmpeg") is not None, "ffprobe": shutil.which("ffprobe") is not None}

@app.post("/api/projects")
def create_project(body: ProjectIn):
    project_id = str(uuid.uuid4()); conn = db(); conn.execute("INSERT INTO projects(id,name) VALUES(?,?)", (project_id, body.name)); conn.commit()
    return {"id": project_id, "name": body.name}

@app.get("/api/projects")
def list_projects(): return [dict(r) for r in db().execute("SELECT * FROM projects ORDER BY created_at DESC")]

@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = db().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
    if not project: raise HTTPException(404, "Project not found")
    assets = [dict(r) | {"metadata": json.loads(r["metadata"])} for r in db().execute("SELECT * FROM assets WHERE project_id=?", (project_id,))]
    return {"project": dict(project), "assets": assets}

@app.post("/api/projects/{project_id}/assets")
async def upload(project_id: str, files: list[UploadFile] = File(...)):
    if not db().execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone(): raise HTTPException(404, "Project not found")
    results = []
    for upload_file in files:
        suffix = Path(upload_file.filename or "").suffix.lower()
        if suffix not in VIDEO_EXTS | AUDIO_EXTS: raise HTTPException(415, f"Unsupported media type: {suffix or 'unknown'}")
        asset_id = str(uuid.uuid4()); destination = MEDIA / f"{asset_id}{suffix}"
        with destination.open("wb") as out: shutil.copyfileobj(upload_file.file, out)
        metadata = probe(destination); conn = db(); conn.execute("INSERT INTO assets VALUES(?,?,?,?,?)", (asset_id, project_id, upload_file.filename, str(destination), json.dumps(metadata))); conn.commit()
        results.append({"id": asset_id, "name": upload_file.filename, "metadata": metadata, "url": f"/api/assets/{asset_id}/file"})
    return results

@app.get("/api/assets/{asset_id}/file")
def serve_asset(asset_id: str):
    row = asset_row(asset_id); return FileResponse(row["path"], filename=row["name"])

@app.get("/api/assets/{asset_id}/probe")
def get_probe(asset_id: str): return json.loads(asset_row(asset_id)["metadata"])

def make_plan(prompt: str, asset_id: str | None) -> dict[str, Any]:
    p = prompt.lower(); operations: list[dict[str, Any]] = []; unsupported = []
    trim = re.search(r"(?:trim|cut|keep).*?(\d+(?:\.\d+)?)\s*(?:to|until|- )\s*(\d+(?:\.\d+)?)", p)
    if trim: operations.append({"type": "trim", "start": float(trim.group(1)), "end": float(trim.group(2))})
    if "square" in p or "1:1" in p: operations.append({"type": "crop_resize", "width": 1080, "height": 1080})
    elif "vertical" in p or "9:16" in p: operations.append({"type": "crop_resize", "width": 1080, "height": 1920})
    if "fade" in p: operations.append({"type": "fade", "amount": 1})
    if "brightness" in p or "contrast" in p: operations.append({"type": "color", "amount": 0.1})
    match = re.search(r"(?:text|title|overlay)\s*[=:]?\s*[\"']([^\"']+)[\"']", prompt, re.I)
    if match: operations.append({"type": "text_overlay", "text": match.group(1)})
    for term in ("stabilize", "transcribe", "remove background", "motion tracking", "music"):
        if term in p: unsupported.append(term)
    if not operations and not unsupported: unsupported.append("No supported edit was detected")
    return {"asset_id": asset_id, "operations": operations, "unsupported": unsupported, "requires_review": True}

@app.post("/api/plan")
def plan(body: PlanRequest): return make_plan(body.prompt, body.asset_id)

@app.post("/api/export")
def export(body: ExportRequest):
    if shutil.which("ffmpeg") is None: raise HTTPException(503, "FFmpeg is required and was not found on PATH")
    rows = [asset_row(i) for i in body.asset_ids]
    if any(json.loads(r["metadata"]).get("duration", 0) <= 0 for r in rows): raise HTTPException(422, "All assets must have a readable duration")
    for op in body.operations:
        if op.type not in ALLOWED: raise HTTPException(422, f"Unsupported operation: {op.type}")
        if op.type == "trim" and (op.end is None or op.start is None or op.end <= op.start): raise HTTPException(422, "Trim requires end greater than start")
    source = Path(rows[0]["path"]); output = EXPORTS / f"{uuid.uuid4()}.mp4"
    vf: list[str] = []
    af: list[str] = []
    for op in body.operations:
        if op.type == "crop_resize" and op.width and op.height: vf.append(f"scale={op.width}:{op.height}:force_original_aspect_ratio=decrease,pad={op.width}:{op.height}:(ow-iw)/2:(oh-ih)/2")
        elif op.type == "color" and op.amount is not None: vf.append(f"eq=brightness={op.amount}:contrast={1 + op.amount}")
        elif op.type == "fade": vf.append("fade=t=in:st=0:d=1,fade=t=out:st=0:d=1")
        elif op.type == "text_overlay" and op.text: vf.append("drawtext=text='" + op.text.replace("'", "\\'") + "':x=(w-text_w)/2:y=h-100:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.5")
    cmd = ["ffmpeg", "-y", "-i", str(source)]
    if any(op.type == "trim" for op in body.operations):
        trim = next(op for op in body.operations if op.type == "trim"); cmd += ["-ss", str(trim.start), "-to", str(trim.end)]
    if vf: cmd += ["-vf", ",".join(vf)]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    cmd += ["-c:a", "aac"] if body.preserve_audio else ["-an"]
    cmd += [str(output)]
    try: subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    except subprocess.CalledProcessError as exc: raise HTTPException(422, f"Export failed: {exc.stderr[-1000:]}") from exc
    verified = probe(output)
    return {"id": output.stem, "url": f"/api/exports/{output.name}", "metadata": verified, "status": "completed"}

@app.get("/api/exports/{filename}")
def serve_export(filename: str):
    path = EXPORTS / Path(filename).name
    if not path.exists(): raise HTTPException(404, "Export not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)

app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
