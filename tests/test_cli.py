from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

import pytest

from mudra_interact_core.cli import main


ROOT = Path(__file__).resolve().parents[1]
STREAM_ID = "123e4567-e89b-42d3-a456-426614174000"
EVENT_ID = "123e4567-e89b-42d3-a456-426614174001"


def _frame(frame_id: int = 1, monotonic_ms: int = 0, *, gesture: str = "index") -> dict[str, object]:
    points = [{"x": 0.0, "y": 0.0, "z": 0.0} for _ in range(21)]
    points[9] = {"x": 0.0, "y": 1.0, "z": 0.0}
    points[4] = {"x": 0.0, "y": 0.0, "z": 0.0}
    points[8] = {"x": 1.0, "y": 0.0, "z": 0.0}
    points[12] = {"x": 1.0, "y": 0.0, "z": 0.0}
    points[16] = {"x": 1.0, "y": 0.0, "z": 0.0}
    if gesture == "index":
        points[8] = {"x": 0.2, "y": 0.0, "z": 0.0}
    elif gesture == "middle":
        points[12] = {"x": 0.2, "y": 0.0, "z": 0.0}
    elif gesture == "ambiguous":
        points[8] = {"x": 0.2, "y": 0.0, "z": 0.0}
        points[12] = {"x": 0.2, "y": 0.0, "z": 0.0}
    else:
        raise AssertionError(gesture)
    return {
        "schema_version": "2.0.0",
        "stream_id": STREAM_ID,
        "frame_id": frame_id,
        "monotonic_ms": monotonic_ms,
        "coordinate_space": "cartesian_relative_v1",
        "landmarks": points,
    }


def _batch(*, gesture: str = "index", times: tuple[int, ...] = (0, 50, 100)) -> dict[str, object]:
    return {"schema_version": "2.0.0", "frames": [_frame(i, time, gesture=gesture) for i, time in enumerate(times, 1)]}


def _write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _invoke(capsys: pytest.CaptureFixture[str], args: list[str]) -> tuple[int, str, str]:
    code = main(args)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


@pytest.mark.acceptance("E45")
def test_recognize_reports_candidate_and_real_batch_stability(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    frame_path = _write_json(tmp_path / "frame.json", _frame())
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(frame_path)])
    assert code == 0 and stderr == ""
    candidate = json.loads(stdout)
    assert candidate["schema_version"] == "2.0.0"
    assert candidate["recognition"]["state"] == "candidate"
    assert candidate["reason_code"] == "insufficient_frames"

    batch_path = _write_json(tmp_path / "batch.json", _batch())
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(batch_path), "--stabilize"])
    assert code == 0 and stderr == ""
    assert json.loads(stdout)["recognition"]["state"] == "stable"

    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(frame_path), "--stabilize"])
    assert code == 0 and stderr == ""
    assert json.loads(stdout)["recognition"]["state"] != "stable"


@pytest.mark.acceptance("E46")
def test_event_requires_both_explicit_flags_and_emits_one_event(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = _write_json(tmp_path / "batch.json", _batch())
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(path), "--stabilize", "--emit-event"])
    assert code == 3 and stdout == ""
    assert json.loads(stderr) == {"error": {"code": "consent_required"}}
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(path), "--stabilize", "--emit-event", "--consent"])
    assert code == 3 and stdout == ""
    assert json.loads(stderr) == {"error": {"code": "confirmation_required"}}
    code, stdout, stderr = _invoke(
        capsys,
        ["recognize", "--input", str(path), "--stabilize", "--emit-event", "--consent", "--confirm", "--sender", "agent", "--recipient", "human"],
    )
    assert code == 0 and stderr == ""
    event = json.loads(stdout)
    assert set(event) == {
        "schema_version", "event_id", "occurred_at", "sender", "recipient", "direction",
        "privacy_mode", "consent_confirmed", "participant_confirmed", "conversation_id",
        "project_id", "recognition", "raw_media_included", "raw_landmarks_included",
    }
    assert event["direction"] == "agent_to_human"


