from __future__ import annotations

import pytest

from mudra_interact_core import Frame, InteractionConfig, Landmark, MudraValidationError, RecognitionSession
from mudra_interact_core.protocol import Recognition, RecognitionState


STREAM_ID = "123e4567-e89b-42d3-a456-426614174000"
OTHER_STREAM = "123e4567-e89b-42d3-a456-426614174002"


def frame(frame_id: int, now: int, gesture: str = "index") -> Frame:
    points = [Landmark(0.0, 0.0, 0.0) for _ in range(21)]
    points[9] = Landmark(0.0, 1.0, 0.0)
    points[4] = Landmark(0.0, 0.0, 0.0)
    points[8] = Landmark(1.0, 0.0, 0.0)
    points[12] = Landmark(1.0, 0.0, 0.0)
    points[16] = Landmark(1.0, 0.0, 0.0)
    if gesture == "index":
        points[8] = Landmark(0.2, 0.0, 0.0)
    elif gesture == "middle":
        points[12] = Landmark(0.2, 0.0, 0.0)
    elif gesture == "ring":
        points[16] = Landmark(0.2, 0.0, 0.0)
    else:
        raise AssertionError(gesture)
    return Frame("2.0.0", STREAM_ID, frame_id, now, "cartesian_relative_v1", tuple(points))


def other_stream_frame(frame_id: int, now: int) -> Frame:
    value = frame(frame_id, now)
    return Frame("2.0.0", OTHER_STREAM, value.frame_id, value.monotonic_ms, value.coordinate_space, value.landmarks)


def stable_session(**kwargs) -> RecognitionSession:
    session = RecognitionSession(STREAM_ID, **kwargs)
    session.observe(frame(1, 0))
    session.observe(frame(2, 50))
    result = session.observe(frame(3, 100))
    assert result.state is RecognitionState.STABLE
    return session


@pytest.mark.acceptance("E30")
def test_stable_requires_three_distinct_frames_and_one_hundred_ms() -> None:
    session = RecognitionSession(STREAM_ID)
    assert session.observe(frame(1, 0)).state is RecognitionState.CANDIDATE
    assert session.observe(frame(2, 50)).state is RecognitionState.CANDIDATE
    assert session.observe(frame(3, 100)).state is RecognitionState.STABLE


@pytest.mark.acceptance("E30")
@pytest.mark.parametrize("required", [2, 12])
def test_required_frame_boundaries_are_respected(required: int) -> None:
    session = RecognitionSession(STREAM_ID, required_frames=required)
    for index in range(required - 1):
        assert session.observe(frame(index + 1, index * 100)).state is RecognitionState.CANDIDATE
    assert session.observe(frame(required, (required - 1) * 100)).state is RecognitionState.STABLE


@pytest.mark.acceptance("E31")
def test_high_rate_frames_cannot_bypass_hold_and_memory_is_bounded() -> None:
    session = RecognitionSession(STREAM_ID, required_frames=3, minimum_hold_ms=100)
    for index in range(1, 30):
        result = session.observe(frame(index, index))
    assert result.state is RecognitionState.CANDIDATE
    assert "hold_incomplete" in result.uncertainties
    assert session.buffered_frames == 3
    assert session.streak_count == 29


@pytest.mark.acceptance("E32")
def test_uncertain_and_low_score_inputs_clear_the_streak() -> None:
    session = RecognitionSession(STREAM_ID)
    session.observe(frame(1, 0))
    session.observe(frame(2, 50))
    result = session.observe(frame(3, 100, "middle"))
    assert result.state is RecognitionState.UNCERTAIN
    assert result.uncertainties == ("gesture_changed",)
    assert session.streak_count == 1

    low = RecognitionSession(STREAM_ID, minimum_confidence=0.73)
    result = low.observe(frame(1, 0))
    assert result.state is RecognitionState.UNCERTAIN
    assert result.uncertainties == ("low_confidence",)
    assert low.streak_count == 0


@pytest.mark.acceptance("E33")
def test_sequence_watermarks_require_strict_ids_and_times() -> None:
    session = RecognitionSession(STREAM_ID)
    session.observe(frame(1, 10))
    for duplicate in (frame(1, 11), frame(2, 10)):
        with pytest.raises(MudraValidationError, match="invalid_sequence"):
            session.observe(duplicate)
    # The invalid attempts did not advance accepted sequence; a fresh frame works.
    assert session.observe(frame(2, 20)).state is RecognitionState.CANDIDATE


@pytest.mark.acceptance("E33")
def test_identical_points_are_allowed_when_frame_identity_is_distinct() -> None:
    session = RecognitionSession(STREAM_ID)
    session.observe(frame(1, 0))
    session.observe(frame(2, 50))
    assert session.observe(frame(3, 100)).state is RecognitionState.STABLE


@pytest.mark.acceptance("E34")
def test_gap_equality_continues_and_gap_above_limit_restarts() -> None:
    session = RecognitionSession(STREAM_ID)
    session.observe(frame(1, 0))
    session.observe(frame(2, 100))
    result = session.observe(frame(3, 350))
    assert result.state is RecognitionState.STABLE

    restarted = RecognitionSession(STREAM_ID)
    restarted.observe(frame(1, 0))
    restarted.observe(frame(2, 100))
    result = restarted.observe(frame(3, 351))
    assert result.state is RecognitionState.CANDIDATE
    assert "frame_gap" in result.uncertainties
    assert restarted.streak_count == 1


@pytest.mark.acceptance("E35")
def test_gesture_conflict_reports_uncertain_and_starts_new_streak() -> None:
    session = RecognitionSession(STREAM_ID)
    session.observe(frame(1, 0, "index"))
    result = session.observe(frame(2, 50, "middle"))
    assert result.state is RecognitionState.UNCERTAIN
    assert result.uncertainties == ("gesture_changed",)
    assert session.streak_count == 1
    session.observe(frame(3, 100, "middle"))
    assert session.observe(frame(4, 150, "middle")).state is RecognitionState.STABLE


@pytest.mark.acceptance("E35")
def test_method_or_catalogue_mismatch_cannot_be_promoted() -> None:
    session = RecognitionSession(STREAM_ID)
    with pytest.raises(MudraValidationError, match="invalid_shape"):
        session.observe(Recognition("contact_thumb_index", 0.72, RecognitionState.CANDIDATE))


@pytest.mark.acceptance("E36")
def test_scope_reset_stop_and_revoke_lifecycle() -> None:
    session = stable_session()
    with pytest.raises(MudraValidationError, match="scope_mismatch"):
        session.observe(other_stream_frame(4, 150))
    session.observe(frame(4, 150))
    session.reset()
    with pytest.raises(MudraValidationError, match="invalid_sequence"):
        session.observe(frame(4, 200))
    session.stop()
    with pytest.raises(MudraValidationError, match="invalid_state"):
        session.observe(frame(5, 300))


@pytest.mark.acceptance("E36")
def test_revoke_retains_sequence_and_requires_new_observation() -> None:
    session = stable_session()
    session.revoke()
    with pytest.raises(MudraValidationError, match="invalid_sequence"):
        session.observe(frame(3, 101))
    result = session.observe(frame(4, 200))
    assert result.state is RecognitionState.CANDIDATE


@pytest.mark.acceptance("E37")
def test_external_stable_result_cannot_be_fed_as_proof_and_sessions_are_isolated() -> None:
    session_a = stable_session()
    session_b = RecognitionSession(STREAM_ID)
    with pytest.raises(MudraValidationError):
        session_b.observe(session_a.current)
    assert session_b.streak_count == 0
    assert session_a.current.state is RecognitionState.STABLE

