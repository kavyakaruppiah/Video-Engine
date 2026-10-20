from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-render")
_lock = threading.Lock()
_jobs: dict[str, dict[str, Any]] = {}


def submit(kind: str, work: Callable[[str], dict[str, Any]]) -> str:
    job_id = str(uuid.uuid4())
    with _lock:
        _jobs[job_id] = {"id": job_id, "kind": kind, "status": "queued", "progress": 0, "result": None, "error": None}

    def run() -> None:
        with _lock:
            _jobs[job_id]["status"] = "processing"
            _jobs[job_id]["progress"] = 10
        try:
            result = work(job_id)
            with _lock:
                _jobs[job_id].update(status="completed", progress=100, result=result)
        except Exception as exc:
            with _lock:
                _jobs[job_id].update(status="failed", progress=100, error=str(exc))

    _executor.submit(run)
    return job_id


def get(job_id: str) -> dict[str, Any] | None:
    with _lock:
        item = _jobs.get(job_id)
        return dict(item) if item else None
