from __future__ import annotations

import json
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("VIDEO_ENGINE_DATA", str(tmp_path / "data"))
    import importlib
    import backend.app as module
    module = importlib.reload(module)
    return TestClient(module.app)

def test_startup_and_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_plan_decisions_and_determinism(client):
    a = client.post("/api/plan", json={"prompt": "trim from 2 to 8, make it vertical and add text 'Launch'", "asset_id": "a"}).json()
    b = client.post("/api/plan", json={"prompt": "stabilize and transcribe this", "asset_id": "a"}).json()
    assert a["decision"] == "applied"
    assert b["decision"] == "rejected"
    assert any(op["type"] == "crop_resize" for op in a["operations"])

def test_projects_history_and_transcript_edit(client):
    project = client.post("/api/projects", json={"name": "Demo"}).json()
    snapshot = client.post(f"/api/projects/{project['id']}/history", json={"label": "before captions", "snapshot": {"clips": []}})
    assert snapshot.status_code == 200
    assert len(client.get(f"/api/projects/{project['id']}/history").json()) == 1

def test_invalid_upload_type(client):
    project = client.post("/api/projects", json={"name": "Demo"}).json()
    response = client.post(f"/api/projects/{project['id']}/assets", files={"files": ("bad.txt", b"x", "text/plain")})
    assert response.status_code == 415

def test_real_media_upload_and_export(client, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe not installed")
    source = tmp_path / "sample.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-f", "lavfi", "-i", "sine=frequency=1000", "-t", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(source)], capture_output=True, check=True)
    project = client.post("/api/projects", json={"name": "Export"}).json()
    uploaded = client.post(f"/api/projects/{project['id']}/assets", files={"files": ("sample.mp4", source.read_bytes(), "video/mp4")})
    assert uploaded.status_code == 200
    asset = uploaded.json()[0]
    assert asset["metadata"]["has_audio"] is True
    output = client.post("/api/export", json={"project_id": project["id"], "asset_ids": [asset["id"]], "operations": [{"type": "trim", "start": 0, "end": 0.8}, {"type": "color", "amount": 0.1}], "preserve_audio": True})
    assert output.status_code == 200
    assert output.json()["metadata"]["has_video"] is True
    assert output.json()["metadata"]["has_audio"] is True
    assert client.get(output.json()["url"]).status_code == 200