@pytest.mark.acceptance("E47")
def test_late_batch_failure_has_no_partial_output_and_ambiguous_event_is_denied(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    bad = _batch()
    bad["frames"][-1]["unknown"] = True  # type: ignore[index]
    bad_path = _write_json(tmp_path / "bad.json", bad)
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(bad_path), "--stabilize"])
    assert code == 2 and stdout == "" and json.loads(stderr)["error"]["code"] == "invalid_shape"

    ambiguous_path = _write_json(tmp_path / "ambiguous.json", _batch(gesture="ambiguous"))
    code, stdout, stderr = _invoke(
        capsys,
        ["recognize", "--input", str(ambiguous_path), "--stabilize", "--emit-event", "--consent", "--confirm"],
    )
    assert code == 3 and stdout == "" and json.loads(stderr)["error"]["code"] == "confirmation_required"


@pytest.mark.acceptance("E48")
def test_validate_event_is_bounded_and_never_echoes_candidate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    event = {
        "schema_version": "2.0.0",
        "event_id": EVENT_ID,
        "occurred_at": "2026-10-07T00:00:00.000000Z",
        "sender": "human",
        "recipient": "agent",
        "direction": "human_to_agent",
        "privacy_mode": "event_only",
        "consent_confirmed": True,
        "participant_confirmed": True,
        "conversation_id": None,
        "project_id": None,
        "recognition": {
            "gesture_id": "contact_thumb_index", "confidence": 0.72, "state": "stable",
            "method": "contact_rules_v2", "catalog_version": "2.0.0",
            "observation_codes": ["thumb_index_contact"], "uncertainty_codes": ["posture_unverified"],
        },
        "raw_media_included": False,
        "raw_landmarks_included": False,
    }
    valid = _write_json(tmp_path / "event.json", event)
    code, stdout, stderr = _invoke(capsys, ["validate-event", "--input", str(valid)])
    assert code == 0 and stderr == ""
    assert json.loads(stdout) == {"schema_version": "2.0.0", "valid": True}
    invalid = dict(event)
    invalid["schema_version"] = "1.0"
    invalid_path = _write_json(tmp_path / "invalid.json", invalid)
    code, stdout, stderr = _invoke(capsys, ["validate-event", "--input", str(invalid_path)])
    assert code == 2 and stdout == "" and "1.0" not in stderr


@pytest.mark.acceptance("E49")
def test_input_file_boundary_rejects_nonlocal_and_nonregular_paths(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for raw in ("-", "https://example.invalid/frame.json", "\\\\server\\share\\frame.json"):
        code, stdout, stderr = _invoke(capsys, ["recognize", "--input", raw])
        assert code == 4 and stdout == "" and len(stderr.encode()) <= 512
    directory = tmp_path / "directory"
    directory.mkdir()
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(directory)])
    assert code == 4 and stdout == "" and stderr
    missing = tmp_path / "missing.json"
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(missing)])
    assert code == 4 and stdout == "" and stderr
    regular = _write_json(tmp_path / "regular.json", _frame())
    if hasattr(os, "symlink"):
        link = tmp_path / "link.json"
        try:
            os.symlink(regular, link)
        except OSError:
            link = None
        if link is not None:
            code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(link)])
            assert code == 4 and stdout == ""


@pytest.mark.acceptance("E50")
def test_exit_classes_and_diagnostics_are_bounded(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    valid = _write_json(tmp_path / "frame.json", _frame())
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(valid)])
    assert code == 0 and stdout and stderr == ""
    code, stdout, stderr = _invoke(capsys, ["recognize", "--unexpected", "secret-path"])
    assert code == 2 and stdout == "" and len(stderr.encode()) <= 512 and "secret-path" not in stderr
    bad = _write_json(tmp_path / "bad.json", {"not": "a frame"})
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(bad)])
    assert code == 2 and stdout == "" and "Traceback" not in stderr
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(valid), "--emit-event"])
    assert code == 2 and stdout == ""  # usage: --emit-event requires --stabilize

    def interrupted(_args: object) -> bytes:
        raise KeyboardInterrupt

    monkeypatch.setattr("mudra_interact_core.cli._run_recognize", interrupted)
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(valid)])
    assert code == 130 and stdout == "" and "Traceback" not in stderr


