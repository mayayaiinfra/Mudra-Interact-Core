"""Landmark-only Mudra recognition with explicit uncertainty."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from math import sqrt
from typing import Iterable

from .protocol import Landmark, Recognition, RecognitionState


WRIST = 0
MIDDLE_MCP = 9
THUMB_TIP = 4
INDEX_TIP = 8
MIDDLE_TIP = 12
RING_TIP = 16


def _distance(left: Landmark, right: Landmark) -> float:
    return sqrt((left.x - right.x) ** 2 + (left.y - right.y) ** 2 + (left.z - right.z) ** 2)


def _landmarks(value: Iterable[Landmark]) -> tuple[Landmark, ...]:
    landmarks = tuple(value)
    if len(landmarks) != 21:
        raise ValueError("Mudra Interact requires exactly 21 hand landmarks in MediaPipe order.")
    scale = _distance(landmarks[WRIST], landmarks[MIDDLE_MCP])
    if scale < 0.0001:
        raise ValueError("Hand landmark scale is invalid or too small.")
    return landmarks


@dataclass(frozen=True)
class ContactFeatures:
    palm_scale: float
    thumb_index: float
    thumb_middle: float
    thumb_ring: float

    def contacts(self, threshold: float) -> dict[str, bool]:
        return {
            "thumb_index": self.thumb_index <= threshold,
            "thumb_middle": self.thumb_middle <= threshold,
            "thumb_ring": self.thumb_ring <= threshold,
        }


def extract_contact_features(value: Iterable[Landmark]) -> ContactFeatures:
    landmarks = _landmarks(value)
    palm_scale = _distance(landmarks[WRIST], landmarks[MIDDLE_MCP])
    return ContactFeatures(
        palm_scale=palm_scale,
        thumb_index=_distance(landmarks[THUMB_TIP], landmarks[INDEX_TIP]) / palm_scale,
        thumb_middle=_distance(landmarks[THUMB_TIP], landmarks[MIDDLE_TIP]) / palm_scale,
        thumb_ring=_distance(landmarks[THUMB_TIP], landmarks[RING_TIP]) / palm_scale,
    )


class LandmarkRuleRecognizer:
    """Conservative contact-pattern recognizer.

    This release purposely treats Gyan and Chin as one ambiguous pair. Palm
    orientation and tradition-specific context must be evaluated before a
    system distinguishes them. It does not attempt medical interpretation.
    """

    def __init__(self, contact_threshold: float = 0.34) -> None:
        self.contact_threshold = max(0.05, min(float(contact_threshold), 0.75))

    def recognize(self, value: Iterable[Landmark]) -> Recognition:
        features = extract_contact_features(value)
        contacts = features.contacts(self.contact_threshold)
        active = tuple(name for name, present in contacts.items() if present)
        observations = tuple(
            f"{name.replace('_', ' ')} normalized distance={getattr(features, name):.3f}"
            for name in active
        )
        if contacts["thumb_middle"] and contacts["thumb_ring"] and not contacts["thumb_index"]:
            return Recognition(
                gesture_id="apana_mudra",
                confidence=0.78,
                state=RecognitionState.CANDIDATE,
                observations=observations,
                uncertainties=("Confirm the finger posture before using this as a learning label.",),
            )
        if active == ("thumb_index",):
            return Recognition(
                gesture_id="gyan_or_chin_mudra",
                confidence=0.72,
                state=RecognitionState.CANDIDATE,
                observations=observations,
                uncertainties=("Palm orientation and context are needed to distinguish Gyan from Chin.",),
            )
        if active == ("thumb_middle",):
            return Recognition(
                gesture_id="shunya_mudra",
                confidence=0.7,
                state=RecognitionState.CANDIDATE,
                observations=observations,
                uncertainties=("Confirm posture with the participant before sharing the label.",),
            )
        if active == ("thumb_ring",):
            return Recognition(
                gesture_id="prithvi_mudra",
                confidence=0.7,
                state=RecognitionState.CANDIDATE,
                observations=observations,
                uncertainties=("Confirm posture with the participant before sharing the label.",),
            )
        return Recognition(
            gesture_id="unknown",
            confidence=0.0,
            state=RecognitionState.UNCERTAIN,
            observations=observations,
            uncertainties=("No supported contact pattern was detected. Adjust framing or choose a catalog gesture.",),
        )


class RecognitionStabilizer:
    """Promotes a repeated candidate to stable without training an LSTM."""

    def __init__(self, required_frames: int = 3, minimum_confidence: float = 0.6) -> None:
        self.required_frames = max(2, min(int(required_frames), 12))
        self.minimum_confidence = max(0.0, min(float(minimum_confidence), 1.0))
        self._recent: deque[Recognition] = deque(maxlen=self.required_frames)

    def reset(self) -> None:
        self._recent.clear()

    def update(self, recognition: Recognition) -> Recognition:
        if recognition.state is RecognitionState.UNCERTAIN or recognition.confidence < self.minimum_confidence:
            self.reset()
            return recognition
        self._recent.append(recognition)
        if len(self._recent) < self.required_frames:
            return recognition
        gesture_ids = {item.gesture_id for item in self._recent}
        if len(gesture_ids) != 1:
            return Recognition(
                gesture_id="unknown",
                confidence=0.0,
                state=RecognitionState.UNCERTAIN,
                observations=recognition.observations,
                uncertainties=("The observed gesture changed between frames. Keep the hand steady and retry.",),
            )
        average_confidence = sum(item.confidence for item in self._recent) / len(self._recent)
        return Recognition(
            gesture_id=recognition.gesture_id,
            confidence=average_confidence,
            state=RecognitionState.STABLE,
            method=recognition.method,
            observations=recognition.observations,
            uncertainties=recognition.uncertainties,
            catalog_version=recognition.catalog_version,
        )
