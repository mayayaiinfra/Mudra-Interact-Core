"""Safe public errors for Mudra Interact Core.

The error code is the complete public message.  Input values, paths and
exception text are deliberately never included.
"""

from __future__ import annotations


SAFE_ERROR_CODES = frozenset(
    {
        "invalid_json",
        "input_too_large",
        "invalid_shape",
        "invalid_number",
        "invalid_geometry",
        "unsupported_version",
        "invalid_configuration",
        "invalid_sequence",
        "invalid_state",
        "consent_required",
        "confirmation_required",
        "stale_confirmation",
        "scope_mismatch",
        "catalog_invalid",
        "unsupported_platform",
        "input_unavailable",
        "internal_error",
    }
)


class MudraValidationError(ValueError):
    """A deterministic, non-sensitive validation failure."""

    __slots__ = ("code",)

    def __init__(self, code: str) -> None:
        if code not in SAFE_ERROR_CODES:
            code = "internal_error"
        self.code = code
        super().__init__(code)

    def __str__(self) -> str:
        return self.code

    def __repr__(self) -> str:
        return f"MudraValidationError({self.code!r})"

