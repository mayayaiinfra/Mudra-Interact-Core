"""Local command line entrypoint for the open Mudra Interact Core."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .catalog import lookup
from .protocol import InteractionParty, Landmark, MudraEvent, PrivacyMode
from .recognition import LandmarkRuleRecognizer, RecognitionStabilizer


def _read_input(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local landmark-only Mudra Interact recognition.")
    parser.add_argument("--input", required=True, help="JSON file containing a 21-item landmarks array.")
    parser.add_argument("--stabilize", action="store_true", help="Promote after three matching frames in one process.")
    args = parser.parse_args()
    payload = _read_input(args.input)
    landmarks = [Landmark.from_mapping(item) for item in payload.get("landmarks", [])]
    recognition = LandmarkRuleRecognizer().recognize(landmarks)
    if args.stabilize:
        stabilizer = RecognitionStabilizer()
        recognition = stabilizer.update(recognition)
    event = MudraEvent(
        recognition=recognition,
        sender=InteractionParty(str(payload.get("sender") or "human")),
        recipient=InteractionParty(str(payload.get("recipient") or "agent")),
        privacy_mode=PrivacyMode.EVENT_ONLY,
        consent_confirmed=bool(payload.get("consent_confirmed", True)),
    )
    result = event.payload()
    result["catalog_entry"] = lookup(recognition.gesture_id)
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
