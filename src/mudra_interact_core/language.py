"""Bounded, dependency-free reference implementation of Mudra Language v1.

Messages describe communication and planning intent. They do not authenticate
participants, grant permission, execute work, contact a provider, or publish an
artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import math
import re
from typing import Any
from uuid import UUID

from .errors import MudraValidationError
from .validation import parse_json_bytes


PROTOCOL_VERSION = "1.0.0"
INTENT_NAME = "org.mayayai.creative.plan"
INTENT_VERSION = "1.0.0"
MAX_MESSAGE_BYTES = 65_536
MAX_JSON_DEPTH = 16
MAX_STRING_SCALARS = 4_096

ERROR_CODES = frozenset({
    "invalid_json",
    "input_too_large",
    "invalid_shape",
    "invalid_number",
    "unsupported_version",
    "unsupported_intent",
    "invalid_sequence",
    "scope_mismatch",
    "expired_message",
    "unsupported_locale",
    "input_unavailable",
    "internal_error",
})
ACTS = frozenset({
    "request", "proposal", "clarification", "accept", "decline",
    "acknowledge", "status", "result", "error",
})
MESSAGE_FIELDS = frozenset({
    "protocol_version", "message_id", "conversation_id", "sender", "recipient",
    "reply_to", "created_at", "expires_at", "act", "intent", "provenance",
})
PARTICIPANT_FIELDS = frozenset({"participant_id", "kind"})
INTENT_FIELDS = frozenset({"name", "version", "payload"})
PROVENANCE_FIELDS = frozenset({
    "mode", "adapter_id", "adapter_version", "interpretation_score", "human_reviewed",
})
MULTILINE_FIELDS = frozenset({"brief", "text", "summary", "description"})
_UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_UTC_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{6}Z$")
_ADAPTER_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")
_SEMVER_PATTERN = re.compile(r"^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")


class LanguageValidationError(ValueError):
    """A fixed, non-sensitive failure code for language validation."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if type(code) is not str or code not in ERROR_CODES:
            code = "internal_error"
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"LanguageValidationError({self.code!r})"


def _fail(code: str) -> None:
    raise LanguageValidationError(code)


def _json_string_size(value: str) -> int:
    if type(value) is not str:
        _fail("invalid_shape")
    if len(value) > MAX_MESSAGE_BYTES:
        _fail("input_too_large")
    try:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8", errors="strict"))
    except (UnicodeError, ValueError):
        _fail("invalid_json")


def _bounded_json_size(value: Any, *, depth: int = 0, active: set[int] | None = None) -> int:
    """Measure JSON size without invoking non-builtin conversion hooks."""
    if active is None:
        active = set()
    if type(value) is str:
        size = _json_string_size(value)
    elif value is None:
        size = 4
    elif type(value) is bool:
        size = 4 if value is True else 5
    elif type(value) is int:
        if value.bit_length() > 217_000:
            _fail("input_too_large")
        try:
            size = len(str(value))
        except ValueError:
            _fail("invalid_number")
    elif type(value) is float:
        if not math.isfinite(value):
            _fail("invalid_number")
        try:
            size = len(json.dumps(value, allow_nan=False, separators=(",", ":")))
        except (TypeError, ValueError, OverflowError):
            _fail("invalid_number")
    elif type(value) in (dict, list):
        next_depth = depth + 1
        if next_depth > MAX_JSON_DEPTH:
            _fail("invalid_json")
        identity = id(value)
        if identity in active:
            _fail("invalid_json")
        active.add(identity)
        try:
            if type(value) is list:
                size = 2
                for index, item in enumerate(value):
                    if index:
                        size += 1
                    size += _bounded_json_size(item, depth=next_depth, active=active)
                    if size > MAX_MESSAGE_BYTES:
                        _fail("input_too_large")
            else:
                size = 2
                for index, (key, item) in enumerate(value.items()):
                    if type(key) is not str:
                        _fail("invalid_shape")
                    if index:
                        size += 1
                    size += _json_string_size(key) + 1
                    size += _bounded_json_size(item, depth=next_depth, active=active)
                    if size > MAX_MESSAGE_BYTES:
                        _fail("input_too_large")
        finally:
            active.remove(identity)
    else:
        _fail("invalid_shape")
    if size > MAX_MESSAGE_BYTES:
        _fail("input_too_large")
    return size


