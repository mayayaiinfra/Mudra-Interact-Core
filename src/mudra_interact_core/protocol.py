"""Versioned protocol values and strict event import boundary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4

from .errors import MudraValidationError
from .frame import Frame, FrameBatch, Landmark
from .validation import (
    CATALOG_VERSION,
    MAX_EVENT_BYTES,
    SCHEMA_VERSION,
    fail,
    parse_json_bytes,
    require_canonical_uuid,
    require_exact_fields,
    require_finite_float,
)


class InteractionParty(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class RecognitionState(StrEnum):
    CANDIDATE = "candidate"
    STABLE = "stable"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"  # local-only state; never valid in a v2 event


class PrivacyMode(StrEnum):
    LOCAL_LANDMARKS_ONLY = "local_landmarks_only"  # v1 compatibility value
    EVENT_ONLY = "event_only"


V2_GESTURE_IDS = frozenset(
    {
        "unknown",
        "contact_thumb_index",
        "contact_thumb_middle",
        "contact_thumb_ring",
        "contact_thumb_middle_ring",
    }
)
LEGACY_GESTURE_IDS = frozenset(
    {"gyan_or_chin_mudra", "apana_mudra", "shunya_mudra", "prithvi_mudra"}
)
V2_OBSERVATION_CODES = frozenset(
    {"thumb_index_contact", "thumb_middle_contact", "thumb_ring_contact"}
)
V2_UNCERTAINTY_CODES = frozenset(
    {
        "unsupported_pattern",
        "ambiguous_contacts",
        "posture_unverified",
        "low_confidence",
        "insufficient_frames",
        "hold_incomplete",
        "frame_gap",
        "gesture_changed",
    }
)
_OCCURRED_AT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")


def _codes(value: Any, allowed: frozenset[str] | None = None) -> tuple[str, ...]:
    if type(value) not in (list, tuple) or len(value) > 8:
        fail("invalid_shape")
    result: list[str] = []
    for item in value:
        if type(item) is not str or not item or len(item) > 80:
            fail("invalid_shape")
        if allowed is not None and item not in allowed:
            fail("invalid_shape")
        if item in result:
            fail("invalid_shape")
        result.append(item)
    return tuple(result)


@dataclass(frozen=True, slots=True)
class Recognition:
    """A copied, bounded recognition result."""

    gesture_id: str
    confidence: float
    state: RecognitionState
    method: str = "landmark_rules_v1"
    observations: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    catalog_version: str = "1.0.0"

    def __post_init__(self) -> None:
        if type(self.gesture_id) is not str or self.gesture_id not in (V2_GESTURE_IDS | LEGACY_GESTURE_IDS):
            fail("invalid_shape")
        if type(self.state) is not RecognitionState:
            fail("invalid_shape")
        object.__setattr__(self, "confidence", require_finite_float(self.confidence, code="invalid_number"))
        if type(self.method) is not str or not self.method or len(self.method) > 80:
            fail("invalid_shape")
        object.__setattr__(self, "observations", _codes(self.observations))
        object.__setattr__(self, "uncertainties", _codes(self.uncertainties))
        if type(self.catalog_version) is not str or not self.catalog_version:
            fail("invalid_shape")

    @property
    def observation_codes(self) -> tuple[str, ...]:
        return self.observations

    @property
    def uncertainty_codes(self) -> tuple[str, ...]:
        return self.uncertainties

    @classmethod
    def from_mapping(cls, value: Any) -> "Recognition":
        mapping = require_exact_fields(
            value,
            {
                "gesture_id",
                "confidence",
                "state",
                "method",
                "catalog_version",
                "observation_codes",
                "uncertainty_codes",
            },
        )
        if mapping["gesture_id"] not in V2_GESTURE_IDS:
            fail("invalid_shape")
        if type(mapping["state"]) is not str or mapping["state"] not in {
            "candidate",
            "stable",
            "uncertain",
        }:
            fail("invalid_state")
        if mapping["method"] != "contact_rules_v2" or mapping["catalog_version"] != CATALOG_VERSION:
            fail("unsupported_version")
        observations = _codes(mapping["observation_codes"], V2_OBSERVATION_CODES)
        uncertainties = _codes(mapping["uncertainty_codes"], V2_UNCERTAINTY_CODES)
        result = cls(
            gesture_id=mapping["gesture_id"],
            confidence=mapping["confidence"],
            state=RecognitionState(mapping["state"]),
            method="contact_rules_v2",
            observations=observations,
            uncertainties=uncertainties,
            catalog_version=CATALOG_VERSION,
        )
        if result.state is RecognitionState.STABLE and result.gesture_id == "unknown":
            fail("invalid_state")
        if result.state is RecognitionState.UNCERTAIN and (result.confidence != 0.0 or result.gesture_id != "unknown"):
            fail("invalid_state")
        if result.state in {RecognitionState.CANDIDATE, RecognitionState.STABLE} and result.confidence <= 0.0:
            fail("invalid_state")
        return result

    def payload(self) -> dict[str, Any]:
        return {
            "gesture_id": self.gesture_id,
            "confidence": self.confidence,
            "state": self.state.value,
            "method": self.method,
            "catalog_version": self.catalog_version,
            "observation_codes": list(self.observations),
            "uncertainty_codes": list(self.uncertainties),
        }


def _strict_occurred_at(value: Any) -> str:
    if type(value) is not str or not _OCCURRED_AT.fullmatch(value):
        fail("invalid_shape")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    except ValueError:
        fail("invalid_shape")
    if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") != value:
        fail("invalid_shape")
    return value


@dataclass(frozen=True, slots=True)
class MudraEvent:
    """A v2 shareable event, with an explicit v1 local compatibility payload."""

    recognition: Recognition
    sender: InteractionParty = InteractionParty.HUMAN
    recipient: InteractionParty = InteractionParty.AGENT
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_LANDMARKS_ONLY
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    conversation_id: str | None = None
    project_id: str | None = None
    consent_confirmed: bool = True
    participant_confirmed: bool | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.recognition, Recognition):
            fail("invalid_shape")
        if type(self.sender) is not InteractionParty or type(self.recipient) is not InteractionParty:
            fail("invalid_shape")
        require_canonical_uuid(self.event_id)
        if type(self.consent_confirmed) is not bool:
            fail("invalid_shape")
        if self.privacy_mode is PrivacyMode.EVENT_ONLY or self.participant_confirmed is not None:
            if self.privacy_mode is not PrivacyMode.EVENT_ONLY:
                fail("invalid_state")
            if self.participant_confirmed is not True or self.consent_confirmed is not True:
                fail("consent_required")
            if self.recognition.method != "contact_rules_v2" or self.recognition.catalog_version != CATALOG_VERSION:
                fail("unsupported_version")
            if self.recognition.state is not RecognitionState.STABLE:
                fail("invalid_state")
            _strict_occurred_at(self.occurred_at)
            require_canonical_uuid(self.conversation_id, nullable=True)
            require_canonical_uuid(self.project_id, nullable=True)
            if type(self.metadata) is not dict or self.metadata:
                fail("invalid_shape")
        else:
            if type(self.metadata) is not dict:
                fail("invalid_shape")
            if self.conversation_id is not None and type(self.conversation_id) is not str:
                fail("invalid_shape")
            if self.project_id is not None and type(self.project_id) is not str:
                fail("invalid_shape")

    @property
    def direction(self) -> str:
        return f"{self.sender.value}_to_{self.recipient.value}"

    @classmethod
    def from_mapping(cls, value: Any) -> "MudraEvent":
        mapping = require_exact_fields(
            value,
            {
                "schema_version",
                "event_id",
                "occurred_at",
                "sender",
                "recipient",
                "direction",
                "privacy_mode",
                "consent_confirmed",
                "participant_confirmed",
                "conversation_id",
                "project_id",
                "recognition",
                "raw_media_included",
                "raw_landmarks_included",
            },
        )
        if mapping["schema_version"] != SCHEMA_VERSION:
            fail("unsupported_version")
        try:
            sender = InteractionParty(mapping["sender"])
            recipient = InteractionParty(mapping["recipient"])
            privacy = PrivacyMode(mapping["privacy_mode"])
        except (ValueError, TypeError):
            fail("invalid_shape")
        if mapping["direction"] != f"{sender.value}_to_{recipient.value}":
            fail("invalid_state")
        if mapping["raw_media_included"] is not False or mapping["raw_landmarks_included"] is not False:
            fail("invalid_shape")
        recognition = Recognition.from_mapping(mapping["recognition"])
        return cls(
            recognition=recognition,
            sender=sender,
            recipient=recipient,
            privacy_mode=privacy,
            event_id=mapping["event_id"],
            occurred_at=mapping["occurred_at"],
            conversation_id=mapping["conversation_id"],
            project_id=mapping["project_id"],
            consent_confirmed=mapping["consent_confirmed"],
            participant_confirmed=mapping["participant_confirmed"],
            metadata={},
        )

    def payload(self) -> dict[str, Any]:
        if self.privacy_mode is PrivacyMode.EVENT_ONLY:
            return {
                "schema_version": SCHEMA_VERSION,
                "event_id": self.event_id,
                "occurred_at": self.occurred_at,
                "sender": self.sender.value,
                "recipient": self.recipient.value,
                "direction": self.direction,
                "privacy_mode": "event_only",
                "consent_confirmed": True,
                "participant_confirmed": True,
                "conversation_id": self.conversation_id,
                "project_id": self.project_id,
                "recognition": self.recognition.payload(),
                "raw_media_included": False,
                "raw_landmarks_included": False,
            }
        # Local compatibility output remains deliberately non-shareable.
        return {
            "schema_version": "1.0",
            "event_id": self.event_id,
            "occurred_at": self.occurred_at,
            "direction": self.direction,
            "sender": self.sender.value,
            "recipient": self.recipient.value,
            "privacy_mode": self.privacy_mode.value,
            "consent_confirmed": self.consent_confirmed,
            "conversation_id": self.conversation_id,
            "project_id": self.project_id,
            "recognition": self.recognition.payload(),
            "metadata": dict(self.metadata),
            "raw_media_retained": False,
            "raw_landmarks_retained": False,
        }

    def to_bytes(self) -> bytes:
        try:
            encoded = json.dumps(
                self.payload(), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8", errors="strict")
        except (TypeError, ValueError, UnicodeError):
            fail("invalid_shape")
        if len(encoded) > MAX_EVENT_BYTES:
            fail("input_too_large")
        return encoded


def parse_event(value: bytes | str | dict[str, Any]) -> MudraEvent:
    if isinstance(value, bytes):
        value = parse_json_bytes(value, limit=MAX_EVENT_BYTES)
    elif isinstance(value, str):
        from .validation import parse_json_text

        value = parse_json_text(value, limit=MAX_EVENT_BYTES)
    return MudraEvent.from_mapping(value)


__all__ = [
    "Frame",
    "FrameBatch",
    "InteractionParty",
    "Landmark",
    "MudraEvent",
    "PrivacyMode",
    "Recognition",
    "RecognitionState",
    "parse_event",
]
