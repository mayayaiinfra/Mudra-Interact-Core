"""Bounded temporal recognition, consent and event emission lifecycle."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from .errors import MudraValidationError
from .frame import Frame, parse_frame
from .protocol import InteractionParty, MudraEvent, PrivacyMode, Recognition, RecognitionState
from .recognition import LandmarkRuleRecognizer
from .validation import (
    CATALOG_VERSION,
    MAX_SAFE_INTEGER,
    SCHEMA_VERSION,
    InteractionConfig,
    fail,
    require_bounded_integer,
    require_canonical_uuid,
)


@dataclass(frozen=True, slots=True)
class _Confirmation:
    stream_id: str
    frame_id: int
    revision: int
    conversation_id: str | None
    project_id: str | None
    method: str
    catalog_version: str
    frame_time: int


def _uncertain(
    code: str,
    *,
    observations: tuple[str, ...] = (),
) -> Recognition:
    return Recognition(
        gesture_id="unknown",
        confidence=0.0,
        state=RecognitionState.UNCERTAIN,
        method="contact_rules_v2",
        observations=observations,
        uncertainties=(code,),
        catalog_version=CATALOG_VERSION,
    )


def _with_uncertainty(result: Recognition, code: str) -> Recognition:
    codes = tuple(dict.fromkeys((*result.uncertainties, code)))
    return Recognition(
        gesture_id=result.gesture_id,
        confidence=result.confidence,
        state=result.state,
        method=result.method,
        observations=result.observations,
        uncertainties=codes,
        catalog_version=result.catalog_version,
    )


class RecognitionSession:
    """Single-owner session for one stream and one optional action scope."""

    _IMMUTABLE_FIELDS = frozenset({"stream_id", "conversation_id", "project_id", "config", "recognizer"})

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._IMMUTABLE_FIELDS and hasattr(self, name):
            fail("invalid_configuration")
        object.__setattr__(self, name, value)

    def __init__(
        self,
        stream_id: str,
        *,
        conversation_id: str | None = None,
        project_id: str | None = None,
        recognizer: LandmarkRuleRecognizer | None = None,
        config: InteractionConfig | None = None,
        required_frames: int | None = None,
        minimum_confidence: float | None = None,
        minimum_hold_ms: int | None = None,
        maximum_gap_ms: int | None = None,
    ) -> None:
        canonical_stream = require_canonical_uuid(stream_id)
        canonical_conversation = require_canonical_uuid(conversation_id, nullable=True)
        canonical_project = require_canonical_uuid(project_id, nullable=True)
        overrides = (required_frames, minimum_confidence, minimum_hold_ms, maximum_gap_ms)
        if config is not None:
            if type(config) is not InteractionConfig or any(value is not None for value in overrides):
                fail("invalid_configuration")
            selected_config = config
        else:
            selected_config = InteractionConfig(
                required_frames=3 if required_frames is None else required_frames,
                minimum_confidence=0.6 if minimum_confidence is None else minimum_confidence,
                minimum_hold_ms=100 if minimum_hold_ms is None else minimum_hold_ms,
                maximum_gap_ms=250 if maximum_gap_ms is None else maximum_gap_ms,
            )
        if recognizer is None:
            selected_recognizer = LandmarkRuleRecognizer(config=selected_config)
        else:
            if type(recognizer) is not LandmarkRuleRecognizer:
                fail("invalid_configuration")
            if recognizer.config != selected_config:
                fail("invalid_configuration")
            selected_recognizer = recognizer
        self.stream_id = canonical_stream
        self.conversation_id = canonical_conversation
        self.project_id = canonical_project
        self.config = selected_config
        self.recognizer = selected_recognizer
        self._recent: deque[Recognition] = deque(maxlen=selected_config.required_frames)
        self._last_frame_id: int | None = None
        self._last_frame_time: int | None = None
        self._last_operation_time: int | None = None
        self._streak_start: int | None = None
        self._streak_count = 0
        self._last_candidate_time: int | None = None
        self._revision = 0
        self._current: Recognition = _uncertain("insufficient_frames")
        self._confirmation: _Confirmation | None = None
        self._consent_granted = False
        self._last_denial: str | None = None
        self._consumed_revision: int | None = None
        self._stopped = False
        self._revoked = False

    @property
    def last_frame_id(self) -> int | None:
        return self._last_frame_id

    @property
    def last_frame_time(self) -> int | None:
        return self._last_frame_time

    @property
    def revision(self) -> int:
        return self._revision

    @property
    def current(self) -> Recognition:
        return Recognition(
            gesture_id=self._current.gesture_id,
            confidence=self._current.confidence,
            state=self._current.state,
            method=self._current.method,
            observations=self._current.observations,
            uncertainties=self._current.uncertainties,
            catalog_version=self._current.catalog_version,
        )

    @property
    def streak_count(self) -> int:
        return self._streak_count

    @property
    def buffered_frames(self) -> int:
        return len(self._recent)

    def _ensure_running(self) -> None:
        if self._stopped:
            fail("invalid_state")

    def _clear_confirmation(self) -> None:
        self._confirmation = None
        self._consent_granted = False

    def _clear_streak(self, reason: str = "insufficient_frames") -> None:
        if reason not in {
            "unsupported_pattern",
            "ambiguous_contacts",
            "posture_unverified",
            "low_confidence",
            "insufficient_frames",
            "hold_incomplete",
            "frame_gap",
            "gesture_changed",
        }:
            reason = "insufficient_frames"
        self._recent.clear()
        self._streak_start = None
        self._streak_count = 0
        self._last_candidate_time = None
        self._current = _uncertain(reason)
        self._revision += 1

    def _operation_time(self, now_ms: Any, *, allow_equal: bool) -> int:
        if type(now_ms) is not int or now_ms < 0 or now_ms > MAX_SAFE_INTEGER:
            fail("invalid_sequence")
        if self._last_operation_time is not None:
            if now_ms < self._last_operation_time or (not allow_equal and now_ms == self._last_operation_time):
                self._clear_confirmation()
                self._clear_streak("stale_confirmation")
                fail("invalid_sequence")
        self._last_operation_time = now_ms
        return now_ms

    def observe(self, frame: Frame | bytes | str | dict[str, Any]) -> Recognition:
        """Accept one validated frame and return a detached local result."""

        self._ensure_running()
        # A new observation invalidates a previous grant before any parse work.
        self._clear_confirmation()
        self._last_denial = None
        self._consumed_revision = None
        try:
            parsed = frame if isinstance(frame, Frame) else parse_frame(frame)
            if parsed.stream_id != self.stream_id:
                self._clear_streak("scope_mismatch")
                fail("scope_mismatch")
            if self._last_frame_id is not None and parsed.frame_id <= self._last_frame_id:
                self._clear_streak("invalid_sequence")
                fail("invalid_sequence")
            if self._last_frame_time is not None and parsed.monotonic_ms <= self._last_frame_time:
                self._clear_streak("invalid_sequence")
                fail("invalid_sequence")
            if self._last_operation_time is not None and parsed.monotonic_ms <= self._last_operation_time:
                self._clear_streak("invalid_sequence")
                fail("invalid_sequence")
            result = self.recognizer.recognize(parsed)
            if result.method != "contact_rules_v2" or result.catalog_version != CATALOG_VERSION:
                self._clear_streak("invalid_state")
                fail("invalid_state")
            # Advance sequence and operation watermarks only after parse and
            # recognition validation have completed.
            self._last_frame_id = parsed.frame_id
            self._last_frame_time = parsed.monotonic_ms
            self._last_operation_time = parsed.monotonic_ms
        except MudraValidationError:
            self._clear_confirmation()
            self._clear_streak("invalid_sequence")
            raise

        if self._revoked:
            self._revoked = False
        if result.state is not RecognitionState.CANDIDATE:
            self._clear_streak(result.uncertainties[0] if result.uncertainties else "unsupported_pattern")
            self._current = result
            self._revision += 1
            return self.current
        if result.confidence < self.config.minimum_confidence:
            self._clear_streak("low_confidence")
            self._current = _uncertain("low_confidence", observations=result.observations)
            return self.current

        gap = None if self._streak_start is None else parsed.monotonic_ms - self._last_candidate_time
        prior = self._recent[-1] if self._recent else None
        changed = prior is not None and prior.gesture_id != result.gesture_id
        if gap is not None and gap > self.config.maximum_gap_ms:
            self._recent.clear()
            self._streak_start = parsed.monotonic_ms
            self._streak_count = 0
            prior = None
        elif changed:
            # The conflicting frame becomes frame one of the new candidate, but
            # the externally returned result records the conflict.
            self._recent.clear()
            self._streak_start = parsed.monotonic_ms
            self._streak_count = 0
        if self._streak_start is None:
            self._streak_start = parsed.monotonic_ms
        self._recent.append(result)
        self._streak_count += 1
        self._last_candidate_time = parsed.monotonic_ms
        if changed:
            self._current = _uncertain("gesture_changed", observations=result.observations)
            self._revision += 1
            return self.current
        if gap is not None and gap > self.config.maximum_gap_ms:
            result = _with_uncertainty(result, "frame_gap")
        if self._streak_count < self.config.required_frames:
            result = _with_uncertainty(result, "insufficient_frames")
            self._current = result
        elif parsed.monotonic_ms - self._streak_start < self.config.minimum_hold_ms:
            result = _with_uncertainty(result, "hold_incomplete")
            self._current = result
        else:
            confidence = sum(item.confidence for item in self._recent) / len(self._recent)
            self._current = Recognition(
                gesture_id=result.gesture_id,
                confidence=confidence,
                state=RecognitionState.STABLE,
                method="contact_rules_v2",
                observations=result.observations,
                uncertainties=result.uncertainties,
                catalog_version=CATALOG_VERSION,
            )
        self._revision += 1
        return self.current

    def confirm(self, consent_confirmed: Any, participant_confirmed: Any, now_ms: Any) -> None:
        """Bind a real UI confirmation to the latest stable revision."""

        self._ensure_running()
        self._clear_confirmation()
        self._last_denial = None
        now = self._operation_time(now_ms, allow_equal=True)
        if self._consumed_revision == self._revision:
            self._last_denial = "confirmation"
            fail("stale_confirmation")
        if type(consent_confirmed) is not bool or consent_confirmed is not True:
            self._last_denial = "consent"
            self._clear_streak("consent_required")
            fail("consent_required")
        if type(participant_confirmed) is not bool or participant_confirmed is not True:
            self._last_denial = "confirmation"
            self._clear_streak("confirmation_required")
            fail("confirmation_required")
        if self._current.state is not RecognitionState.STABLE or self._last_frame_time is None:
            self._last_denial = "confirmation"
            fail("confirmation_required")
        if now < self._last_frame_time or now > self._last_frame_time + 5_000:
            self._last_denial = "confirmation"
            self._clear_streak("stale_confirmation")
            fail("stale_confirmation")
        self._confirmation = _Confirmation(
            stream_id=self.stream_id,
            frame_id=self._last_frame_id,  # type: ignore[arg-type]
            revision=self._revision,
            conversation_id=self.conversation_id,
            project_id=self.project_id,
            method=self._current.method,
            catalog_version=self._current.catalog_version,
            frame_time=self._last_frame_time,
        )
        self._consent_granted = True

    def emit_event(
        self,
        *,
        sender: InteractionParty = InteractionParty.HUMAN,
        recipient: InteractionParty = InteractionParty.AGENT,
        now_ms: Any,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> MudraEvent:
        """Consume the grant before validation and return one immutable event."""

        self._ensure_running()
        grant = self._confirmation
        if grant is None or not self._consent_granted:
            if self._last_denial == "confirmation":
                fail("confirmation_required")
            fail("consent_required")
            fail("confirmation_required")
        # Consumption is intentionally first: all later failures require new
        # observations and a new confirmation.
        self._clear_confirmation()
        self._consumed_revision = grant.revision
        self._last_denial = None
        now = self._operation_time(now_ms, allow_equal=True)
        if now < grant.frame_time or now > grant.frame_time + 5_000:
            self._clear_streak("stale_confirmation")
            fail("stale_confirmation")
        if type(sender) is not InteractionParty or type(recipient) is not InteractionParty:
            fail("invalid_shape")
        if self._current.state is not RecognitionState.STABLE or self._revision != grant.revision:
            fail("stale_confirmation")
        if event_id is None:
            event_id = str(uuid4())
        else:
            require_canonical_uuid(event_id)
        if occurred_at is None:
            from datetime import UTC, datetime

            occurred_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        event = MudraEvent(
            recognition=self._current,
            sender=sender,
            recipient=recipient,
            privacy_mode=PrivacyMode.EVENT_ONLY,
            event_id=event_id,
            occurred_at=occurred_at,
            conversation_id=self.conversation_id,
            project_id=self.project_id,
            consent_confirmed=True,
            participant_confirmed=True,
            metadata={},
        )
        # Build bytes before returning so a size/serialization failure also
        # consumes the grant, with no ambiguous retry.
        event.to_bytes()
        return event

    def reset(self) -> None:
        self._ensure_running()
        self._clear_confirmation()
        self._last_denial = None
        self._clear_streak()

    def revoke(self) -> None:
        self._ensure_running()
        self._clear_confirmation()
        self._last_denial = "consent"
        self._clear_streak("consent_required")
        self._revoked = True

    def stop(self) -> None:
        self._clear_confirmation()
        self._clear_streak()
        self._stopped = True


__all__ = ["RecognitionSession"]

