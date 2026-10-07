from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest

from mudra_interact_core import Frame, Landmark, MudraEvent, Recognition, RecognitionSession, parse_event
from mudra_interact_core.protocol import InteractionParty, PrivacyMode, RecognitionState
from mudra_interact_core.cli import main
from mudra_interact_core.errors import MudraValidationError


ROOT = Path(__file__).resolve().parents[1]
STREAM_ID = "123e4567-e89b-42d3-a456-426614174000"
EVENT_ID = "123e4567-e89b-42d3-a456-426614174001"


def _event() -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "event_id": EVENT_ID,
        "occurred_at": "2026-10-07T00:00:00.000000Z",
        "sender": "human",
        "recipient": "agent",
        "direction": "human_to_agent",
        "privacy_mode": "event_only",
        "consent_confirmed": True,
        "participant_confirmed": True,
        "conversation_id": None,
        "project_id": None,
        "recognition": {
            "gesture_id": "contact_thumb_index",
            "confidence": 0.72,
            "state": "stable",
            "method": "contact_rules_v2",
            "catalog_version": "2.0.0",
            "observation_codes": ["thumb_index_contact"],
            "uncertainty_codes": ["posture_unverified"],
        },
        "raw_media_included": False,
        "raw_landmarks_included": False,
    }


def _frame(frame_id: int, monotonic_ms: int) -> Frame:
    points = [Landmark(0.0, 0.0, 0.0) for _ in range(21)]
    points[4] = Landmark(0.0, 0.0, 0.0)
    points[8] = Landmark(0.2, 0.0, 0.0)
    points[9] = Landmark(0.0, 1.0, 0.0)
    points[12] = Landmark(1.0, 0.0, 0.0)
    points[16] = Landmark(1.0, 0.0, 0.0)
    return Frame("2.0.0", STREAM_ID, frame_id, monotonic_ms, "cartesian_relative_v1", tuple(points))


@pytest.mark.acceptance("E62")
@pytest.mark.parametrize("location", ["event", "recognition"])
def test_event_boundary_rejects_raw_data_and_prose_at_each_closed_nesting_point(location: str) -> None:
    value = _event()
    if location == "event":
        value["metadata"] = {"sentinel": "PRIVATE_RAW_DATA"}
    else:
        value["recognition"] = {**value["recognition"], "landmarks": [{"x": 0}]}
    with pytest.raises(MudraValidationError) as caught:
        parse_event(value)
    assert caught.value.code == "invalid_shape"
    assert "PRIVATE_RAW_DATA" not in str(caught.value)
    if location == "event":
        recognition = Recognition(
            "contact_thumb_index",
            0.72,
            RecognitionState.STABLE,
            method="contact_rules_v2",
            observations=("thumb_index_contact",),
            uncertainties=("posture_unverified",),
            catalog_version="2.0.0",
        )
        with pytest.raises(MudraValidationError, match="invalid_shape"):
            MudraEvent(
                recognition=recognition,
                sender=InteractionParty.HUMAN,
                recipient=InteractionParty.AGENT,
                privacy_mode=PrivacyMode.EVENT_ONLY,
                event_id=EVENT_ID,
                occurred_at="2026-10-07T00:00:00.000000Z",
                consent_confirmed=True,
                participant_confirmed=True,
                metadata={"sentinel": "PRIVATE_RAW_DATA"},
            )


@pytest.mark.acceptance("E63")
def test_sentinel_never_crosses_error_or_cli_report_channels(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    sentinel = "PRIVATE_SENTINEL_9f5d"
    bad = tmp_path / f"{sentinel}.json"
    bad.write_text(json.dumps({"schema_version": "1.0", "{sentinel}": sentinel}), encoding="utf-8")
    code = main(["recognize", "--input", str(bad)])
    captured = capsys.readouterr()
    assert code == 2
    assert sentinel not in captured.out + captured.err
    with pytest.raises(MudraValidationError) as caught:
        parse_event({**_event(), "metadata": sentinel})
    assert str(caught.value) == "invalid_shape"
    privacy_doc = (ROOT / "docs" / "PRIVACY.md").read_text(encoding="utf-8")
    assert "zeroization" in privacy_doc and "host retention" in privacy_doc


@pytest.mark.acceptance("E64")
def test_runtime_core_has_no_network_subprocess_or_implicit_egress(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("unexpected runtime egress")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    session = RecognitionSession(STREAM_ID)
    session.observe(_frame(1, 0))
    session.observe(_frame(2, 50))
    session.observe(_frame(3, 100))
    session.confirm(True, True, 100)
    event = session.emit_event(now_ms=100)
    assert event.to_bytes()


@pytest.mark.acceptance("E70")
def test_long_session_keeps_bounded_recognition_only_state_and_clears_grants() -> None:
    session = RecognitionSession(STREAM_ID)
    for frame_id in range(1, 10_001):
        session.observe(_frame(frame_id, frame_id * 50))
    assert session.buffered_frames == session.config.required_frames
    assert session.streak_count == 10_000
    assert all(not isinstance(value, Frame) for value in session.__dict__.values())
    session.confirm(True, True, 10_000 * 50)
    assert session.__dict__["_confirmation"] is not None
    session.revoke()
    assert session.__dict__["_confirmation"] is None
    session.stop()
    assert session.buffered_frames == 0
    assert session.__dict__["_confirmation"] is None


@pytest.mark.acceptance("E72")
def test_threat_model_maps_public_channels_to_negative_cases_without_universal_claim() -> None:
    text = (ROOT / "docs" / "THREAT_MODEL.md").read_text(encoding="utf-8")
    for case_id in ("E62", "E63", "E64", "E65", "E66", "E67", "E68", "E69", "E70", "E71"):
        assert case_id in text
    assert "universal privacy" in text
    assert "security certification" in text