def _validate_text(value: Any, *, maximum: int, allow_lf: bool = False) -> str:
    if type(value) is not str:
        _fail("invalid_shape")
    if len(value) > maximum or not value.strip():
        _fail("invalid_shape")
    if any(0xD800 <= ord(char) <= 0xDFFF for char in value):
        _fail("invalid_json")
    for char in value:
        codepoint = ord(char)
        if codepoint == 0x0A and allow_lf:
            continue
        if codepoint <= 0x1F or codepoint == 0x7F:
            _fail("invalid_shape")
    return value


def _validate_json_tree(value: Any, *, depth: int = 0, field: str | None = None, active: set[int] | None = None) -> None:
    if active is None:
        active = set()
    if type(value) is str:
        if len(value) > MAX_STRING_SCALARS:
            _fail("invalid_shape")
        _validate_text(value, maximum=MAX_STRING_SCALARS, allow_lf=field in MULTILINE_FIELDS)
        return
    if value is None or type(value) in (bool, int):
        return
    if type(value) is float:
        if not math.isfinite(value):
            _fail("invalid_number")
        return
    if type(value) not in (dict, list):
        _fail("invalid_shape")
    if depth >= MAX_JSON_DEPTH:
        _fail("invalid_json")
    identity = id(value)
    if identity in active:
        _fail("invalid_json")
    active.add(identity)
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    _fail("invalid_shape")
                _validate_json_tree(key, depth=depth + 1, active=active)
                _validate_json_tree(item, depth=depth + 1, field=key, active=active)
        else:
            for item in value:
                _validate_json_tree(item, depth=depth + 1, active=active)
    finally:
        active.remove(identity)


def _exact_object(value: Any, fields: frozenset[str]) -> dict[str, Any]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        _fail("invalid_shape")
    if set(value) != fields:
        _fail("invalid_shape")
    return value


def _canonical_uuid(value: Any) -> str:
    if type(value) is not str or not _UUID_PATTERN.fullmatch(value):
        _fail("invalid_shape")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        _fail("invalid_shape")
    if str(parsed) != value or parsed.variant != "specified in RFC 4122":
        _fail("invalid_shape")
    return value


def _parse_utc(value: Any) -> datetime:
    if type(value) is not str or not _UTC_PATTERN.fullmatch(value):
        _fail("invalid_shape")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except (ValueError, OverflowError):
        _fail("invalid_shape")
    if parsed.isoformat(timespec="microseconds").replace("+00:00", "Z") != value:
        _fail("invalid_shape")
    return parsed


@dataclass(frozen=True, slots=True)
class _FrozenObject:
    items: tuple[tuple[str, Any], ...]


@dataclass(frozen=True, slots=True)
class _FrozenArray:
    items: tuple[Any, ...]


def _freeze_json(value: Any) -> Any:
    if type(value) is dict:
        return _FrozenObject(tuple((key, _freeze_json(item)) for key, item in sorted(value.items())))
    if type(value) is list:
        return _FrozenArray(tuple(_freeze_json(item) for item in value))
    return value


def _thaw_json(value: Any) -> Any:
    if isinstance(value, _FrozenObject):
        return {key: _thaw_json(item) for key, item in value.items}
    if isinstance(value, _FrozenArray):
        return [_thaw_json(item) for item in value.items]
    return value


@dataclass(frozen=True, slots=True)
class _Participant:
    participant_id: str
    kind: str

    def payload(self) -> dict[str, str]:
        return {"participant_id": self.participant_id, "kind": self.kind}


