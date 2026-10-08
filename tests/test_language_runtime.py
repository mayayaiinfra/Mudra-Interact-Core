from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from mudra_interact_core.language import LanguageValidationError, Message, check_freshness, parse_message


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "language" / "v1"
DIRECTIONS = ("human_to_human", "human_to_agent", "agent_to_human", "agent_to_agent")


def _valid_messages() -> list[tuple[str, str, dict]]:
    output = []
    for direction in DIRECTIONS:
        bundle = json.loads((FIXTURE_ROOT / f"{direction}.json").read_text(encoding="utf-8"))
        output.extend((direction, act, message) for act, message in bundle["valid"].items())
    return output


def _base_message() -> dict:
    return copy.deepcopy(next(message for _direction, act, message in _valid_messages() if act == "request"))


def _proposal(message: dict, steps: list[dict] | None = None) -> dict:
    result = copy.deepcopy(message)
    result["message_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    result["reply_to"] = message["message_id"]
    result["act"] = "proposal"
    result["intent"]["payload"] = {
        "summary": "A synthetic plan",
        "steps": steps if steps is not None else [{"step_id": 1, "description": "Review the brief"}],
    }
    return result


def _reply(message: dict, act: str, payload: dict) -> dict:
    result = copy.deepcopy(message)
    result["message_id"] = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    result["reply_to"] = message["message_id"]
    result["act"] = act
    result["intent"]["payload"] = payload
    return result


def _assert_error(code: str, value: object) -> None:
    with pytest.raises(LanguageValidationError) as captured:
        parse_message(value)  # type: ignore[arg-type]
    assert captured.value.code == code
    assert str(captured.value) == code


@pytest.mark.acceptance("L10")
@pytest.mark.parametrize(
    ("direction", "act", "wire"),
    _valid_messages(),
    ids=[f"{direction}-{act}" for direction, act, _wire in _valid_messages()],
)
def test_all_static_valid_messages_match_constructor_and_parser(direction: str, act: str, wire: dict) -> None:
    parsed = parse_message(wire)
    constructed = Message(**copy.deepcopy(wire))
    assert parsed.payload() == wire
    assert constructed.payload() == wire
    assert parse_message(parsed.to_bytes()).payload() == wire
    assert parsed.to_bytes() == constructed.to_bytes()
    assert parsed.act == act
    assert f"{parsed.sender.kind}_to_{parsed.recipient.kind}" == direction


@pytest.mark.acceptance("L10")
def test_message_payloads_are_detached_and_internal_values_are_immutable() -> None:
    original = _base_message()
    message = parse_message(original)
    original_bytes = message.to_bytes()
    original["intent"]["payload"]["brief"] = "mutated input"
    detached = message.payload()
    detached["intent"]["payload"]["brief"] = "mutated outside"
    detached["sender"]["kind"] = "agent"
    nested = message.intent.payload
    nested["brief"] = "mutated nested copy"
    assert message.intent.payload["brief"] == "Plan a synthetic idea."
    assert message.sender.kind == "human"
    assert message.to_bytes() == original_bytes
    with pytest.raises((AttributeError, TypeError)):
        message.act = "result"  # type: ignore[misc]
    with pytest.raises((AttributeError, TypeError)):
        message.sender.kind = "agent"  # type: ignore[misc]


@pytest.mark.acceptance("L10")
def test_constructor_rejects_open_or_non_builtin_inputs_with_safe_errors() -> None:
    message = _base_message()
    with pytest.raises(LanguageValidationError, match="invalid_shape"):
        Message(**{**message, "unexpected": "sensitive text"})
    with pytest.raises(LanguageValidationError, match="invalid_shape"):
        Message(message)  # type: ignore[call-arg]

    class DictSubclass(dict):
        pass

    _assert_error("invalid_shape", DictSubclass(message))
    _assert_error("invalid_shape", {**message, "sender": object()})


@pytest.mark.acceptance("L11")
def test_wire_byte_limit_and_precedence_are_exact() -> None:
    message = _base_message()
    message["extra"] = ""
    baseline = len(json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    message["extra"] = "x" * (65_536 - baseline)
    at_limit = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(at_limit) == 65_536
    _assert_error("invalid_shape", at_limit)

    message["extra"] += "x"
    over_limit = json.dumps(message, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    assert len(over_limit) == 65_537
    _assert_error("input_too_large", over_limit)
    with pytest.raises(LanguageValidationError, match="input_too_large"):
        Message(**message)


@pytest.mark.acceptance("L11")
def test_depth_boundary_duplicate_keys_bom_utf8_and_trailing_documents() -> None:
    message = _base_message()
    nested: object = "leaf"
    for _ in range(15):
        nested = {"nested": nested}
    message["extra"] = nested
    _assert_error("invalid_shape", json.dumps(message, separators=(",", ":")).encode("utf-8"))
    message["extra"] = {"nested": nested}
    _assert_error("invalid_json", json.dumps(message, separators=(",", ":")).encode("utf-8"))

    for encoded in (b'{"act":"request","act":"proposal"}', b"\xef\xbb\xbf{}", b"\xff", b"{} {}"):
        _assert_error("invalid_json", encoded)


@pytest.mark.acceptance("L11")
def test_text_bounds_unicode_controls_and_multiline_allowlist() -> None:
    message = _base_message()
    message["intent"]["payload"]["brief"] = "x" * 4096
    assert len(parse_message(message).intent.payload["brief"]) == 4096
    message["intent"]["payload"]["brief"] += "x"
    _assert_error("invalid_shape", message)

    message = _base_message()
    message["intent"]["payload"]["brief"] = "First line\nSecond line"
    assert parse_message(message).intent.payload["brief"] == "First line\nSecond line"
    for invalid in ("line\tbreak", "line\rbreak", "line\x7fbreak"):
        message = _base_message()
        message["intent"]["payload"]["brief"] = invalid
        _assert_error("invalid_shape", message)

    message = _base_message()
    message["intent"]["payload"]["brief"] = "😀" * 4096
    assert len(parse_message(message).intent.payload["brief"]) == 4096
    message["intent"]["payload"]["brief"] += "😀"
    _assert_error("invalid_shape", message)

    message = _base_message()
    message["intent"]["payload"]["brief"] = "\ud800"
    _assert_error("invalid_json", message)
    _assert_error("invalid_json", b'{"surrogate":"\\ud800"}')


@pytest.mark.acceptance("L11")
def test_all_tighter_text_field_boundaries_are_enforced() -> None:
    base = _base_message()
    cases = [
        ("proposal", {"summary": "x" * 1024, "steps": [{"step_id": 1, "description": "Step"}]}, "summary", 1024),
        ("proposal", {"summary": "Plan", "steps": [{"step_id": 1, "description": "x" * 1024}]}, "step", 1024),
        ("clarification", {"text": "x" * 1024, "about": "brief"}, "text", 1024),
        ("status", {"state": "planning", "text": "x" * 1024}, "text", 1024),
        ("result", {"summary": "x" * 4096}, "summary", 4096),
    ]
    for act, payload, location, maximum in cases:
        assert parse_message(_reply(base, act, payload)).act == act
        invalid = copy.deepcopy(payload)
        if location == "step":
            invalid["steps"][0]["description"] += "x"
        elif "summary" in invalid:
            invalid["summary"] += "x"
        else:
            invalid["text"] += "x"
        if location == "step":
            assert len(invalid["steps"][0]["description"]) == maximum + 1
        else:
            assert len(invalid.get("summary", invalid.get("text", ""))) == maximum + 1
        _assert_error("invalid_shape", _reply(base, act, invalid))


@pytest.mark.acceptance("L11")
def test_interpretation_score_numeric_boundaries_and_boolean_review_flag() -> None:
    for score in (0, 1, 0.0, 1.0):
        message = _base_message()
        message["provenance"]["interpretation_score"] = score
        assert parse_message(message).provenance.interpretation_score == score
    for score in (-0.01, 1.01):
        message = _base_message()
        message["provenance"]["interpretation_score"] = score
        _assert_error("invalid_number", message)
    message = _base_message()
    message["provenance"]["human_reviewed"] = 1
    _assert_error("invalid_shape", message)


@pytest.mark.acceptance("L11")
def test_json_numbers_booleans_and_proposal_step_count_boundaries() -> None:
    message = _base_message()
    message["provenance"]["interpretation_score"] = True
    _assert_error("invalid_shape", message)
    message = _base_message()
    message["provenance"]["interpretation_score"] = float("inf")
    _assert_error("invalid_number", message)
    message = _base_message()
    message["provenance"]["interpretation_score"] = 10**1000
    _assert_error("invalid_number", message)

    overflow = json.dumps(_base_message(), separators=(",", ":")).replace(
        '"interpretation_score":null', '"interpretation_score":1e10000',
    ).encode("utf-8")
    _assert_error("invalid_json", overflow)

    assert parse_message(_proposal(_base_message())).act == "proposal"
    sixteen = [{"step_id": index, "description": f"Step {index}"} for index in range(1, 17)]
    assert len(parse_message(_proposal(_base_message(), sixteen)).intent.payload["steps"]) == 16
    _assert_error("invalid_shape", _proposal(_base_message(), []))
    _assert_error("invalid_shape", _proposal(_base_message(), sixteen + [{"step_id": 17, "description": "Step 17"}]))
    _assert_error("invalid_shape", _proposal(_base_message(), [{"step_id": True, "description": "Bad"}]))
    _assert_error("invalid_sequence", _proposal(_base_message(), [{"step_id": 2, "description": "Gap"}]))


@pytest.mark.acceptance("L12")
@pytest.mark.parametrize(
    ("field", "value", "code"),
    [("protocol_version", "2.0.0", "unsupported_version"), ("act", "publish", "unsupported_intent")],
)
def test_unknown_protocol_and_act_fail_closed(field: str, value: str, code: str) -> None:
    message = _base_message()
    message[field] = value
    _assert_error(code, message)


@pytest.mark.acceptance("L12")
@pytest.mark.parametrize(("field", "value"), [("name", "org.example.unknown"), ("version", "2.0.0")])
def test_unknown_intent_name_and_version_fail_closed(field: str, value: str) -> None:
    message = _base_message()
    message["intent"][field] = value
    _assert_error("unsupported_intent", message)


@pytest.mark.acceptance("L12")
def test_participant_identity_and_provenance_mode_rules() -> None:
    message = _base_message()
    message["recipient"]["participant_id"] = message["sender"]["participant_id"]
    _assert_error("invalid_shape", message)
    message = _base_message()
    message["provenance"]["mode"] = "agent"
    _assert_error("invalid_shape", message)
    message = _base_message()
    message["sender"]["kind"] = "agent"
    message["provenance"]["mode"] = "text"
    _assert_error("invalid_shape", message)
    message = _base_message()
    message["provenance"]["adapter_version"] = "01.0.0"
    _assert_error("invalid_shape", message)

    message = _base_message()
    message["message_id"] = message["message_id"].upper()
    _assert_error("invalid_shape", message)

    message = _base_message()
    message["message_id"] = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    message["reply_to"] = message["message_id"]
    _assert_error("invalid_sequence", message)


@pytest.mark.acceptance("L12")
def test_act_specific_enums_and_closed_payload_shapes_reject() -> None:
    base = _base_message()
    invalid_cases = [
        _reply(base, "request", {"brief": "Work", "medium": "document"}),
        _reply(base, "clarification", {"text": "Explain", "about": "result"}),
        _reply(base, "decline", {"reason": "later"}),
        _reply(base, "status", {"state": "finished", "text": "Done"}),
        _reply(base, "error", {"code": "secret_exception"}),
        _reply(base, "accept", {"approved": True}),
        _reply(base, "result", {"summary": "Done", "url": "https://example.invalid"}),
    ]
    for message in invalid_cases:
        _assert_error("invalid_shape", message)


@pytest.mark.acceptance("L12")
def test_message_time_interval_has_strict_positive_ten_minute_bound() -> None:
    message = _base_message()
    message["expires_at"] = message["created_at"]
    _assert_error("invalid_sequence", message)
    message = _base_message()
    message["expires_at"] = "2026-10-08T12:10:00.000000Z"
    assert parse_message(message).expires_at == message["expires_at"]
    message["expires_at"] = "2026-10-08T12:10:00.000001Z"
    _assert_error("invalid_sequence", message)
    message = _base_message()
    message["created_at"] = "0001-01-01T00:00:00.000000Z"
    message["expires_at"] = "0001-01-01T00:00:01.000000Z"
    assert parse_message(message).created_at == message["created_at"]


@pytest.mark.acceptance("L12")
def test_all_static_invalid_fixtures_reject_through_runtime_parser() -> None:
    for direction in DIRECTIONS:
        bundle = json.loads((FIXTURE_ROOT / f"{direction}.json").read_text(encoding="utf-8"))
        for message in bundle["invalid"].values():
            with pytest.raises(LanguageValidationError):
                parse_message(message)
    negative = json.loads((FIXTURE_ROOT / "negative_cases.json").read_text(encoding="utf-8"))
    for message in negative.values():
        with pytest.raises(LanguageValidationError):
            parse_message(message)


@pytest.mark.acceptance("L13")
def test_freshness_exact_expiry_and_future_skew_boundaries() -> None:
    message = parse_message(_base_message())
    assert check_freshness(message, "2026-10-08T12:05:00.000000Z") is True
    with pytest.raises(LanguageValidationError, match="expired_message"):
        check_freshness(message, "2026-10-08T12:05:00.000001Z")

    future = _base_message()
    future["created_at"] = "2026-10-08T12:00:30.000000Z"
    future["expires_at"] = "2026-10-08T12:05:30.000000Z"
    assert check_freshness(parse_message(future), "2026-10-08T12:00:00.000000Z") is True
    future["created_at"] = "2026-10-08T12:00:31.000000Z"
    future["expires_at"] = "2026-10-08T12:05:31.000000Z"
    with pytest.raises(LanguageValidationError, match="expired_message"):
        check_freshness(parse_message(future), "2026-10-08T12:00:00.000000Z")


@pytest.mark.acceptance("L13")
def test_import_has_no_network_process_or_authority_surface() -> None:
    code = r'''
import os, socket, subprocess, sys, urllib.request
sys.path.insert(0, sys.argv[1])
def forbidden(*args, **kwargs):
    raise AssertionError("unexpected side effect")
socket.socket = forbidden
socket.create_connection = forbidden
subprocess.Popen = forbidden
subprocess.run = forbidden
os.system = forbidden
urllib.request.urlopen = forbidden
import mudra_interact_core.language as language
assert set(language.__all__) == {"LanguageValidationError", "Message", "check_freshness", "parse_message"}
assert not any(hasattr(language, name) for name in ("authorize", "execute", "publish", "generate"))
'''
    completed = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / "src")],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": "", "PYTHONNOUSERSITE": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
