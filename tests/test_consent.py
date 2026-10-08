from __future__ import annotations

import pytest

from mudra_interact_core import MudraValidationError, RecognitionSession
from mudra_interact_core.protocol import InteractionParty

from test_session import STREAM_ID, frame, stable_session


@pytest.mark.acceptance("E38")
@pytest.mark.parametrize(
    "consent,participant,code",
    [(False, True, "consent_required"), (True, False, "confirmation_required"), ("true", True, "consent_required"),
     (True, 1, "confirmation_required")],
)
def test_confirmation_requires_exact_true_booleans(consent, participant, code: str) -> None:
    session = stable_session()
    with pytest.raises(MudraValidationError, match=code):
        session.confirm(consent, participant, 100)
    expected_emit_code = "consent_required" if code == "consent_required" else "confirmation_required"
    with pytest.raises(MudraValidationError, match=expected_emit_code):
        session.emit_event(now_ms=100)


@pytest.mark.acceptance("E38")
@pytest.mark.acceptance("E40")
@pytest.mark.parametrize("bad_time", [True, "100", 100.0, -1, 9_007_199_254_740_992])
@pytest.mark.parametrize("prior_grant", [False, True])
def test_invalid_confirmation_time_revokes_stable_result_and_requires_fresh_frames(
    bad_time, prior_grant: bool,
) -> None:
    session = stable_session()
    if prior_grant:
        session.confirm(True, True, 100)
    with pytest.raises(MudraValidationError, match="invalid_sequence"):
        session.confirm(True, True, bad_time)

    assert session.current.state.value == "uncertain"
    assert session.last_frame_id == 3
    assert session.last_frame_time == 100
    assert session.streak_count == 0
    with pytest.raises(MudraValidationError, match="confirmation_required"):
        session.emit_event(now_ms=100)
    with pytest.raises(MudraValidationError, match="confirmation_required"):
        session.confirm(True, True, 100)

    session.observe(frame(4, 150))
    session.observe(frame(5, 200))
    recovered = session.observe(frame(6, 250))
    assert recovered.state.value == "stable"
    session.confirm(True, True, 250)
    assert session.emit_event(now_ms=250).direction == "human_to_agent"


@pytest.mark.acceptance("E38")
def test_both_true_and_current_stable_are_required_for_every_sender() -> None:
    session = stable_session()
    session.confirm(True, True, 100)
    event = session.emit_event(sender=InteractionParty.AGENT, recipient=InteractionParty.HUMAN, now_ms=100)
    assert event.direction == "agent_to_human"


@pytest.mark.acceptance("E39")
def test_confirmation_is_invalidated_by_a_later_observation_reset_or_revoke() -> None:
    session = stable_session()
    session.confirm(True, True, 100)
    session.observe(frame(4, 150))
    with pytest.raises(MudraValidationError, match="consent_required"):
        session.emit_event(now_ms=150)

    session = stable_session()
    session.confirm(True, True, 100)
    session.reset()
    with pytest.raises(MudraValidationError, match="consent_required"):
        session.emit_event(now_ms=100)

    session = stable_session()
    session.confirm(True, True, 100)
    session.revoke()
    with pytest.raises(MudraValidationError, match="consent_required"):
        session.emit_event(now_ms=100)


@pytest.mark.acceptance("E40")
def test_confirmation_age_and_monotonic_clock_boundaries() -> None:
    session = stable_session()
    session.confirm(True, True, 100)
    with pytest.raises(MudraValidationError, match="stale_confirmation"):
        session.emit_event(now_ms=5101)

    session = stable_session()
    session.confirm(True, True, 100)
    event = session.emit_event(now_ms=5100)
    assert event.payload()["consent_confirmed"] is True

    session = stable_session()
    with pytest.raises(MudraValidationError, match="invalid_sequence"):
        session.confirm(True, True, 99)


@pytest.mark.acceptance("E41")
def test_one_emission_per_confirmed_revision() -> None:
    session = stable_session()
    session.confirm(True, True, 100)
    session.emit_event(now_ms=100)
    with pytest.raises(MudraValidationError, match="consent_required"):
        session.emit_event(now_ms=100)
    with pytest.raises(MudraValidationError, match="stale_confirmation"):
        session.confirm(True, True, 100)


@pytest.mark.acceptance("E42")
def test_invalid_emit_arguments_consume_grant_and_require_fresh_observation() -> None:
    session = stable_session()
    session.confirm(True, True, 100)
    with pytest.raises(MudraValidationError):
        session.emit_event(sender="human", now_ms=100)
    with pytest.raises(MudraValidationError, match="consent_required"):
        session.emit_event(now_ms=100)
    session.observe(frame(4, 150))
    session.observe(frame(5, 200))
    session.observe(frame(6, 250))
    session.confirm(True, True, 250)
    assert session.emit_event(now_ms=250).direction == "human_to_agent"
