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
    return TestClient(module.app), module

def test_health(client):
    response = client[0].get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_prompt_validation_and_plan(client):
    api = client[0]
    assert api.post("/api/plan", json={"prompt": ""}).status_code == 422
    response = api.post("/api/plan", json={"prompt": "trim from 2 to 8, make it vertical and add text 'Launch day'"})
    assert response.status_code == 200
    assert {item["type"] for item in response.json()["operations"]} >= {"trim", "crop_resize", "text_overlay"}

def test_invalid_operation_timestamps(client):
    response = client[0].post("/api/export", json={"project_id": "missing", "asset_ids": ["missing"], "operations": [{"type": "trim", "start": 8, "end": 2}]})
    assert response.status_code == 422

def test_project_and_invalid_upload(client):
    api = client[0]
    project = api.post("/api/projects", json={"name": "Test"}).json()
    response = api.post(f"/api/projects/{project['id']}/assets", files={"files": ("bad.txt", b"not media", "text/plain")})
    assert response.status_code == 415

def test_real_ffmpeg_export(client, tmp_path):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe not installed")
    source = tmp_path / "sample.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=size=160x90:rate=10", "-f", "lavfi", "-i", "sine=frequency=1000", "-t", "1", "-pix_fmt", "yuv420p", "-c:v", "libx264", "-c:a", "aac", str(source)], capture_output=True, check=True)
    api = client[0]
    project = api.post("/api/projects", json={"name": "Export"}).json()
    upload = api.post(f"/api/projects/{project['id']}/assets", files={"files": ("sample.mp4", source.read_bytes(), "video/mp4")})
    assert upload.status_code == 200
    asset = upload.json()[0]
    exported = api.post("/api/export", json={"project_id": project["id"], "asset_ids": [asset["id"]], "operations": [{"type": "trim", "start": 0, "end": 0.8}], "preserve_audio": True})
    assert exported.status_code == 200
    assert exported.json()["metadata"]["has_video"] is True
    assert exported.json()["metadata"]["has_audio"] is True
    assert api.get(exported.json()["url"]).status_code == 200