@dataclass(frozen=True, slots=True)
class _Intent:
    name: str
    version: str
    _payload: _FrozenObject

    @property
    def payload(self) -> dict[str, Any]:
        return _thaw_json(self._payload)


@dataclass(frozen=True, slots=True)
class _Provenance:
    mode: str
    adapter_id: str
    adapter_version: str
    interpretation_score: int | float | None
    human_reviewed: bool

    def payload(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "adapter_id": self.adapter_id,
            "adapter_version": self.adapter_version,
            "interpretation_score": self.interpretation_score,
            "human_reviewed": self.human_reviewed,
        }


def _validate_shape_types(value: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    value = _exact_object(value, MESSAGE_FIELDS)
    for key in ("protocol_version", "message_id", "conversation_id", "created_at", "expires_at", "act"):
        if type(value[key]) is not str:
            _fail("invalid_shape")
    if value["reply_to"] is not None and type(value["reply_to"]) is not str:
        _fail("invalid_shape")

    sender = _exact_object(value["sender"], PARTICIPANT_FIELDS)
    recipient = _exact_object(value["recipient"], PARTICIPANT_FIELDS)
    for participant in (sender, recipient):
        if type(participant["participant_id"]) is not str or type(participant["kind"]) is not str:
            _fail("invalid_shape")

    intent = _exact_object(value["intent"], INTENT_FIELDS)
    if type(intent["name"]) is not str or type(intent["version"]) is not str:
        _fail("invalid_shape")
    if type(intent["payload"]) is not dict:
        _fail("invalid_shape")

    provenance = _exact_object(value["provenance"], PROVENANCE_FIELDS)
    if any(type(provenance[key]) is not str for key in ("mode", "adapter_id", "adapter_version")):
        _fail("invalid_shape")
    if provenance["interpretation_score"] is not None and type(provenance["interpretation_score"]) not in (int, float):
        _fail("invalid_shape")
    if type(provenance["human_reviewed"]) is not bool:
        _fail("invalid_shape")
    return sender, recipient, intent


def _validate_payload(act: str, payload: dict[str, Any]) -> _FrozenObject:
    if act == "request":
        fields = _exact_object(payload, frozenset({"brief", "medium"}))
        _validate_text(fields["brief"], maximum=4096, allow_lf=True)
        if type(fields["medium"]) is not str or fields["medium"] not in {"text", "image", "audio", "video"}:
            _fail("invalid_shape")
    elif act == "proposal":
        fields = _exact_object(payload, frozenset({"summary", "steps"}))
        _validate_text(fields["summary"], maximum=1024, allow_lf=True)
        steps = fields["steps"]
        if type(steps) is not list or not (1 <= len(steps) <= 16):
            _fail("invalid_shape")
        for expected_id, raw_step in enumerate(steps, start=1):
            step = _exact_object(raw_step, frozenset({"step_id", "description"}))
            if type(step["step_id"]) is not int:
                _fail("invalid_shape")
            if not (1 <= step["step_id"] <= 16):
                _fail("invalid_shape")
            if step["step_id"] != expected_id:
                _fail("invalid_sequence")
            _validate_text(step["description"], maximum=1024, allow_lf=True)
    elif act == "clarification":
        fields = _exact_object(payload, frozenset({"text", "about"}))
        _validate_text(fields["text"], maximum=1024, allow_lf=True)
        if type(fields["about"]) is not str or fields["about"] not in {"brief", "proposal"}:
            _fail("invalid_shape")
    elif act in {"accept", "acknowledge"}:
        _exact_object(payload, frozenset())
    elif act == "decline":
        fields = _exact_object(payload, frozenset({"reason"}))
        if type(fields["reason"]) is not str or fields["reason"] not in {"not_intended", "needs_revision", "not_now"}:
            _fail("invalid_shape")
    elif act == "status":
        fields = _exact_object(payload, frozenset({"state", "text"}))
        if type(fields["state"]) is not str or fields["state"] not in {"planning", "waiting_for_input"}:
            _fail("invalid_shape")
        _validate_text(fields["text"], maximum=1024, allow_lf=True)
    elif act == "result":
        fields = _exact_object(payload, frozenset({"summary"}))
        _validate_text(fields["summary"], maximum=4096, allow_lf=True)
    else:  # error
        fields = _exact_object(payload, frozenset({"code"}))
        if type(fields["code"]) is not str or fields["code"] not in {
            "unsupported_request", "permission_denied", "provider_unavailable", "internal_error",
        }:
            _fail("invalid_shape")
    frozen = _freeze_json(payload)
    assert isinstance(frozen, _FrozenObject)
    return frozen


def _validated_message(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("invalid_shape")
    _bounded_json_size(value)
    _validate_json_tree(value)
    sender, recipient, intent = _validate_shape_types(value)

    if value["protocol_version"] != PROTOCOL_VERSION:
        _fail("unsupported_version")
    if value["act"] not in ACTS:
        _fail("unsupported_intent")
    if intent["name"] != INTENT_NAME or intent["version"] != INTENT_VERSION:
        _fail("unsupported_intent")

    message_id = _canonical_uuid(value["message_id"])
    conversation_id = _canonical_uuid(value["conversation_id"])
    sender_id = _canonical_uuid(sender["participant_id"])
    recipient_id = _canonical_uuid(recipient["participant_id"])
    sender_kind = sender["kind"]
    recipient_kind = recipient["kind"]
    if sender_kind not in {"human", "agent"} or recipient_kind not in {"human", "agent"}:
        _fail("invalid_shape")
    reply_to = value["reply_to"]
    if reply_to is not None:
        reply_to = _canonical_uuid(reply_to)
    created = _parse_utc(value["created_at"])
    expires = _parse_utc(value["expires_at"])

    if value["act"] == "request":
        payload_fields = _exact_object(intent["payload"], frozenset({"brief", "medium"}))
    elif value["act"] == "proposal":
        payload_fields = _exact_object(intent["payload"], frozenset({"summary", "steps"}))
    elif value["act"] == "clarification":
        payload_fields = _exact_object(intent["payload"], frozenset({"text", "about"}))
    elif value["act"] in {"accept", "acknowledge"}:
        payload_fields = _exact_object(intent["payload"], frozenset())
    elif value["act"] == "decline":
        payload_fields = _exact_object(intent["payload"], frozenset({"reason"}))
    elif value["act"] == "status":
        payload_fields = _exact_object(intent["payload"], frozenset({"state", "text"}))
    elif value["act"] == "result":
        payload_fields = _exact_object(intent["payload"], frozenset({"summary"}))
    else:
        payload_fields = _exact_object(intent["payload"], frozenset({"code"}))
    # Schema/version selection happens before act-specific value validation.
    frozen_payload = _validate_payload(value["act"], payload_fields)

    provenance = value["provenance"]
    mode = provenance["mode"]
    if mode not in {"text", "gesture", "speech", "agent"}:
        _fail("invalid_shape")
    adapter_id = provenance["adapter_id"]
    if not 3 <= len(adapter_id) <= 128 or not _ADAPTER_PATTERN.fullmatch(adapter_id):
        _fail("invalid_shape")
    if not _SEMVER_PATTERN.fullmatch(provenance["adapter_version"]):
        _fail("invalid_shape")
    score = provenance["interpretation_score"]
    if score is not None:
        if type(score) not in (int, float):
            _fail("invalid_shape")
        try:
            finite_score = math.isfinite(score)
        except (OverflowError, TypeError):
            finite_score = False
        if not finite_score or score < 0 or score > 1:
            _fail("invalid_number")

    # Relational invariants come after every field and payload value check.
    if sender_id == recipient_id:
        _fail("invalid_shape")
    if reply_to == message_id or (value["act"] == "request") != (reply_to is None):
        _fail("invalid_sequence")
    if expires <= created or expires - created > timedelta(seconds=600):
        _fail("invalid_sequence")
    if (mode == "agent") != (sender_kind == "agent"):
        _fail("invalid_shape")

    return {
        "protocol_version": PROTOCOL_VERSION,
        "message_id": message_id,
        "conversation_id": conversation_id,
        "sender": _Participant(sender_id, sender_kind),
        "recipient": _Participant(recipient_id, recipient_kind),
        "reply_to": reply_to,
        "created_at": value["created_at"],
        "expires_at": value["expires_at"],
        "act": value["act"],
        "intent": _Intent(INTENT_NAME, INTENT_VERSION, frozen_payload),
        "provenance": _Provenance(
            mode,
            adapter_id,
            provenance["adapter_version"],
            score,
            provenance["human_reviewed"],
        ),
    }


@dataclass(frozen=True, slots=True, init=False, repr=False)
class Message:
    """Immutable, structurally validated communication record."""

    protocol_version: str
    message_id: str
    conversation_id: str
    sender: _Participant
    recipient: _Participant
    reply_to: str | None
    created_at: str
    expires_at: str
    act: str
    intent: _Intent
    provenance: _Provenance

    def __init__(self, *args: Any, **values: Any) -> None:
        if args:
            _fail("invalid_shape")
        normalized = _validated_message(values)
        for key, value in normalized.items():
            object.__setattr__(self, key, value)

    def payload(self) -> dict[str, Any]:
        return {
            "protocol_version": self.protocol_version,
            "message_id": self.message_id,
            "conversation_id": self.conversation_id,
            "sender": self.sender.payload(),
            "recipient": self.recipient.payload(),
            "reply_to": self.reply_to,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "act": self.act,
            "intent": {
                "name": self.intent.name,
                "version": self.intent.version,
                "payload": self.intent.payload,
            },
            "provenance": self.provenance.payload(),
        }

    def to_bytes(self) -> bytes:
        try:
            encoded = json.dumps(
                self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
            ).encode("utf-8", errors="strict")
        except (TypeError, ValueError, UnicodeError, OverflowError):
            _fail("internal_error")
        if len(encoded) > MAX_MESSAGE_BYTES:
            _fail("input_too_large")
        return encoded

    def __repr__(self) -> str:
        return f"Message(message_id={self.message_id!r}, act={self.act!r}, protocol_version={self.protocol_version!r})"


def parse_message(data: bytes | dict[str, Any]) -> Message:
    """Parse bounded UTF-8 JSON bytes or an exact builtin message dictionary."""
    if type(data) is bytes:
        try:
            value = parse_json_bytes(
                data,
                limit=MAX_MESSAGE_BYTES,
                max_depth=MAX_JSON_DEPTH,
                max_string_scalars=MAX_MESSAGE_BYTES,
            )
        except MudraValidationError as exc:
            if exc.code == "input_too_large":
                _fail("input_too_large")
            _fail("invalid_json")
    elif type(data) is dict:
        if any(type(key) is not str for key in data):
            _fail("invalid_shape")
        value = data
    else:
        _fail("invalid_shape")
    if type(value) is not dict:
        _fail("invalid_shape")
    return Message(**value)


def check_freshness(message: Message, now_utc: str) -> bool:
    """Check message age against an explicit strict UTC clock value."""
    if type(message) is not Message:
        _fail("invalid_shape")
    now = _parse_utc(now_utc)
    created = _parse_utc(message.created_at)
    expires = _parse_utc(message.expires_at)
    if created - now > timedelta(seconds=30) or now > expires:
        _fail("expired_message")
    return True


__all__ = [
    "LanguageValidationError",
    "Message",
    "check_freshness",
    "parse_message",
]
