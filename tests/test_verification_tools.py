from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

from tools.verify_gate import (
    CommandResult,
    acceptance_owners,
    check_fresh_identity,
    command_error_codes,
    parse_pytest_document,
    run_command,
    validate_ledger,
)
from tools.verification_report import (
    REPORT_SCHEMA_VERSION,
    VerificationError,
    read_json,
    seal_report,
    validate_report_integrity,
)


ROOT = Path(__file__).resolve().parents[1]


def _test_document(case_ids: list[str], outcome: str = "passed", *, complete: bool = True, exit_status: int = 0) -> dict:
    if outcome == "passed":
        phases = [{"phase": phase, "outcome": "passed"} for phase in ("setup", "call", "teardown")]
    elif outcome == "skipped":
        phases = [{"phase": "setup", "outcome": "skipped"}]
    else:
        phases = [
            {"phase": "setup", "outcome": "passed"},
            {"phase": "call", "outcome": outcome},
            {"phase": "teardown", "outcome": "passed"},
        ]
    return {
        "report_schema_version": 1,
        "complete": complete,
        "pytest_exit_status": exit_status,
        "started_at": "2026-10-06T00:00:00.000000Z",
        "finished_at": "2026-10-06T00:00:01.000000Z",
        "collected_count": len(case_ids),
        "nodes": [
            {
                "node_id": f"tests/test_contract_spec.py::case[{case_id}]",
                "acceptance_id": case_id,
                "parameter_id": case_id,
                "parameters": {},
                "phases": phases,
                "outcome": outcome,
            }
            for case_id in case_ids
        ],
    }


def _valid_report() -> dict:
    return seal_report({
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "scope": {"kind": "item", "id": "MI-01"},
        "state": "VERIFIED",
        "verification_kind": "luna_self_verified",
        "source_commit": "a" * 40,
        "source_tree_sha256": "1" * 64,
        "spec_sha256": "2" * 64,
        "acceptance_sha256": "3" * 64,
        "tool_lock_sha256": "4" * 64,
        "platform": {"os": "windows", "architecture": "x86_64", "python": "3.14.2"},
        "started_at": "2026-10-06T00:00:00.000000Z",
        "finished_at": "2026-10-06T00:00:01.000000Z",
        "commands": [],
        "test_counts": {"collected": 1, "passed": 1, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0},
        "acceptance_cases": [{"acceptance_id": "E01", "outcome": "passed", "node_id": "tests/test_contract_spec.py::test_example"}],
        "mutation_results": [],
        "artifacts": [],
        "prerequisites": [],
        "limitations": [],
        "errors": [],
        "items": ["MI-01"],
    })


@pytest.mark.acceptance("E04")
@pytest.mark.parametrize("failure", ["absent_command", "nonzero_exit", "timeout", "zero_tests", "omitted_id", "missing_parser"])
def test_runner_fails_closed_for_command_and_result_failures(tmp_path: Path, failure: str) -> None:
    if failure == "absent_command":
        result = run_command(
            ["mudra-command-that-does-not-exist-8f15"],
            cwd=tmp_path,
            log_directory=tmp_path / "logs",
            timeout_seconds=0.1,
            command_id="absent",
        )
        assert "command_unavailable" in command_error_codes(result)
    elif failure == "nonzero_exit":
        result = run_command(
            [sys.executable, "-c", "raise SystemExit(19)"],
            cwd=tmp_path,
            log_directory=tmp_path / "logs",
            timeout_seconds=2,
            command_id="nonzero",
        )
        assert "command_exit_nonzero" in command_error_codes(result)
    elif failure == "timeout":
        result = run_command(
            [sys.executable, "-c", "import time; time.sleep(3)"],
            cwd=tmp_path,
            log_directory=tmp_path / "logs",
            timeout_seconds=0.05,
            command_id="timeout",
        )
        assert "command_timeout" in command_error_codes(result)
    elif failure == "zero_tests":
        with pytest.raises(VerificationError, match="pytest_zero_tests"):
            parse_pytest_document(_test_document([]), {"E04"})
    elif failure == "omitted_id":
        with pytest.raises(VerificationError, match="pytest_case_missing"):
            parse_pytest_document(_test_document(["E01"]), {"E01", "E04"})
    else:
        with pytest.raises(VerificationError, match="pytest_report_unavailable"):
            parse_pytest_document(_test_document(["E04"]), {"E04"}, parser_available=False)


@pytest.mark.acceptance("E05")
@pytest.mark.parametrize("failure", ["skipped", "xfail", "xpass", "truncated", "stale_source", "stale_spec"])
def test_required_cases_and_evidence_cannot_pass_when_skipped_or_stale(failure: str) -> None:
    if failure in {"skipped", "xfail", "xpass"}:
        outcome = {"skipped": "skipped", "xfail": "xfailed", "xpass": "xpassed"}[failure]
        with pytest.raises(VerificationError, match="pytest_case_not_passed"):
            parse_pytest_document(_test_document(["E05"], outcome=outcome), {"E05"})
    elif failure == "truncated":
        with pytest.raises(VerificationError, match="pytest_report_invalid"):
            parse_pytest_document(_test_document(["E05"], complete=False), {"E05"})
    else:
        key = "source_tree_sha256" if failure == "stale_source" else "spec_sha256"
        receipt = {key: "0" * 64}
        with pytest.raises(VerificationError, match="receipt_stale"):
            check_fresh_identity(receipt, {key: "1" * 64})


@pytest.mark.acceptance("E06")
@pytest.mark.parametrize("failure", ["tampered_report_hash", "dependency_cycle", "unknown_dependency", "gate_cycle", "unknown_gate", "premature_gate", "hand_edited_verified"])
def test_tampered_receipts_and_invalid_ledger_graphs_are_rejected(failure: str) -> None:
    if failure == "tampered_report_hash":
        report = _valid_report()
        report["source_tree_sha256"] = "f" * 64
        with pytest.raises(VerificationError, match="report_hash_mismatch"):
            validate_report_integrity(report)
        return

    ledger = read_json(ROOT / "IMPLEMENTATION_BACKLOG.json")
    if failure == "dependency_cycle":
        ledger["items"][0]["requires"] = ["MI-01"]
        expected = "ledger_dependency_cycle"
    elif failure == "unknown_dependency":
        ledger["items"][0]["requires"] = ["MI-99"]
        expected = "ledger_unknown_item"
    elif failure == "gate_cycle":
        ledger["gates"][0]["requires"] = ["M0"]
        expected = "ledger_dependency_cycle"
    elif failure == "unknown_gate":
        ledger["gates"][0]["requires"] = ["M99"]
        expected = "ledger_unknown_gate"
    elif failure == "premature_gate":
        ledger["gates"][0]["state"] = "VERIFIED"
        expected = "ledger_gate_prematurely_verified"
    else:
        ledger["items"][0]["state"] = "VERIFIED"
        expected = "ledger_verified_without_evidence"
    with pytest.raises(VerificationError, match=expected):
        validate_ledger(ROOT, ledger, acceptance_owners(ROOT))