@pytest.mark.acceptance("E51")
def test_broken_and_partial_output_are_nonzero_without_retry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write_json(tmp_path / "frame.json", _frame())

    class Broken:
        def write(self, _value: object) -> int:
            raise BrokenPipeError

        def flush(self) -> None:
            return None

    class Partial:
        def write(self, value: bytes) -> int:
            return max(0, len(value) - 1)

        def flush(self) -> None:
            return None

    monkeypatch.setattr(sys, "stdout", Broken())
    assert main(["recognize", "--input", str(path)]) == 4
    monkeypatch.setattr(sys, "stdout", Partial())
    assert main(["recognize", "--input", str(path)]) == 4


@pytest.mark.acceptance("E52")
def test_module_entrypoint_shorthand_help_and_version_parity(tmp_path: Path) -> None:
    path = _write_json(tmp_path / "frame.json", _frame())
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    module = subprocess.run([sys.executable, "-m", "mudra_interact_core", "--input", str(path)], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    launcher_name = "mudra-interact.exe" if os.name == "nt" else "mudra-interact"
    launcher = Path(sys.executable).with_name(launcher_name)
    assert launcher.is_file()
    script = subprocess.run([str(launcher), "--input", str(path)], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    assert module.returncode == script.returncode == 0
    assert json.loads(module.stdout) == json.loads(script.stdout)
    assert subprocess.run([sys.executable, "-m", "mudra_interact_core", "--help"], cwd=ROOT, env=environment, capture_output=True, text=True, check=False).returncode == 0
    assert subprocess.run([sys.executable, "-m", "mudra_interact_core", "--version"], cwd=ROOT, env=environment, capture_output=True, text=True, check=False).stdout.strip() == "0.4.1"


@pytest.mark.acceptance("E53")
def test_preliminary_wheel_owns_imports_outside_checkout(tmp_path: Path) -> None:
    wheel_dir = tmp_path / "wheel"
    wheel_dir.mkdir()
    environment = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    environment["PIP_NO_INDEX"] = "1"
    environment["PYTHONNOUSERSITE"] = "1"
    built = subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps", "--no-build-isolation", str(ROOT), "--wheel-dir", str(wheel_dir)], cwd=ROOT, env=environment, capture_output=True, text=True, check=False)
    assert built.returncode == 0, built.stderr[-500:]
    wheels = sorted(wheel_dir.glob("*.whl"))
    assert len(wheels) == 1
    target = tmp_path / "installed"
    venv.EnvBuilder(with_pip=True, clear=True).create(target)
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = subprocess.run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheels[0])], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert installed.returncode == 0, installed.stderr[-500:]
    probe = subprocess.run([str(python), "-c", "import mudra_interact_core; print(mudra_interact_core.__file__)"], cwd=tmp_path, env=environment, capture_output=True, text=True, check=False)
    assert probe.returncode == 0
    assert str(ROOT) not in probe.stdout


@pytest.mark.acceptance("E54")
def test_documented_v2_example_runs_and_v1_inspection_example_is_rejected(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    frame_path = _write_json(tmp_path / "frame.json", _frame())
    code, stdout, stderr = _invoke(capsys, ["--input", str(frame_path)])
    assert code == 0 and json.loads(stdout)["schema_version"] == "2.0.0" and stderr == ""
    old = _write_json(tmp_path / "old.json", {"schema_version": "1.0", "landmarks": []})
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(old)])
    assert code == 2 and stdout == "" and "1.0" not in stderr


@pytest.mark.acceptance("E55")
def test_reports_and_events_have_closed_bounded_fields(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    frame_path = _write_json(tmp_path / "frame.json", _frame())
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(frame_path)])
    assert code == 0 and stderr == ""
    report = json.loads(stdout)
    assert set(report) == {"schema_version", "recognition", "reason_code"}
    assert len(stdout.encode()) < 4096
    batch_path = _write_json(tmp_path / "batch.json", _batch())
    code, stdout, stderr = _invoke(capsys, ["recognize", "--input", str(batch_path), "--stabilize", "--emit-event", "--consent", "--confirm"])
    assert code == 0 and stderr == ""
    event = json.loads(stdout)
    assert len(stdout.encode()) <= 4096
    assert "metadata" not in event
    assert "landmarks" not in event["recognition"]
