"""MI-09 design-only adapter contract checks."""

from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "docs" / "ADAPTER_SPEC.md"


def _spec() -> str:
    return SPEC.read_text(encoding="utf-8")


@pytest.mark.acceptance("E85")
def test_design_has_pinned_assets_and_keeps_camera_out_of_core() -> None:
    text = _spec()
    assert "**Status: DESIGN ONLY.**" in text
    for term in ("SHA-256", "SPDX", "NOTICE", "approved", "public core package"):
        assert term in text
    assert "no camera dependency is added" in text.lower()
    assert "unimplemented" in text.lower()


@pytest.mark.acceptance("E86")
def test_state_table_closes_lifecycle_and_late_callbacks() -> None:
    text = _spec()
    for term in (
        "Start", "denied", "Stop", "Revoke", "late model callback", "Device/track switch",
        "Hand loss", "Tab/app hidden", "drops queued frames", "discarded, never emitted",
        "generation counter",
    ):
        assert term.lower() in text.lower()
    assert "never implicitly start" in text
    assert "do not repeat the last stable gesture" in text.lower()


@pytest.mark.acceptance("E87")
def test_identity_geometry_and_duplicate_guards_are_explicit() -> None:
    text = _spec()
    for term in (
        "track_id", "frame_sequence", "capture_time_monotonic_ns", "model_revision",
        "aspect-ratio", "rotation", "mirror", "wall-clock", "duplicate guard",
        "duplicate or regressed identity", "duplicate-frame hold bypass",
    ):
        assert term.lower() in text.lower()


@pytest.mark.acceptance("E88")
def test_failure_offline_queue_telemetry_and_byok_boundaries_are_defined() -> None:
    text = _spec().lower()
    for term in (
        "fixed (recommended maximum two entries)", "latest bounded frame", "model load failure",
        "offline_unavailable", "cold-cache", "counters", "fixed error codes",
        "never sends images", "byok capability probe", "non-camera path",
    ):
        assert term in text


@pytest.mark.acceptance("E89")
def test_real_proof_and_accessible_alternative_are_not_fabricated() -> None:
    text = _spec().lower()
    for term in (
        "required proof before implementation status changes", "browser/device permission",
        "real model inference", "accessibility review", "community and language review",
        "asset and model/data licence review", "keyboard/pointer alternative",
        "remains design", "no recognition", "accuracy",
    ):
        assert term in text
    assert "fake" not in text
