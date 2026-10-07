from __future__ import annotations

import json

import pytest

from mudra_interact_core import MudraValidationError, RecognitionSession, parse_event
from mudra_interact_core.protocol import InteractionParty

from test_session import STREAM_ID, frame, stable_session


@pytest.mark.acceptance("E43")
@pytest.mark.parametrize(
    "sender,recipient,direction",
    [
        (InteractionParty.HUMAN, InteractionParty.HUMAN, "human_to_human"),
        (InteractionParty.HUMAN, InteractionParty.AGENT, "human_to_agent"),
        (InteractionParty.AGENT, InteractionParty.HUMAN, "agent_to_human"),
        (InteractionParty.AGENT, InteractionParty.AGENT, "agent_to_agent"),
    ],
)
def test_four_party_directions_and_stable_serialization(sender, recipient, direction: str) -> None:
    session = stable_session()
    session.confirm(True, True, 100)
    event = session.emit_event(sender=sender, recipient=recipient, now_ms=100, event_id="123e4567-e89b-42d3-a456-426614174001", occurred_at="2026-10-07T01:00:00.000000Z")
    assert event.direction == direction
    first = event.to_bytes()
    second = event.to_bytes()
    assert first == second
    assert parse_event(first).payload() == event.payload()
    assert len(first) <= 4096


@pytest.mark.acceptance("E44")
def test_event_import_is_validation_only_and_cannot_grant_a_session() -> None:
    source = stable_session()
    source.confirm(True, True, 100)
    event = source.emit_event(now_ms=100)
    imported = parse_event(event.to_bytes())
    assert imported.payload() == event.payload()

    receiver = RecognitionSession(STREAM_ID)
    with pytest.raises(MudraValidationError, match="consent_required"):
        receiver.emit_event(now_ms=100)


@pytest.mark.acceptance("E43")
def test_event_payload_is_detached_and_closed() -> None:
    session = stable_session()
    session.confirm(True, True, 100)
    event = session.emit_event(now_ms=100)
    payload = event.payload()
    payload["recognition"]["gesture_id"] = "unknown"
    payload["recognition"]["observation_codes"].append("tamper")
    fresh = event.payload()
    assert fresh["recognition"]["gesture_id"] != "unknown"
    assert "tamper" not in fresh["recognition"]["observation_codes"]
    assert set(fresh) == {
        "schema_version", "event_id", "occurred_at", "sender", "recipient", "direction",
        "privacy_mode", "consent_confirmed", "participant_confirmed", "conversation_id",
        "project_id", "recognition", "raw_media_included", "raw_landmarks_included",
    }

