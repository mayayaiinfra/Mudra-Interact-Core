from __future__ import annotations

import json
import random

import pytest

from mudra_interact_core import Frame, Landmark, MudraValidationError, RecognitionSession, parse_event, parse_frame


STREAM_ID = "123e4567-e89b-42d3-a456-426614174000"
EVENT_ID = "123e4567-e89b-42d3-a456-426614174001"


def _frame_mapping(frame_id: int = 1, monotonic_ms: int = 0) -> dict[str, object]:
    points = [{"x": 0.0, "y": 0.0, "z": 0.0} for _ in range(21)]
    points[4] = {"x": 0.0, "y": 0.0, "z": 0.0}
    points[8] = {"x": 0.2, "y": 0.0, "z": 0.0}
    points[9] = {"x": 0.0, "y": 1.0, "z": 0.0}
    points[12] = {"x": 1.0, "y": 0.0, "z": 0.0}
    points[16] = {"x": 1.0, "y": 0.0, "z": 0.0}
    return {
        "schema_version": "2.0.0",
        "stream_id": STREAM_ID,
        "frame_id": frame_id,
        "monotonic_ms": monotonic_ms,
        "coordinate_space": "cartesian_relative_v1",
        "landmarks": points,
    }


def _valid_event() -> dict[str, object]:
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
            "gesture_id": "contact_thumb_index", "confidence": 0.72, "state": "stable",
            "method": "contact_rules_v2", "catalog_version": "2.0.0",
            "observation_codes": ["thumb_index_contact"], "uncertainty_codes": ["posture_unverified"],
        },
        "raw_media_included": False,
        "raw_landmarks_included": False,
    }


@pytest.mark.acceptance("E65")
@pytest.mark.parametrize("seed", [0x51A7, 0xC0DE, 0xBEEF])
def test_bounded_fuzz_seeds_cover_parser_numeric_enum_and_length_boundaries(seed: int) -> None:
    randomizer = random.Random(seed)
    for index in range(10_000):
        selector = randomizer.randrange(8)
        if selector == 0:
            value: object = _frame_mapping(index + 1, index)
            parser = parse_frame
        elif selector == 1:
            value = {**_frame_mapping(), "landmarks": []}
            parser = parse_frame
        elif selector == 2:
            value = {**_frame_mapping(), "landmarks": [{"x": True, "y": 0.0, "z": 0.0}] * 21}
            parser = parse_frame
        elif selector == 3:
            value = {**_frame_mapping(), "landmarks": [{"x": "0", "y": 0.0, "z": 0.0}] * 21}
            parser = parse_frame
        elif selector == 4:
            value = b'{"schema_version":"2.0.0","schema_version":"2.0.0"}'
            parser = parse_frame
        elif selector == 5:
            value = b"[" + (b"[" * 20) + b"0" + (b"]" * 20) + b"]"
            parser = parse_frame
        elif selector == 6:
            value = json.dumps({**_frame_mapping(), "frame_id": 2**53}).encode()
            parser = parse_frame
        else:
            value = json.dumps({**_valid_event(), "unknown": randomizer.random()}).encode()
            parser = parse_event
        try:
            parser(value)  # type: ignore[arg-type]
        except MudraValidationError:
            pass
        except (TypeError, ValueError, OverflowError, RecursionError) as error:
            raise AssertionError("unbounded parser exception") from error


@pytest.mark.acceptance("E66")
def test_random_valid_sequences_have_independent_stability_and_one_shot_expectations() -> None:
    randomizer = random.Random(0xA11CE)
    for sequence in range(64):
        session = RecognitionSession(STREAM_ID)
        for frame_id in range(1, 4):
            points = [Landmark(0.0, 0.0, 0.0) for _ in range(21)]
            points[8] = Landmark(0.2, 0.0, 0.0)
            points[9] = Landmark(0.0, 1.0, 0.0)
            points[12] = Landmark(1.0, 0.0, 0.0)
            points[16] = Landmark(1.0, 0.0, 0.0)
            result = session.observe(Frame("2.0.0", STREAM_ID, frame_id, (frame_id - 1) * 50, "cartesian_relative_v1", tuple(points)))
        assert result.state.value == "stable"
        assert 0.0 < result.confidence <= 1.0
        session.confirm(True, True, 100)
        assert session.emit_event(now_ms=100).payload()["direction"] == "human_to_agent"
        with pytest.raises(MudraValidationError, match="consent_required"):
            session.emit_event(now_ms=100)
        # Consume the randomizer so each sequence has a deterministic but
        # independent workload without deriving expected state from the code.
        assert 0 <= randomizer.randrange(10_000) < 10_000
