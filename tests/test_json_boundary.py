from __future__ import annotations

import json

import pytest

from mudra_interact_core import MudraValidationError, parse_batch, parse_frame
from mudra_interact_core.validation import MAX_BATCH_BYTES, MAX_FRAME_BYTES, MAX_JSON_DEPTH, parse_json_bytes



def frame_mapping() -> dict[str, object]:
    points = [{"x": 0.0, "y": 0.0, "z": 0.0} for _ in range(21)]
    points[9] = {"x": 0.0, "y": 1.0, "z": 0.0}
    return {
        "schema_version": "2.0.0",
        "stream_id": "123e4567-e89b-42d3-a456-426614174000",
        "frame_id": 1,
        "monotonic_ms": 100,
        "coordinate_space": "cartesian_relative_v1",
        "landmarks": points,
    }


@pytest.mark.acceptance("E15")
@pytest.mark.parametrize(
    "payload",
    [
        b'{"a":1,"a":2}',
        b'{"a":{"b":1,"b":2}}',
        b'{"schema_version":"2.0.0"} {}',
        b"\xff",
        b"\xef\xbb\xbf{}",
        b"NaN",
        b"Infinity",
        b"-Infinity",
        b'"\\ud800"',
    ],
)
def test_json_boundary_rejects_ambiguous_or_nonfinite_documents(payload: bytes) -> None:
    with pytest.raises(MudraValidationError) as caught:
        parse_json_bytes(payload, limit=MAX_BATCH_BYTES)
    assert caught.value.code == "invalid_json"


@pytest.mark.acceptance("E16")
def test_json_byte_limits_are_checked_before_decode() -> None:
    with pytest.raises(MudraValidationError, match="input_too_large"):
        parse_json_bytes(b" " * (MAX_FRAME_BYTES + 1), limit=MAX_FRAME_BYTES)
    with pytest.raises(MudraValidationError, match="input_too_large"):
        parse_json_bytes(b" " * (MAX_BATCH_BYTES + 1), limit=MAX_BATCH_BYTES)


@pytest.mark.acceptance("E16")
def test_depth_scan_is_string_aware_and_bounded() -> None:
    nested = "0"
    for _ in range(MAX_JSON_DEPTH):
        nested = "[" + nested + "]"
    assert parse_json_bytes(nested.encode(), limit=MAX_BATCH_BYTES) == json.loads(nested)
    too_deep = "[" * (MAX_JSON_DEPTH + 1) + "0" + "]" * (MAX_JSON_DEPTH + 1)
    with pytest.raises(MudraValidationError, match="invalid_json"):
        parse_json_bytes(too_deep.encode(), limit=MAX_BATCH_BYTES)
    escaped = json.dumps('{[]}')
    assert parse_json_bytes(escaped.encode(), limit=MAX_BATCH_BYTES) == "{[]}"


@pytest.mark.acceptance("E16")
def test_oversized_frame_and_batch_inputs_fail_at_the_public_parser() -> None:
    large_string = "x" * 1025
    with pytest.raises(MudraValidationError):
        parse_json_bytes(json.dumps(large_string).encode(), limit=MAX_FRAME_BYTES)
    value = {"schema_version": "2.0.0", "frames": [frame_mapping()]}
    encoded = json.dumps(value, separators=(",", ":")).encode()
    assert parse_batch(encoded).frames[0].frame_id == 1

