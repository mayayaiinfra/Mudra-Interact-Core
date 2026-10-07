"""Declared coordinate-space conversion for the geometric recognizer."""

from __future__ import annotations

from typing import Sequence

from .errors import MudraValidationError
from .frame import COORDINATE_SPACES, Frame, Landmark
from .validation import MAX_IMAGE_DIMENSION, fail, require_coordinate


def convert_landmarks(
    landmarks: Sequence[Landmark],
    *,
    coordinate_space: str,
    image_width: int | None = None,
    image_height: int | None = None,
) -> tuple[Landmark, ...]:
    """Convert declared image-normalized y units into the Cartesian rule space."""

    if type(landmarks) not in (list, tuple) or len(landmarks) != 21:
        fail("invalid_shape")
    if type(coordinate_space) is not str or coordinate_space not in COORDINATE_SPACES:
        fail("invalid_configuration")
    if coordinate_space == "cartesian_relative_v1":
        if image_width is not None or image_height is not None:
            fail("invalid_configuration")
        return tuple(Landmark(point.x, point.y, point.z) for point in landmarks)
    if type(image_width) is not int or type(image_height) is not int:
        fail("invalid_configuration")
    if not (1 <= image_width <= MAX_IMAGE_DIMENSION and 1 <= image_height <= MAX_IMAGE_DIMENSION):
        fail("invalid_configuration")
    factor = image_height / image_width
    return tuple(Landmark(point.x, point.y * factor, point.z) for point in landmarks)


def to_cartesian(frame: Frame) -> tuple[Landmark, ...]:
    if not isinstance(frame, Frame):
        fail("invalid_shape")
    return frame.converted_landmarks()


__all__ = ["convert_landmarks", "to_cartesian"]
