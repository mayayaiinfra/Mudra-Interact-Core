"""Strict neutral v2 catalogue loader with detached lookup results."""

from __future__ import annotations

import copy
from importlib.resources import files
from pathlib import Path
from typing import Any

from .errors import MudraValidationError
from .validation import CATALOG_VERSION, MAX_STRING_SCALARS, parse_json_bytes, require_finite_float


CATALOG_IDS = frozenset(
    {"contact_thumb_index", "contact_thumb_middle", "contact_thumb_ring", "contact_thumb_middle_ring"}
)
CONTACT_PATTERNS = frozenset({"I", "M", "R", "M+R"})
ENTRY_FIELDS = {"gesture_id", "display_name", "contact_pattern", "confidence", "limitations", "provenance"}
PROVENANCE_FIELDS = {"status", "reference", "content_license"}
PROVENANCE_STATUSES = frozenset({"specification_source", "unverified_historical_alias"})


def _invalid() -> None:
    raise MudraValidationError("catalog_invalid")


def validate_catalog_payload(payload: Any) -> dict[str, Any]:
    if type(payload) is not dict or set(payload) != {"catalog_version", "entries"}:
        _invalid()
    if payload["catalog_version"] != CATALOG_VERSION or type(payload["entries"]) is not list:
        _invalid()
    entries = payload["entries"]
    if len(entries) != 4:
        _invalid()
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in entries:
        if type(entry) is not dict or set(entry) != ENTRY_FIELDS:
            _invalid()
        gesture_id = entry["gesture_id"]
        display_name = entry["display_name"]
        pattern = entry["contact_pattern"]
        if type(gesture_id) is not str or gesture_id not in CATALOG_IDS or gesture_id in seen:
            _invalid()
        if type(display_name) is not str or not (1 <= len(display_name) <= 80):
            _invalid()
        if type(pattern) is not str or pattern not in CONTACT_PATTERNS:
            _invalid()
        try:
            confidence = require_finite_float(entry["confidence"], minimum=0.0, maximum=1.0, code="catalog_invalid")
        except MudraValidationError:
            _invalid()
        limitations = entry["limitations"]
        if type(limitations) is not list or not (1 <= len(limitations) <= 8):
            _invalid()
        if any(type(item) is not str or not (1 <= len(item) <= 240) for item in limitations):
            _invalid()
        provenance = entry["provenance"]
        if type(provenance) is not dict or set(provenance) != PROVENANCE_FIELDS:
            _invalid()
        if type(provenance["status"]) is not str or provenance["status"] not in PROVENANCE_STATUSES:
            _invalid()
        if type(provenance["reference"]) is not str or not (1 <= len(provenance["reference"]) <= 240):
            _invalid()
        if type(provenance["content_license"]) is not str or not (1 <= len(provenance["content_license"]) <= 80):
            _invalid()
        seen.add(gesture_id)
        normalized.append(
            {
                "gesture_id": gesture_id,
                "display_name": display_name,
                "contact_pattern": pattern,
                "confidence": confidence,
                "limitations": list(limitations),
                "provenance": dict(provenance),
            }
        )
    if seen != CATALOG_IDS:
        _invalid()
    return {"catalog_version": CATALOG_VERSION, "entries": normalized}


def load_catalog(path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    try:
        if path is None:
            resource = files("mudra_interact_core").joinpath("catalog/mudra_catalog.json")
            data = resource.read_bytes()
        else:
            candidate = Path(path)
            if candidate.is_symlink() or not candidate.is_file():
                _invalid()
            data = candidate.read_bytes()
        payload = parse_json_bytes(data, limit=65_536)
        validated = validate_catalog_payload(payload)
    except MudraValidationError:
        raise
    except (OSError, UnicodeError):
        _invalid()
    return {entry["gesture_id"]: copy.deepcopy(entry) for entry in validated["entries"]}


def lookup(gesture_id: str) -> dict[str, Any] | None:
    if type(gesture_id) is not str or len(gesture_id) > MAX_STRING_SCALARS:
        _invalid()
    entry = load_catalog().get(gesture_id)
    return copy.deepcopy(entry) if entry is not None else None


def validate_label_pack(payload: Any) -> dict[str, Any]:
    """Validate a review record without implying that a reviewer approved it."""

    if type(payload) is not dict or set(payload) != {"pack_version", "entries"} or type(payload["entries"]) is not list:
        _invalid()
    for entry in payload["entries"]:
        if type(entry) is not dict or set(entry) != {
            "gesture_id", "label", "reviewer", "evidence_reference", "rights", "language_scope", "prohibited_claims", "withdrawal"
        }:
            _invalid()
        if any(type(entry[key]) is not str or not entry[key] for key in entry):
            _invalid()
    return copy.deepcopy(payload)


__all__ = ["CATALOG_IDS", "load_catalog", "lookup", "validate_catalog_payload", "validate_label_pack"]
