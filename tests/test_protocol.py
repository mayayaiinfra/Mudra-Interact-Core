from __future__ import annotations

import pytest

from mudra_interact_core.protocol import Landmark, MudraEvent, PrivacyMode, RecognitionState
from mudra_interact_core.recognition import LandmarkRuleRecognizer, RecognitionStabilizer


def sample_landmarks() -> list[Landmark]:
    points = [Landmark(float(index % 5) + 2.0, float(index // 5) + 2.0) for index in range(21)]
    points[0] = Landmark(0.0, 0.0)
    points[9] = Landmark(0.0, 1.0)
    points[4] = Landmark(0.2, 0.6)
    points[8] = Landmark(1.5, 1.5)
    points[12] = Landmark(1.7, 1.5)
    points[16] = Landmark(1.9, 1.5)
    return points


def test_recognizes_thumb_index_pattern_as_ambiguous_gyan_or_chin() -> None:
    landmarks = sample_landmarks()
    landmarks[8] = Landmark(0.23, 0.62)
    result = LandmarkRuleRecognizer().recognize(landmarks)
    assert result.gesture_id == "contact_thumb_index"
    assert result.state is RecognitionState.CANDIDATE
    assert "posture_unverified" in result.uncertainties


def test_recognizes_apana_before_single_contacts() -> None:
    landmarks = sample_landmarks()
    landmarks[12] = Landmark(0.22, 0.61)
    landmarks[16] = Landmark(0.24, 0.62)
    result = LandmarkRuleRecognizer().recognize(landmarks)
    assert result.gesture_id == "contact_thumb_middle_ring"


def test_stabilizer_promotes_repeated_candidate() -> None:
    landmarks = sample_landmarks()
    landmarks[8] = Landmark(0.23, 0.62)
    recognizer = LandmarkRuleRecognizer()
    stabilizer = RecognitionStabilizer(required_frames=3)
    candidate = recognizer.recognize(landmarks)
    stabilizer.update(candidate)
    stabilizer.update(candidate)
    stable = stabilizer.update(candidate)
    assert stable.state is RecognitionState.STABLE
    assert stable.gesture_id == candidate.gesture_id


def test_shareable_event_has_no_raw_media_or_landmarks() -> None:
    landmarks = sample_landmarks()
    landmarks[8] = Landmark(0.23, 0.62)
    recognition = LandmarkRuleRecognizer().recognize(landmarks)
    stabilizer = RecognitionStabilizer()
    stabilizer.update(recognition)
    stabilizer.update(recognition)
    stable = stabilizer.update(recognition)
    event = MudraEvent(
        recognition=stable,
        privacy_mode=PrivacyMode.EVENT_ONLY,
        participant_confirmed=True,
        occurred_at="2026-10-07T01:00:00.000000Z",
    )
    payload = event.payload()
    assert payload["raw_media_included"] is False
    assert payload["raw_landmarks_included"] is False
    assert "landmarks" not in payload
    assert "landmarks" not in payload["recognition"]


def test_requires_twenty_one_landmarks() -> None:
    with pytest.raises(ValueError):
        LandmarkRuleRecognizer().recognize([Landmark(0, 0)] * 20)
