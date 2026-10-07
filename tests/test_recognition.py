from __future__ import annotations

import math

import pytest

from mudra_interact_core import Landmark
from mudra_interact_core.recognition import LandmarkRuleRecognizer
from mudra_interact_core.protocol import RecognitionState


def points(bits: tuple[bool, bool, bool], distance: float = 0.2) -> list[Landmark]:
    result = [Landmark(0.0, 0.0, 0.0) for _ in range(21)]
    result[9] = Landmark(0.0, 1.0, 0.0)
    for index, active in zip((8, 12, 16), bits):
        result[index] = Landmark(distance if active else 1.0, 0.0, 0.0)
    return result


@pytest.mark.acceptance("E20")
@pytest.mark.parametrize(
    "bits,gesture,state,confidence",
    [
        ((False, False, False), "unknown", RecognitionState.UNCERTAIN, 0.0),
        ((True, False, False), "contact_thumb_index", RecognitionState.CANDIDATE, 0.72),
        ((False, True, False), "contact_thumb_middle", RecognitionState.CANDIDATE, 0.70),
        ((False, False, True), "contact_thumb_ring", RecognitionState.CANDIDATE, 0.70),
        ((False, True, True), "contact_thumb_middle_ring", RecognitionState.CANDIDATE, 0.78),
        ((True, True, False), "unknown", RecognitionState.UNCERTAIN, 0.0),
        ((True, False, True), "unknown", RecognitionState.UNCERTAIN, 0.0),
        ((True, True, True), "unknown", RecognitionState.UNCERTAIN, 0.0),
    ],
)
def test_all_eight_contact_patterns_match_the_fixed_oracle(bits, gesture, state, confidence) -> None:
    result = LandmarkRuleRecognizer().recognize(points(bits))
    assert (result.gesture_id, result.state, result.confidence) == (gesture, state, confidence)


@pytest.mark.acceptance("E21")
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_contact_threshold_is_inclusive(delta: int) -> None:
    threshold = 0.34
    distance = math.nextafter(threshold, 0.0) if delta < 0 else math.nextafter(threshold, math.inf) if delta > 0 else threshold
    result = LandmarkRuleRecognizer().recognize(points((True, False, False), distance))
    assert (result.gesture_id == "contact_thumb_index") is (delta <= 0)


@pytest.mark.acceptance("E25")
def test_result_uses_exact_method_catalogue_scores_and_codes() -> None:
    result = LandmarkRuleRecognizer().recognize(points((False, True, True)))
    assert result.method == "contact_rules_v2"
    assert result.catalog_version == "2.0.0"
    assert result.gesture_id == "contact_thumb_middle_ring"
    assert result.confidence == 0.78
    assert result.observation_codes == ("thumb_middle_contact", "thumb_ring_contact")
    assert result.uncertainty_codes == ("posture_unverified",)


@pytest.mark.acceptance("E26")
def test_uncertain_and_supported_results_contain_codes_only() -> None:
    uncertain = LandmarkRuleRecognizer().recognize(points((True, True, True)))
    assert uncertain.gesture_id == "unknown"
    assert uncertain.confidence == 0.0
    assert uncertain.uncertainties == ("ambiguous_contacts",)
    assert all("distance" not in code and " " not in code for code in uncertain.observations + uncertain.uncertainties)

