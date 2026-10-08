from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from tools import verify_a2a_gate as gate
from tools.verification_report import (
    VerificationError,
    canonical_json_bytes,
    seal_report,
    sha256_file,
    sha256_text_file,
    source_commit,
    source_tree_sha256,
)


def _pytest_document(*, outcome: str = "passed") -> dict:
    return {
        "report_schema_version": 1,
        "complete": True,
        "pytest_exit_status": 0,
        "started_at": "2026-10-08T13:00:00.000000Z",
        "finished_at": "2026-10-08T13:00:01.000000Z",
        "collected_count": len(gate.REQUIRED_CASES),
        "nodes": [
            {
                "node_id": f"tests/test_a2a_interop.py::test_{case}",
                "acceptance_id": case,
                "parameter_id": None,
                "parameters": {},
                "phases": [
                    {"phase": phase, "outcome": outcome}
                    for phase in ("setup", "call", "teardown")
                ],
                "outcome": outcome,
            }
            for case in sorted(gate.REQUIRED_CASES)
        ],
    }


def _committed_repo(root: Path) -> Path:
    (root / "docs").mkdir(parents=True)
    (root / "requirements-dev.lock").write_text("locked-tools\n", encoding="utf-8")
    (root / gate.ACCEPTANCE_PATH).write_text("acceptance\n", encoding="utf-8")
    (root / gate.CONTRACT_PATH).write_text("a2a contract\n", encoding="utf-8")
    (root / gate.LANGUAGE_CONTRACT_PATH).write_text("language contract\n", encoding="utf-8")
    (root / "src").mkdir()
    (root / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Mudra Test"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "mudra-test@example.invalid"], cwd=root, check=True)
    subprocess.run(["git", "add", "--all"], cwd=root, check=True)
    subprocess.run(["git", "commit", "--quiet", "-m", "seed"], cwd=root, check=True)
    return root


def _valid_receipt(root: Path, report_path: Path) -> dict:
    acceptance_path = root / "evidence/language/ML-06-pytest.json"
    command_log_path = root / "evidence/language/ML-06.log"
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    acceptance_path.write_bytes(canonical_json_bytes(_pytest_document()))
    command_log_path.write_bytes(b"STDOUT\n4 passed\nSTDERR\n")
    cases = [
        {"acceptance_id": case, "outcome": "passed", "node_id": f"node::{case}"}
        for case in sorted(gate.REQUIRED_CASES)
    ]
    report = {
        "report_schema_version": 1,
        "scope": {"kind": "item", "id": "ML-06"},
        "state": "VERIFIED",
        "verification_kind": "luna_self_verified",
        "source_commit": source_commit(root),
        "source_tree_sha256": source_tree_sha256(root),
        "acceptance_sha256": sha256_text_file(root / gate.ACCEPTANCE_PATH),
        "contract_sha256": sha256_text_file(root / gate.CONTRACT_PATH),
        "tool_lock_sha256": sha256_text_file(root / gate.LOCK_PATH),
        "platform": {"os": "windows", "architecture": "x86_64", "python": "3.14.0"},
        "started_at": "2026-10-08T13:00:00.000000Z",
        "finished_at": "2026-10-08T13:00:01.000000Z",
        "commands": [{
            "id": "ml06_a2a_acceptance",
            "argv": [
                "python", "-m", "pytest", "tests/test_a2a_interop.py",
                "tests/test_a2a_verification.py",
            ],
            "exit_code": 0,
        }],
        "test_counts": {
            "collected": len(cases), "passed": len(cases), "failed": 0,
            "skipped": 0, "xfailed": 0, "xpassed": 0,
        },
        "acceptance_cases": cases,
        "artifacts": [
            {
                "kind": "acceptance_report",
                "path": acceptance_path.relative_to(root).as_posix(),
                "sha256": sha256_file(acceptance_path),
                "size_bytes": acceptance_path.stat().st_size,
            },
            {
                "kind": "command_log",
                "path": command_log_path.relative_to(root).as_posix(),
                "sha256": sha256_file(command_log_path),
                "size_bytes": command_log_path.stat().st_size,
            },
        ],
        "limitations": gate._EXPECTED_LIMITATIONS,
        "errors": [],
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_bytes(canonical_json_bytes(seal_report(report)))
    return report


@pytest.mark.acceptance("L53")
def test_pytest_receipt_parser_requires_all_cases_and_only_passed_phases() -> None:
    counts, cases = gate._parse_pytest_report(_pytest_document())
    assert counts["collected"] == counts["passed"] == len(gate.REQUIRED_CASES)
    assert {case["acceptance_id"] for case in cases} == gate.REQUIRED_CASES

    skipped = _pytest_document(outcome="skipped")
    with pytest.raises(VerificationError, match="a2a_pytest_phase_invalid|a2a_acceptance_incomplete"):
        gate._parse_pytest_report(skipped)

    incomplete = _pytest_document()
    incomplete["nodes"].pop()
    incomplete["collected_count"] -= 1
    with pytest.raises(VerificationError, match="a2a_acceptance_incomplete"):
        gate._parse_pytest_report(incomplete)


@pytest.mark.acceptance("L53")
def test_receipt_checker_accepts_fresh_receipt_and_rejects_tampered_artifact(tmp_path: Path) -> None:
    root = _committed_repo(tmp_path / "repo")
    report_path = root / "evidence/language/ML-06.json"
    _valid_receipt(root, report_path)
    assert gate._check_receipt(root, report_path)["state"] == "VERIFIED"

    command_log = root / "evidence/language/ML-06.log"
    command_log.write_bytes(b"x" * command_log.stat().st_size)
    with pytest.raises(VerificationError, match="a2a_receipt_artifact_hash_mismatch"):
        gate._check_receipt(root, report_path)


@pytest.mark.acceptance("L53")
def test_receipt_checker_rejects_stale_contract_and_forged_outcome(tmp_path: Path) -> None:
    root = _committed_repo(tmp_path / "repo")
    report_path = root / "evidence/language/ML-06.json"
    _valid_receipt(root, report_path)

    (root / gate.CONTRACT_PATH).write_text("changed contract\n", encoding="utf-8")
    with pytest.raises(VerificationError, match="a2a_receipt_stale"):
        gate._check_receipt(root, report_path)

    report_path = root / "evidence/language/ML-06-forged.json"
    _valid_receipt(root, report_path)
    forged = json.loads(report_path.read_text(encoding="utf-8"))
    forged["acceptance_cases"][0]["outcome"] = "skipped"
    report_path.write_bytes(canonical_json_bytes(seal_report(forged)))
    with pytest.raises(VerificationError, match="a2a_receipt_not_verified"):
        gate._check_receipt(root, report_path)


@pytest.mark.acceptance("L53")
def test_output_path_rejects_traversal_and_non_evidence_receipt(tmp_path: Path) -> None:
    root = _committed_repo(tmp_path / "repo")
    for path in ("../outside.json", "evidence\\language\\report.json"):
        with pytest.raises(VerificationError, match="a2a_report_path_invalid"):
            gate._safe_output_path(root, path)

    outside = root / "build/report.json"
    outside.parent.mkdir()
    outside.write_text("{}", encoding="utf-8")
    with pytest.raises(VerificationError, match="a2a_report_path_invalid"):
        gate._check_receipt(root, outside)
