"""Portable, image-free protocol for Mudra Interact.

The core deliberately accepts landmarks and emits small semantic events.  It
does not identify people, retain camera media, or make health claims.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Mapping
from uuid import uuid4


class InteractionParty(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class RecognitionState(StrEnum):
    CANDIDATE = "candidate"
    STABLE = "stable"
    UNCERTAIN = "uncertain"
    REJECTED = "rejected"


class PrivacyMode(StrEnum):
    LOCAL_LANDMARKS_ONLY = "local_landmarks_only"
    EVENT_ONLY = "event_only"


@dataclass(frozen=True)
class Landmark:
    """One normalized 3-D hand landmark in MediaPipe ordering."""

    x: float
    y: float
    z: float = 0.0

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Landmark":
        return cls(
            x=float(value["x"]),
            y=float(value["y"]),
            z=float(value.get("z", 0.0)),
        )


@dataclass(frozen=True)
class Recognition:
    gesture_id: str
    confidence: float
    state: RecognitionState
    method: str = "landmark_rules_v1"
    observations: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()
    catalog_version: str = "1.0.0"

    def __post_init__(self) -> None:
        object.__setattr__(self, "gesture_id", str(self.gesture_id).strip().lower()[:80] or "unknown")
        object.__setattr__(self, "confidence", max(0.0, min(float(self.confidence), 1.0)))


@dataclass(frozen=True)
class MudraEvent:
    """A shareable event. Raw image and landmark arrays never belong here."""

    recognition: Recognition
    sender: InteractionParty = InteractionParty.HUMAN
    recipient: InteractionParty = InteractionParty.AGENT
    privacy_mode: PrivacyMode = PrivacyMode.LOCAL_LANDMARKS_ONLY
    event_id: str = field(default_factory=lambda: str(uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    conversation_id: str | None = None
    project_id: str | None = None
    consent_confirmed: bool = True
    metadata: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.consent_confirmed and self.sender is InteractionParty.HUMAN:
            raise ValueError("Human-originated Mudra events require explicit consent.")
        safe_metadata = {
            str(key)[:80]: str(value)[:240]
            for key, value in self.metadata.items()
            if str(key).strip() and str(value).strip()
        }
        object.__setattr__(self, "metadata", safe_metadata)

    @property
    def direction(self) -> str:
        return f"{self.sender.value}_to_{self.recipient.value}"

    def payload(self) -> dict[str, Any]:
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
            "recognition": {
                **asdict(self.recognition),
                "state": self.recognition.state.value,
            },
            "metadata": dict(self.metadata),
            "raw_media_retained": False,
            "raw_landmarks_retained": False,
        }
