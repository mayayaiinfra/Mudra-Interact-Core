"""Validated immutable v2 frames and bounded frame batches."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any

from .errors import MudraValidationError
from .validation import (
    MAX_BATCH_BYTES,
    MAX_BATCH_FRAMES,
    MAX_IMAGE_DIMENSION,
    MAX_FRAME_BYTES,
    MIN_PALM_SCALE,
    SCHEMA_VERSION,
    fail,
    parse_json_bytes,
    require_bounded_integer,
    require_coordinate,
    require_exact_fields,
)


COORDINATE_SPACES = frozenset({"cartesian_relative_v1", "mediapipe_image_v1"})
LANDMARK_FIELDS = {"x", "y", "z"}
FRAME_FIELDS = {
    "schema_version",
    "stream_id",
    "frame_id",
    "monotonic_ms",
    "coordinate_space",
    "landmarks",
}
IMAGE_FRAME_FIELDS = FRAME_FIELDS | {"image_width", "image_height"}
WRIST_INDEX = 0
MIDDLE_MCP_INDEX = 9


def _uuid_text(value: Any) -> str:
    from .validation import require_canonical_uuid

    result = require_canonical_uuid(value)
    assert result is not None
    return result


@dataclass(frozen=True, slots=True)
class Landmark:
    x: float
    y: float
    z: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "x", require_coordinate(self.x))
        object.__setattr__(self, "y", require_coordinate(self.y))
        object.__setattr__(self, "z", require_coordinate(self.z))

    @classmethod
    def from_mapping(cls, value: Any) -> "Landmark":
        mapping = require_exact_fields(value, LANDMARK_FIELDS)
        return cls(mapping["x"], mapping["y"], mapping["z"])

    def payload(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


def _landmark_tuple(value: Any) -> tuple[Landmark, ...]:
    if type(value) not in (list, tuple) or len(value) != 21:
        fail("invalid_shape")
    copied: list[Landmark] = []
    for landmark in value:
        if isinstance(landmark, Landmark):
            copied.append(Landmark(landmark.x, landmark.y, landmark.z))
        else:
            copied.append(Landmark.from_mapping(landmark))
    return tuple(copied)


@dataclass(frozen=True, slots=True)
class Frame:
    schema_version: str
    stream_id: str
    frame_id: int
    monotonic_ms: int
    coordinate_space: str
    landmarks: tuple[Landmark, ...]
    image_width: int | None = None
    image_height: int | None = None

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != SCHEMA_VERSION:
            fail("unsupported_version")
        object.__setattr__(self, "stream_id", _uuid_text(self.stream_id))
        object.__setattr__(self, "frame_id", require_bounded_integer(self.frame_id))
        object.__setattr__(self, "monotonic_ms", require_bounded_integer(self.monotonic_ms))
        if type(self.coordinate_space) is not str or self.coordinate_space not in COORDINATE_SPACES:
            fail("invalid_configuration")
        object.__setattr__(self, "landmarks", _landmark_tuple(self.landmarks))
        has_width = self.image_width is not None
        has_height = self.image_height is not None
        if has_width != has_height:
            fail("invalid_configuration")
        if self.coordinate_space == "cartesian_relative_v1" and (has_width or has_height):
            fail("invalid_configuration")
        if self.coordinate_space == "mediapipe_image_v1" and not (has_width and has_height):
            fail("invalid_configuration")
        if has_width:
            if type(self.image_width) is not int or type(self.image_height) is not int:
                fail("invalid_configuration")
            if not (1 <= self.image_width <= MAX_IMAGE_DIMENSION and 1 <= self.image_height <= MAX_IMAGE_DIMENSION):
                fail("invalid_configuration")
            object.__setattr__(self, "image_width", self.image_width)
            object.__setattr__(self, "image_height", self.image_height)
        if self.coordinate_space == "mediapipe_image_v1":
            factor = self.image_height / self.image_width
            converted = tuple(Landmark(point.x, point.y * factor, point.z) for point in self.landmarks)
        else:
            converted = self.landmarks
        wrist = converted[WRIST_INDEX]
        middle = converted[MIDDLE_MCP_INDEX]
        scale = sqrt((wrist.x - middle.x) ** 2 + (wrist.y - middle.y) ** 2 + (wrist.z - middle.z) ** 2)
        if scale < MIN_PALM_SCALE:
            fail("invalid_geometry")

    @property
    def palm_scale(self) -> float:
        converted = self.converted_landmarks()
        wrist = converted[WRIST_INDEX]
        middle = converted[MIDDLE_MCP_INDEX]
        return sqrt((wrist.x - middle.x) ** 2 + (wrist.y - middle.y) ** 2 + (wrist.z - middle.z) ** 2)

    def converted_landmarks(self) -> tuple[Landmark, ...]:
        if self.coordinate_space == "cartesian_relative_v1":
            return tuple(Landmark(point.x, point.y, point.z) for point in self.landmarks)
        factor = self.image_height / self.image_width  # type: ignore[operator]
        return tuple(Landmark(point.x, point.y * factor, point.z) for point in self.landmarks)

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "stream_id": self.stream_id,
            "frame_id": self.frame_id,
            "monotonic_ms": self.monotonic_ms,
            "coordinate_space": self.coordinate_space,
            "landmarks": [point.payload() for point in self.landmarks],
        }
        if self.coordinate_space == "mediapipe_image_v1":
            result["image_width"] = self.image_width
            result["image_height"] = self.image_height
        return result


def _frame_from_object(value: Any) -> Frame:
    if type(value) is not dict:
        fail("invalid_shape")
    coordinate_space = value.get("coordinate_space")
    expected = IMAGE_FRAME_FIELDS if coordinate_space == "mediapipe_image_v1" else FRAME_FIELDS
    mapping = require_exact_fields(value, expected)
    return Frame(
        schema_version=mapping["schema_version"],
        stream_id=mapping["stream_id"],
        frame_id=mapping["frame_id"],
        monotonic_ms=mapping["monotonic_ms"],
        coordinate_space=mapping["coordinate_space"],
        landmarks=tuple(Landmark.from_mapping(item) for item in mapping["landmarks"])
        if type(mapping["landmarks"]) in (list, tuple)
        else mapping["landmarks"],
        image_width=mapping.get("image_width"),
        image_height=mapping.get("image_height"),
    )


def parse_frame(value: bytes | str | dict[str, Any]) -> Frame:
    if isinstance(value, bytes):
        value = parse_json_bytes(value, limit=MAX_FRAME_BYTES)
    elif isinstance(value, str):
        from .validation import parse_json_text

        value = parse_json_text(value, limit=MAX_FRAME_BYTES)
    return _frame_from_object(value)


@dataclass(frozen=True, slots=True)
class FrameBatch:
    schema_version: str
    frames: tuple[Frame, ...]

    def __post_init__(self) -> None:
        if type(self.schema_version) is not str or self.schema_version != SCHEMA_VERSION:
            fail("unsupported_version")
        if type(self.frames) not in (list, tuple) or not (1 <= len(self.frames) <= MAX_BATCH_FRAMES):
            fail("invalid_shape")
        frames = tuple(self.frames)
        if not all(isinstance(frame, Frame) for frame in frames):
            fail("invalid_shape")
        first_stream = frames[0].stream_id
        if any(frame.stream_id != first_stream for frame in frames):
            fail("invalid_sequence")
        for previous, current in zip(frames, frames[1:]):
            if current.frame_id <= previous.frame_id or current.monotonic_ms <= previous.monotonic_ms:
                fail("invalid_sequence")
        object.__setattr__(self, "frames", frames)

    def payload(self) -> dict[str, Any]:
        return {"schema_version": self.schema_version, "frames": [frame.payload() for frame in self.frames]}


def parse_batch(value: bytes | str | dict[str, Any]) -> FrameBatch:
    if isinstance(value, bytes):
        value = parse_json_bytes(value, limit=MAX_BATCH_BYTES)
    elif isinstance(value, str):
        from .validation import parse_json_text

        value = parse_json_text(value, limit=MAX_BATCH_BYTES)
    mapping = require_exact_fields(value, {"schema_version", "frames"})
    frames_value = mapping["frames"]
    if type(frames_value) not in (list, tuple):
        fail("invalid_shape")
    return FrameBatch(
        schema_version=mapping["schema_version"],
        frames=tuple(_frame_from_object(item) for item in frames_value),
    )

