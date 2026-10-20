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
from pydantic import BaseModel, Field, model_validator

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.getenv("VIDEO_ENGINE_DATA", ROOT / "data"))
MEDIA, EXPORTS, DB = DATA / "media", DATA / "exports", DATA / "projects.sqlite3"
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "512")) * 1024 * 1024
for folder in (MEDIA, EXPORTS): folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Video Engine", version="1.1.0")

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

    @model_validator(mode="after")
    def validate_operation(self):
        if self.type not in {"trim", "crop_resize", "color", "text_overlay", "fade"}:
            raise ValueError("operation is not supported")
        if self.type == "trim" and (self.start is None or self.end is None or self.end <= self.start):
            raise ValueError("trim requires end greater than start")
        if self.type == "crop_resize" and (self.width is None or self.height is None):
            raise ValueError("crop_resize requires width and height")
        if self.type == "text_overlay" and not self.text:
            raise ValueError("text_overlay requires text")
        return self

class ExportRequest(BaseModel):
    project_id: str
    asset_ids: list[str] = Field(min_length=1, max_length=50)
    operations: list[Operation] = Field(default_factory=list, max_length=30)
    preserve_audio: bool = True

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm", ".avi"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE IF NOT EXISTS projects (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    conn.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, project_id TEXT NOT NULL, name TEXT NOT NULL, path TEXT NOT NULL, metadata TEXT NOT NULL)")
    conn.commit()
    return conn

