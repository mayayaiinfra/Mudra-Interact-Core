from __future__ import annotations

import math
from copy import deepcopy

import pytest

from mudra_interact_core import (
    Frame,
    InteractionConfig,
    Landmark,
    MudraValidationError,
    parse_event,
    parse_frame,
)
from mudra_interact_core.protocol import Recognition, RecognitionState


STREAM_ID = "123e4567-e89b-42d3-a456-426614174000"
EVENT_ID = "123e4567-e89b-42d3-a456-426614174001"


def points(*, palm_scale: float = 1.0) -> list[dict[str, float]]:
    result = [{"x": 0.0, "y": 0.0, "z": 0.0} for _ in range(21)]
    result[9] = {"x": 0.0, "y": palm_scale, "z": 0.0}
    return result


def frame_mapping(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "2.0.0",
        "stream_id": STREAM_ID,
        "frame_id": 1,
        "monotonic_ms": 100,
        "coordinate_space": "cartesian_relative_v1",
        "landmarks": points(),
    }
    value.update(overrides)
    return value


def expect_code(code: str, operation) -> None:
    with pytest.raises(MudraValidationError) as caught:
        operation()
    assert caught.value.code == code
    assert "sentinel" not in str(caught.value)


@pytest.mark.acceptance("E10")
@pytest.mark.parametrize("count", [0, 20, 22])
def test_point_count_is_exactly_twenty_one(count: int) -> None:
    values = points()
    if count > len(values):
        values = values + [{"x": 0.0, "y": 0.0, "z": 0.0}] * (count - len(values))
    expect_code("invalid_shape", lambda: parse_frame({**frame_mapping(), "landmarks": values[:count]}))


@pytest.mark.acceptance("E10")
def test_twenty_one_points_are_accepted_and_arbitrary_iterables_are_not_consumed() -> None:
    frame = Frame(
        "2.0.0",
        STREAM_ID,
        1,
        100,
        "cartesian_relative_v1",
        tuple(Landmark(**point) for point in points()),
    )
    assert len(frame.landmarks) == 21

    consumed = False

    class HostileIterable:
        def __iter__(self):
            nonlocal consumed
            consumed = True
            yield from points()

    expect_code("invalid_shape", lambda: Frame("2.0.0", STREAM_ID, 1, 100, "cartesian_relative_v1", HostileIterable()))
    assert consumed is False


@pytest.mark.acceptance("E11")
@pytest.mark.parametrize(
    "bad_point",
    [
        {"x": 0.0, "y": 0.0},
        {"x": 0.0, "y": 0.0, "z": 0.0, "extra": 1},
        {"x": None, "y": 0.0, "z": 0.0},
        {"x": True, "y": 0.0, "z": 0.0},
        {"x": "0", "y": 0.0, "z": 0.0},
    ],
)
def test_point_fields_are_closed_and_uncoerced(bad_point: dict[str, object]) -> None:
    value = frame_mapping(landmarks=[bad_point] + points()[1:])
    expect_code("invalid_shape" if bad_point.get("x") not in (16, -16) else "invalid_geometry", lambda: parse_frame(value))


@pytest.mark.acceptance("E11")
def test_constructor_rejects_custom_numeric_conversion() -> None:
    class Numeric:
        def __float__(self):
            raise AssertionError("conversion hook must not run")

    expect_code("invalid_shape", lambda: Landmark(Numeric(), 0.0, 0.0))


@pytest.mark.acceptance("E12")
@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 17.0, -17.0, 10**1000])
def test_coordinates_are_finite_and_bounded(value: object) -> None:
    expected = "invalid_geometry" if type(value) is int or (isinstance(value, float) and math.isfinite(value)) else "invalid_number"
    expect_code(expected, lambda: Landmark(value, 0.0, 0.0))
    assert Landmark(16, -16, -0.0).x == 16.0
    assert math.copysign(1.0, Landmark(0.0, 0.0, -0.0).z) == -1.0


@pytest.mark.acceptance("E13")
@pytest.mark.parametrize("scale", [0.0, 0.000099999])
def test_palm_scale_has_a_minimum(scale: float) -> None:
    expect_code("invalid_geometry", lambda: parse_frame(frame_mapping(landmarks=points(palm_scale=scale))))


@pytest.mark.acceptance("E13")
def test_minimum_palm_scale_equality_is_allowed() -> None:
    frame = parse_frame(frame_mapping(landmarks=points(palm_scale=0.0001)))
    assert frame.palm_scale >= 0.0001


@pytest.mark.acceptance("E14")
@pytest.mark.parametrize(
    "field,value",
    [
        ("contact_threshold", True),
        ("contact_threshold", 0.049),
        ("contact_threshold", 0.751),
        ("required_frames", 1),
        ("required_frames", 13),
        ("required_frames", 3.0),
        ("minimum_confidence", math.nan),
        ("minimum_hold_ms", -1),
        ("maximum_gap_ms", 1001),
    ],
)
def test_configuration_is_rejected_without_clamping(field: str, value: object) -> None:
    kwargs = {field: value}
    expect_code("invalid_configuration", lambda: InteractionConfig(**kwargs))


@pytest.mark.acceptance("E14")
def test_configuration_boundaries_are_accepted() -> None:
    config = InteractionConfig(
        contact_threshold=0.05,
        required_frames=12,
        minimum_confidence=1.0,
        minimum_hold_ms=2000,
        maximum_gap_ms=1000,
    )
    assert config.contact_threshold == 0.05
    assert config.required_frames == 12


@pytest.mark.acceptance("E17")
def test_frame_copies_inputs_and_payloads() -> None:
    source = points()
    frame = parse_frame(frame_mapping(landmarks=source))
    source[0]["x"] = 16
    assert frame.landmarks[0].x == 0.0
    payload = frame.payload()
    payload["landmarks"][0]["x"] = 15
    assert frame.landmarks[0].x == 0.0


def _valid_event() -> dict[str, object]:
    return {
        "schema_version": "2.0.0",
        "event_id": EVENT_ID,
        "occurred_at": "2026-10-07T01:00:00.000000Z",
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


@pytest.mark.acceptance("E18")
@pytest.mark.parametrize(
    "mutator,code",
    [
        (lambda value: value.update(schema_version="9.0.0"), "unsupported_version"),
        (lambda value: value.update(extra="nope"), "invalid_shape"),
        (lambda value: value.update(direction="agent_to_human"), "invalid_state"),
        (lambda value: value["recognition"].update(confidence=0.0), "invalid_state"),
        (lambda value: value.update(event_id="not-a-uuid"), "invalid_shape"),
    ],
)
def test_event_parser_rejects_versions_fields_ids_and_incompatible_state(mutator, code: str) -> None:
    value = _valid_event()
    mutator(value)
    expect_code(code, lambda: parse_event(value))


@pytest.mark.acceptance("E19")
def test_public_errors_are_fixed_codes_without_input_or_paths() -> None:
    value = frame_mapping(landmarks=[{"x": "sentinel", "y": 0.0, "z": 0.0}] + points()[1:])
    with pytest.raises(MudraValidationError) as caught:
        parse_frame(value)
    assert caught.value.code == "invalid_shape"
    assert str(caught.value) == "invalid_shape"
    assert "sentinel" not in repr(caught.value)

