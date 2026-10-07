from __future__ import annotations

import math

import pytest

from mudra_interact_core import Frame, Landmark, MudraValidationError, convert_landmarks
from mudra_interact_core.recognition import LandmarkRuleRecognizer


STREAM_ID = "123e4567-e89b-42d3-a456-426614174000"


def fixture_landmarks() -> list[Landmark]:
    points = [Landmark(0.0, 0.0, 0.0) for _ in range(21)]
    points[9] = Landmark(0.0, 1.0, 0.25)
    points[4] = Landmark(0.0, 0.0, 0.0)
    points[8] = Landmark(0.2, 0.0, 0.0)
    points[12] = Landmark(1.0, 0.0, 0.0)
    points[16] = Landmark(1.0, 0.0, 0.0)
    return points


def transformed(points: list[Landmark], fn) -> list[Landmark]:
    return [Landmark(*fn(point.x, point.y, point.z)) for point in points]


@pytest.mark.acceptance("E22")
def test_translation_uniform_scale_reflection_and_cartesian_rotation_preserve_rule() -> None:
    recognizer = LandmarkRuleRecognizer()
    base = fixture_landmarks()
    expected = recognizer.recognize(base)
    variants = [
        transformed(base, lambda x, y, z: (x + 1, y + 1, z + 1)),
        transformed(base, lambda x, y, z: (x * 2, y * 2, z * 2)),
        transformed(base, lambda x, y, z: (-x, y, z)),
        transformed(base, lambda x, y, z: (x * 0.8 - y * 0.6, x * 0.6 + y * 0.8, z)),
    ]
    for candidate in variants:
        result = recognizer.recognize(candidate)
        assert (result.gesture_id, result.confidence, result.state) == (
            expected.gesture_id,
            expected.confidence,
            expected.state,
        )


@pytest.mark.acceptance("E22")
def test_invalid_transformed_bounds_are_rejected() -> None:
    bad = fixture_landmarks()
    bad[12] = Landmark(0.0, 16.0, 0.0)
    with pytest.raises(MudraValidationError):
        Frame("2.0.0", STREAM_ID, 1, 100, "mediapipe_image_v1", tuple(bad), 1, 2)


@pytest.mark.acceptance("E23")
def test_portrait_and_landscape_image_spaces_match_cartesian_oracle() -> None:
    cartesian = fixture_landmarks()
    expected = LandmarkRuleRecognizer().recognize(cartesian)
    portrait = Frame("2.0.0", STREAM_ID, 1, 100, "mediapipe_image_v1", tuple(
        Landmark(point.x, point.y * 200 / 100, point.z) for point in cartesian
    ), 200, 100)
    landscape = Frame("2.0.0", STREAM_ID, 1, 100, "mediapipe_image_v1", tuple(
        Landmark(point.x, point.y * 100 / 200, point.z) for point in cartesian
    ), 100, 200)
    for frame in (portrait, landscape):
        result = LandmarkRuleRecognizer().recognize(frame)
        assert result.gesture_id == expected.gesture_id
        assert result.confidence == expected.confidence


@pytest.mark.acceptance("E24")
@pytest.mark.parametrize(
    "width,height,space",
    [(0, 100, "mediapipe_image_v1"), (-1, 100, "mediapipe_image_v1"), (True, 100, "mediapipe_image_v1"),
     (100, 100, "cartesian_relative_v1")],
)
def test_image_dimensions_and_space_are_explicit(width, height, space) -> None:
    with pytest.raises(MudraValidationError):
        Frame("2.0.0", STREAM_ID, 1, 100, space, tuple(fixture_landmarks()), width, height)


@pytest.mark.acceptance("E24")
def test_image_conversion_rejects_post_conversion_overflow_and_mixed_arguments() -> None:
    points = fixture_landmarks()
    points[12] = Landmark(0.0, 16.0, 0.0)
    with pytest.raises(MudraValidationError):
        Frame("2.0.0", STREAM_ID, 1, 100, "mediapipe_image_v1", tuple(points), 1, 2)
    with pytest.raises(MudraValidationError):
        convert_landmarks(points, coordinate_space="cartesian_relative_v1", image_width=100, image_height=100)