def probe(path: Path) -> dict[str, Any]:
    if not shutil.which("ffprobe"): raise HTTPException(503, "FFprobe is required and was not found on PATH")
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, text=True, timeout=30, check=True)
        info = json.loads(result.stdout)
    except (subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise HTTPException(422, "Unable to read media with FFprobe") from exc
    streams = info.get("streams", []); video = next((s for s in streams if s.get("codec_type") == "video"), None); audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    raw_fps = (video or {}).get("r_frame_rate", "0/1").split("/")
    fps = round(float(raw_fps[0]) / float(raw_fps[1]), 3) if len(raw_fps) == 2 and float(raw_fps[1]) else 0
    duration = float(info.get("format", {}).get("duration") or (video or {}).get("duration") or (audio or {}).get("duration") or 0)
    return {"duration": duration, "width": (video or {}).get("width"), "height": (video or {}).get("height"), "fps": fps, "video_codec": (video or {}).get("codec_name"), "audio_codec": (audio or {}).get("codec_name"), "has_audio": audio is not None, "has_video": video is not None, "aspect_ratio": f"{video['width']}:{video['height']}" if video and video.get("width") and video.get("height") else None}

def project_exists(project_id: str) -> bool:
    return db().execute("SELECT 1 FROM projects WHERE id=?", (project_id,)).fetchone() is not None

def asset_row(asset_id: str, project_id: str | None = None):
    query, args = "SELECT * FROM assets WHERE id=?", [asset_id]
    if project_id: query += " AND project_id=?"; args.append(project_id)
    row = db().execute(query, args).fetchone()
    if not row: raise HTTPException(404, "Asset not found in this project")
    return row

@app.get("/api/health")
def health(): return {"status": "ok", "ffmpeg": bool(shutil.which("ffmpeg")), "ffprobe": bool(shutil.which("ffprobe"))}

@app.post("/api/projects")
def create_project(body: ProjectIn):
    project_id = str(uuid.uuid4()); conn = db(); conn.execute("INSERT INTO projects(id,name) VALUES(?,?)", (project_id, body.name.strip())); conn.commit()
    return {"id": project_id, "name": body.name.strip()}

@app.get("/api/projects")
def list_projects(): return [dict(row) for row in db().execute("SELECT * FROM projects ORDER BY created_at DESC")]

@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    if not project_exists(project_id): raise HTTPException(404, "Project not found")
    assets = []
    for row in db().execute("SELECT * FROM assets WHERE project_id=? ORDER BY rowid", (project_id,)):
        assets.append({"id": row["id"], "name": row["name"], "metadata": json.loads(row["metadata"]), "url": f"/api/assets/{row['id']}/file"})
    return {"project": dict(db().execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()), "assets": assets}

@app.post("/api/projects/{project_id}/assets")
async def upload(project_id: str, files: list[UploadFile] = File(...)):
    if not project_exists(project_id): raise HTTPException(404, "Project not found")
    results = []
    for upload_file in files:
        suffix = Path(upload_file.filename or "").suffix.lower()
        if suffix not in VIDEO_EXTS | AUDIO_EXTS: raise HTTPException(415, f"Unsupported media type: {suffix or 'unknown'}")
        asset_id = str(uuid.uuid4()); destination = MEDIA / f"{asset_id}{suffix}"; total = 0
        try:
            with destination.open("wb") as out:
                while chunk := await upload_file.read(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_UPLOAD: raise HTTPException(413, f"File exceeds {MAX_UPLOAD // 1024 // 1024} MB limit")
                    out.write(chunk)
            metadata = probe(destination)
            if not metadata["has_video"] and not metadata["has_audio"]: raise HTTPException(422, "Media has no audio or video stream")
            conn = db(); conn.execute("INSERT INTO assets VALUES(?,?,?,?,?)", (asset_id, project_id, upload_file.filename or destination.name, str(destination), json.dumps(metadata))); conn.commit()
            results.append({"id": asset_id, "name": upload_file.filename, "metadata": metadata, "url": f"/api/assets/{asset_id}/file"})
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        finally: await upload_file.close()
    return results

@app.get("/api/assets/{asset_id}/file")
def serve_asset(asset_id: str):
    row = asset_row(asset_id); return FileResponse(row["path"], filename=row["name"])

@app.get("/api/assets/{asset_id}/probe")
def get_probe(asset_id: str): return json.loads(asset_row(asset_id)["metadata"])

def make_plan(prompt: str, asset_id: str | None):
    p = prompt.lower(); operations = []; unsupported = []
    trim = re.search(r"(?:trim|cut|keep).*?(\d+(?:\.\d+)?)\s*(?:to|until|-|through)\s*(\d+(?:\.\d+)?)", p)
    if trim: operations.append({"type": "trim", "start": float(trim.group(1)), "end": float(trim.group(2))})
    if "square" in p or "1:1" in p: operations.append({"type": "crop_resize", "width": 1080, "height": 1080})
    elif "vertical" in p or "9:16" in p: operations.append({"type": "crop_resize", "width": 1080, "height": 1920})
    if "fade" in p: operations.append({"type": "fade", "amount": 1})
    if "brightness" in p or "contrast" in p: operations.append({"type": "color", "amount": 0.1})
    match = re.search(r"(?:text|title|overlay)\s*[=:]?\s*[\"']([^\"']+)[\"']", prompt, re.I)
    if match: operations.append({"type": "text_overlay", "text": match.group(1)})
    for term in ("stabilize", "transcribe", "remove background", "motion tracking", "music", "split"):
        if term in p: unsupported.append(term)
    if not operations and not unsupported: unsupported.append("No supported edit was detected")
    return {"asset_id": asset_id, "operations": operations, "unsupported": unsupported, "requires_review": True}

@app.post("/api/plan")
def plan(body: PlanRequest): return make_plan(body.prompt, body.asset_id)

@app.post("/api/export")
def export(body: ExportRequest):
    if not shutil.which("ffmpeg"): raise HTTPException(503, "FFmpeg is required and was not found on PATH")
    if not project_exists(body.project_id): raise HTTPException(404, "Project not found")
    rows = [asset_row(asset_id, body.project_id) for asset_id in body.asset_ids]
    source = Path(rows[0]["path"]); metadata = json.loads(rows[0]["metadata"])
    if not metadata.get("has_video"): raise HTTPException(422, "The selected source must contain a video stream")
    duration = float(metadata.get("duration") or 0)
    for operation in body.operations:
        if operation.type == "trim" and operation.end > duration: raise HTTPException(422, "Trim end exceeds source duration")
    filters = []
    for operation in body.operations:
        if operation.type == "crop_resize": filters.append(f"scale={operation.width}:{operation.height}:force_original_aspect_ratio=decrease,pad={operation.width}:{operation.height}:(ow-iw)/2:(oh-ih)/2")
        elif operation.type == "color": filters.append(f"eq=brightness={operation.amount or 0}:contrast={1 + (operation.amount or 0)}")
        elif operation.type == "fade": filters.append("fade=t=in:st=0:d=1,fade=t=out:st=0:d=1")
        elif operation.type == "text_overlay": filters.append("drawtext=text='" + operation.text.replace("'", "\\'") + "':x=(w-text_w)/2:y=h-100:fontsize=36:fontcolor=white:box=1:boxcolor=black@0.5")
    output = EXPORTS / f"{uuid.uuid4()}.mp4"; cmd = ["ffmpeg", "-y"]
    trim = next((item for item in body.operations if item.type == "trim"), None)
    if trim: cmd += ["-ss", str(trim.start), "-to", str(trim.end)]
    cmd += ["-i", str(source)]
    if filters: cmd += ["-vf", ",".join(filters)]
    cmd += ["-map", "0:v:0", "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p"]
    cmd += ["-map", "0:a:0?", "-c:a", "aac"] if body.preserve_audio and metadata.get("has_audio") else ["-an"]
    cmd += ["-movflags", "+faststart", str(output)]
    try: subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=True)
    except subprocess.CalledProcessError as exc: raise HTTPException(422, f"Export failed: {exc.stderr[-1000:]}") from exc
    verified = probe(output)
    if not verified.get("has_video") or verified.get("width") is None: raise HTTPException(422, "Export verification failed")
    if body.preserve_audio and metadata.get("has_audio") and not verified.get("has_audio"): raise HTTPException(422, "Export verification failed: audio was not preserved")
    return {"id": output.stem, "url": f"/api/exports/{output.name}", "metadata": verified, "status": "completed"}

@app.get("/api/exports/{filename}")
def serve_export(filename: str):
    path = EXPORTS / Path(filename).name
    if not path.exists(): raise HTTPException(404, "Export not found")
    return FileResponse(path, media_type="video/mp4", filename=path.name)

app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
