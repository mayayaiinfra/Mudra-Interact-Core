"""Strict, bounded input validation shared by every public boundary."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .errors import MudraValidationError


SCHEMA_VERSION = "2.0.0"
CATALOG_VERSION = "2.0.0"
MAX_SAFE_INTEGER = 2**53 - 1
MAX_COORDINATE = 16.0
MIN_PALM_SCALE = 0.0001
MAX_IMAGE_DIMENSION = 16_384
MAX_JSON_DEPTH = 16
MAX_STRING_SCALARS = 1_024
MAX_FRAME_BYTES = 65_536
MAX_BATCH_BYTES = 1_048_576
MAX_EVENT_BYTES = 4_096
MAX_BATCH_FRAMES = 256


def fail(code: str) -> None:
    raise MudraValidationError(code)


def require_builtin_number(value: Any, *, code: str = "invalid_number") -> int | float:
    """Return a builtin finite number without invoking user conversion hooks."""

    if type(value) not in (int, float):
        fail("invalid_shape")
    if isinstance(value, float) and not math.isfinite(value):
        fail(code)
    return value


def require_coordinate(value: Any) -> float:
    number = require_builtin_number(value)
    if abs(number) > MAX_COORDINATE:
        fail("invalid_geometry")
    # The bound is checked before conversion, so huge integers cannot overflow.
    converted = float(number)
    if not math.isfinite(converted) or abs(converted) > MAX_COORDINATE:
        fail("invalid_geometry")
    return converted


def require_bounded_integer(
    value: Any,
    *,
    minimum: int = 0,
    maximum: int = MAX_SAFE_INTEGER,
    code: str = "invalid_shape",
) -> int:
    if type(value) is not int or value < minimum or value > maximum:
        fail(code)
    return value


def require_finite_float(
    value: Any,
    *,
    minimum: float = 0.0,
    maximum: float = 1.0,
    code: str = "invalid_configuration",
) -> float:
    if type(value) not in (int, float):
        fail(code)
    converted = float(value)
    if not math.isfinite(converted) or converted < minimum or converted > maximum:
        fail(code)
    return converted


def require_canonical_uuid(value: Any, *, nullable: bool = False) -> str | None:
    if nullable and value is None:
        return None
    if type(value) is not str:
        fail("invalid_shape")
    if len(value) != 36 or value != value.lower():
        fail("invalid_shape")
    try:
        parsed = UUID(value)
    except (ValueError, AttributeError):
        fail("invalid_shape")
    if str(parsed) != value:
        fail("invalid_shape")
    if parsed.version not in {1, 2, 3, 4, 5, 6, 7, 8} or parsed.variant != "specified in RFC 4122":
        fail("invalid_shape")
    return value


def _reject_surrogates_and_bound_strings(value: Any, *, depth: int = 0) -> None:
    if depth > MAX_JSON_DEPTH:
        fail("invalid_json")
    if isinstance(value, str):
        if len(value) > MAX_STRING_SCALARS or any(0xD800 <= ord(char) <= 0xDFFF for char in value):
            fail("invalid_json")
        return
    if isinstance(value, list):
        for item in value:
            _reject_surrogates_and_bound_strings(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates_and_bound_strings(key, depth=depth + 1)
            _reject_surrogates_and_bound_strings(item, depth=depth + 1)


def _scan_depth(data: bytes, *, maximum: int = MAX_JSON_DEPTH) -> None:
    """Scan JSON nesting without treating escaped brackets inside strings as structure."""

    depth = 0
    in_string = False
    escaped = False
    for byte in data:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:  # backslash
                escaped = True
            elif byte == 0x22:  # quote
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):  # {[
            depth += 1
            if depth > maximum:
                fail("invalid_json")
        elif byte in (0x7D, 0x5D):  # }]
            depth -= 1
            if depth < 0:
                fail("invalid_json")
    if in_string or escaped or depth != 0:
        fail("invalid_json")


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            fail("invalid_json")
        result[key] = value
    return result


def _finite_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        fail("invalid_json")
    return parsed


def _invalid_constant(_value: str) -> Any:
    fail("invalid_json")


def parse_json_bytes(data: bytes, *, limit: int) -> Any:
    """Decode one bounded JSON document with no coercion or remote behavior."""

    if type(data) is not bytes:
        fail("invalid_json")
    if len(data) > limit:
        fail("input_too_large")
    if data.startswith(b"\xef\xbb\xbf"):
        fail("invalid_json")
    _scan_depth(data)
    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_pairs_no_duplicates,
            parse_float=_finite_float,
            parse_constant=_invalid_constant,
        )
    except MudraValidationError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError, OverflowError):
        fail("invalid_json")
    _reject_surrogates_and_bound_strings(value)
    return value


def parse_json_text(text: str, *, limit: int) -> Any:
    if type(text) is not str:
        fail("invalid_json")
    try:
        data = text.encode("utf-8", errors="strict")
    except UnicodeError:
        fail("invalid_json")
    return parse_json_bytes(data, limit=limit)


def require_exact_fields(value: Any, fields: set[str]) -> dict[str, Any]:
    if type(value) is not dict or set(value) != fields:
        fail("invalid_shape")
    return value


def require_finite_json_number(value: Any) -> int | float:
    return require_builtin_number(value, code="invalid_number")


@dataclass(frozen=True, slots=True)
class InteractionConfig:
    """Validated recognizer/session limits; values are never silently clipped."""

    contact_threshold: float = 0.34
    required_frames: int = 3
    minimum_confidence: float = 0.6
    minimum_hold_ms: int = 100
    maximum_gap_ms: int = 250

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "contact_threshold",
            require_finite_float(self.contact_threshold, minimum=0.05, maximum=0.75),
        )
        object.__setattr__(
            self,
            "required_frames",
            require_bounded_integer(self.required_frames, minimum=2, maximum=12, code="invalid_configuration"),
        )
        object.__setattr__(
            self,
            "minimum_confidence",
            require_finite_float(self.minimum_confidence, minimum=0.0, maximum=1.0),
        )
        object.__setattr__(
            self,
            "minimum_hold_ms",
            require_bounded_integer(self.minimum_hold_ms, minimum=0, maximum=2_000, code="invalid_configuration"),
        )
        object.__setattr__(
            self,
            "maximum_gap_ms",
            require_bounded_integer(self.maximum_gap_ms, minimum=1, maximum=1_000, code="invalid_configuration"),
        )

