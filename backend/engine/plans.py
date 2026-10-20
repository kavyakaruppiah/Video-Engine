from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from pydantic import BaseModel, Field, model_validator

SUPPORTED_OPERATIONS = {"trim", "crop_resize", "color", "text_overlay", "fade", "speed", "mute", "volume"}

class EditOperation(BaseModel):
    type: str
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    width: int | None = Field(default=None, gt=0, le=4096)
    height: int | None = Field(default=None, gt=0, le=4096)
    amount: float | None = Field(default=None, ge=-1, le=1)
    factor: float | None = Field(default=None, gt=0, le=8)
    text: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_operation(self):
        if self.type not in SUPPORTED_OPERATIONS:
            raise ValueError(f"operation is not supported: {self.type}")
        if self.type == "trim" and (self.start is None or self.end is None or self.end <= self.start):
            raise ValueError("trim requires end greater than start")
        if self.type == "crop_resize" and (self.width is None or self.height is None):
            raise ValueError("crop_resize requires width and height")
        if self.type == "text_overlay" and not self.text:
            raise ValueError("text_overlay requires text")
        if self.type == "speed" and self.factor is None:
            raise ValueError("speed requires factor")
        return self

class EditPlan(BaseModel):
    decision: str
    interpreted_request: str
    operations: list[EditOperation] = Field(default_factory=list, max_length=30)
    affected_content: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    reason: str = ""
    interpreter: str = "rules"
    requires_review: bool = True

    @model_validator(mode="after")
    def validate_decision(self):
        if self.decision not in {"applied", "needs_clarification", "rejected"}:
            raise ValueError("invalid decision")
        return self

def timeline_hash(source_ids: list[str], operations: list[EditOperation], settings: dict[str, Any] | None = None) -> str:
    payload = {"source_ids": source_ids, "operations": [op.model_dump(mode="json") for op in operations], "settings": settings or {}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def rule_plan(prompt: str, asset_id: str | None = None) -> EditPlan:
    original = prompt.strip()
    p = original.lower()
    operations: list[EditOperation] = []
    warnings: list[str] = []
    trim = re.search(r"(?:trim|cut|keep).*?(\d+(?:\.\d+)?)\s*(?:to|until|-|through)\s*(\d+(?:\.\d+)?)", p)
    if trim:
        operations.append(EditOperation(type="trim", start=float(trim.group(1)), end=float(trim.group(2))))
    if "vertical" in p or "9:16" in p:
        operations.append(EditOperation(type="crop_resize", width=1080, height=1920))
    elif "square" in p or "1:1" in p:
        operations.append(EditOperation(type="crop_resize", width=1080, height=1080))
    if "fade" in p:
        operations.append(EditOperation(type="fade", amount=1))
    if "mute" in p:
        operations.append(EditOperation(type="mute"))
    if "faster" in p:
        operations.append(EditOperation(type="speed", factor=1.25))
    if "slower" in p:
        operations.append(EditOperation(type="speed", factor=0.8))
    if "brightness" in p or "contrast" in p:
        operations.append(EditOperation(type="color", amount=0.1))
    match = re.search(r"(?:text|title|overlay)\s*[=:]?\s*[\"']([^\"']+)[\"']", original, re.I)
    if match:
        operations.append(EditOperation(type="text_overlay", text=match.group(1)))
    for term in ("stabilize", "transcribe", "remove background", "motion tracking", "music", "speaker labels", "scene-aware"):
        if term in p:
            warnings.append(f"Unsupported or optional capability requested: {term}")
    if warnings and not operations:
        return EditPlan(decision="rejected", interpreted_request=original, warnings=warnings, reason="The requested capability is unavailable in this local build", affected_content=[asset_id] if asset_id else [])
    if not operations:
        return EditPlan(decision="needs_clarification", interpreted_request=original, reason="No deterministic supported operation was identified", warnings=["Try specifying a trim range, aspect ratio, speed, mute, fade, color, or quoted overlay text"], affected_content=[asset_id] if asset_id else [])
    return EditPlan(decision="applied", interpreted_request=original, operations=operations, warnings=warnings, reason="A deterministic allowlisted plan was generated", affected_content=[asset_id] if asset_id else [])
