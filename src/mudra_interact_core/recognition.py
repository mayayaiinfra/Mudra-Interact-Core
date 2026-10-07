"""Deterministic v2 contact-rule recognition and a small local stabilizer."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Any

from .coordinates import to_cartesian
from .errors import MudraValidationError
from .frame import Frame, Landmark
from .protocol import Recognition, RecognitionState
from .validation import InteractionConfig, fail


WRIST = 0
MIDDLE_MCP = 9
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_TIP = 12
RING_TIP = 16


def _distance(left: Landmark, right: Landmark) -> float:
    return sqrt((left.x - right.x) ** 2 + (left.y - right.y) ** 2 + (left.z - right.z) ** 2)


def _landmarks(value: Any) -> tuple[Landmark, ...]:
    if isinstance(value, Frame):
        return to_cartesian(value)
    if type(value) not in (list, tuple) or len(value) != 21:
        fail("invalid_shape")
    result: list[Landmark] = []
    for point in value:
        if not isinstance(point, Landmark):
            fail("invalid_shape")
        result.append(Landmark(point.x, point.y, point.z))
    return tuple(result)


@dataclass(frozen=True, slots=True)
class ContactFeatures:
    palm_scale: float
    thumb_index: float
    thumb_middle: float
    thumb_ring: float

    def contacts(self, threshold: float) -> dict[str, bool]:
        if type(threshold) not in (int, float):
            fail("invalid_configuration")
        return {
            "thumb_index": self.thumb_index <= threshold,
            "thumb_middle": self.thumb_middle <= threshold,
            "thumb_ring": self.thumb_ring <= threshold,
        }


def extract_contact_features(value: Any) -> ContactFeatures:
    landmarks = _landmarks(value)
    palm_scale = _distance(landmarks[WRIST], landmarks[MIDDLE_MCP])
    if palm_scale < 0.0001:
        fail("invalid_geometry")
    return ContactFeatures(
        palm_scale=palm_scale,
        thumb_index=_distance(landmarks[THUMB_TIP], landmarks[INDEX_TIP]) / palm_scale,
        thumb_middle=_distance(landmarks[THUMB_TIP], landmarks[MIDDLE_TIP]) / palm_scale,
        thumb_ring=_distance(landmarks[THUMB_TIP], landmarks[RING_TIP]) / palm_scale,
    )


RULES: dict[tuple[bool, bool, bool], tuple[str, RecognitionState, float, tuple[str, ...]]] = {
    (False, False, False): ("unknown", RecognitionState.UNCERTAIN, 0.0, ("unsupported_pattern",)),
    (True, False, False): ("contact_thumb_index", RecognitionState.CANDIDATE, 0.72, ("posture_unverified",)),
    (False, True, False): ("contact_thumb_middle", RecognitionState.CANDIDATE, 0.70, ("posture_unverified",)),
    (False, False, True): ("contact_thumb_ring", RecognitionState.CANDIDATE, 0.70, ("posture_unverified",)),
    (False, True, True): ("contact_thumb_middle_ring", RecognitionState.CANDIDATE, 0.78, ("posture_unverified",)),
    (True, True, False): ("unknown", RecognitionState.UNCERTAIN, 0.0, ("ambiguous_contacts",)),
    (True, False, True): ("unknown", RecognitionState.UNCERTAIN, 0.0, ("ambiguous_contacts",)),
    (True, True, True): ("unknown", RecognitionState.UNCERTAIN, 0.0, ("ambiguous_contacts",)),
}


class LandmarkRuleRecognizer:
    """Recognize only the four neutral geometric contact patterns."""

    def __init__(self, contact_threshold: float = 0.34, *, config: InteractionConfig | None = None) -> None:
        if config is not None:
            if type(config) is not InteractionConfig:
                fail("invalid_configuration")
            if contact_threshold != 0.34:
                fail("invalid_configuration")
            self.config = config
        else:
            self.config = InteractionConfig(contact_threshold=contact_threshold)

    @property
    def contact_threshold(self) -> float:
        return self.config.contact_threshold

    def recognize(self, value: Any) -> Recognition:
        features = extract_contact_features(value)
        contacts = features.contacts(self.config.contact_threshold)
        bits = (contacts["thumb_index"], contacts["thumb_middle"], contacts["thumb_ring"])
        gesture_id, state, confidence, uncertainties = RULES[bits]
        observations = tuple(
            code
            for active, code in (
                (contacts["thumb_index"], "thumb_index_contact"),
                (contacts["thumb_middle"], "thumb_middle_contact"),
                (contacts["thumb_ring"], "thumb_ring_contact"),
            )
            if active
        )
        return Recognition(
            gesture_id=gesture_id,
            confidence=confidence,
            state=state,
            method="contact_rules_v2",
            observations=observations,
            uncertainties=uncertainties,
            catalog_version="2.0.0",
        )


class RecognitionStabilizer:
    """A bounded compatibility stabilizer; session timing is MI-04's concern."""

    def __init__(self, required_frames: int = 3, minimum_confidence: float = 0.6) -> None:
        self.config = InteractionConfig(required_frames=required_frames, minimum_confidence=minimum_confidence)
        self._recent: deque[Recognition] = deque(maxlen=self.config.required_frames)

    def reset(self) -> None:
        self._recent.clear()

    def update(self, recognition: Recognition) -> Recognition:
        if not isinstance(recognition, Recognition):
            fail("invalid_shape")
        if recognition.state is not RecognitionState.CANDIDATE or recognition.confidence < self.config.minimum_confidence:
            self.reset()
            return recognition
        if self._recent and recognition.gesture_id != self._recent[-1].gesture_id:
            self.reset()
            self._recent.append(recognition)
            return Recognition(
                gesture_id="unknown",
                confidence=0.0,
                state=RecognitionState.UNCERTAIN,
                method="contact_rules_v2",
                observations=recognition.observations,
                uncertainties=("gesture_changed",),
                catalog_version="2.0.0",
            )
        self._recent.append(recognition)
        if len(self._recent) < self.config.required_frames:
            return recognition
        confidence = sum(item.confidence for item in self._recent) / len(self._recent)
        return Recognition(
            gesture_id=recognition.gesture_id,
            confidence=confidence,
            state=RecognitionState.STABLE,
            method="contact_rules_v2",
            observations=recognition.observations,
            uncertainties=recognition.uncertainties,
            catalog_version="2.0.0",
        )


__all__ = ["ContactFeatures", "LandmarkRuleRecognizer", "RecognitionStabilizer", "RULES", "extract_contact_features"]
