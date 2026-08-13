"""Versioned, non-medical learning catalog."""

from __future__ import annotations

import json
from importlib.resources import files
from typing import Any


def load_catalog() -> dict[str, dict[str, Any]]:
    resource = files("mudra_interact_core").joinpath("catalog/mudra_catalog.json")
    payload = json.loads(resource.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else []
    return {
        str(item.get("gesture_id")): item
        for item in entries
        if isinstance(item, dict) and str(item.get("gesture_id") or "").strip()
    }


def lookup(gesture_id: str) -> dict[str, Any] | None:
    return load_catalog().get(str(gesture_id).strip().lower())
