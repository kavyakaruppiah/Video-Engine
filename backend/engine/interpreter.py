from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .plans import EditPlan, rule_plan

class Interpreter:
    def __init__(self, url: str | None = None, model: str | None = None):
        self.url = (url or os.getenv("OLLAMA_URL", "")).rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL", "llama3.2")

    @property
    def available(self) -> bool:
        return bool(self.url)

    def interpret(self, prompt: str, asset_id: str | None = None, context: dict[str, Any] | None = None) -> EditPlan:
        if not self.url:
            return rule_plan(prompt, asset_id)
        schema = EditPlan.model_json_schema()
        body = {"model": self.model, "stream": False, "format": schema, "prompt": "Return only JSON matching this schema. Never output commands.\n" + json.dumps(schema) + "\nRequest: " + prompt}
        try:
            response = httpx.post(f"{self.url}/api/generate", json=body, timeout=90)
            response.raise_for_status()
            raw = response.json().get("response", "")
            return EditPlan.model_validate_json(raw)
        except (httpx.HTTPError, ValueError, json.JSONDecodeError):
            return rule_plan(prompt, asset_id)
