"""Fail a Mudra Interact release when an included component lacks an allowed licence."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
POLICY = ROOT / "licenses" / "approved_components.json"


def validate() -> list[str]:
    payload = json.loads(POLICY.read_text(encoding="utf-8"))
    allowed = set(payload.get("approved_spdx_licenses") or [])
    errors: list[str] = []
    for component in payload.get("components") or []:
        if component.get("status") != "included":
            continue
        if component.get("license") not in allowed:
            errors.append(f"{component.get('name')}: licence is not on the approved allowlist")
        if component.get("notice_required") and not (ROOT / "NOTICE").exists():
            errors.append(f"{component.get('name')}: NOTICE is required")
    return errors


if __name__ == "__main__":
    failures = validate()
    if failures:
        raise SystemExit("\n".join(failures))
    print("Mudra Interact licence allowlist: OK")
