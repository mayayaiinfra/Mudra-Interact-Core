from __future__ import annotations

from pathlib import Path

import pytest

from tools.verify_language_gate import _atomic_bytes, _report_path
from tools.verification_report import (
    REPORT_SCHEMA_VERSION,
    VerificationError,
    canonical_json_bytes,
    seal_report,
    sha256_bytes,
)
from tools.verify_language_gate import (
    LANGUAGE_IDENTITY_FIELDS,
    compare_identity,
    parse_language_pytest_document,
    validate_language_receipt_files,
)


def _phase_reports(outcome: str = "passed") -> list[dict[str, str]]:
    return [{"phase": phase, "outcome": outcome} for phase in ("setup", "call", "teardown")]


def _pytest_document(case_ids: list[str] | None = None, *, outcome: str = "passed", exit_status: int = 0) -> dict:
    cases = case_ids if case_ids is not None else ["L01", "L02", "L03"]
    nodes = []
    for index, case_id in enumerate(cases):
        nodes.append({
            "node_id": f"tests/test_language_contract.py::case-{index}",
            "acceptance_id": case_id,
            "parameter_id": None,
            "parameters": {},
            "phases": _phase_reports(outcome if outcome in {"skipped", "xfailed", "xpassed", "failed"} else "passed"),
            "outcome": outcome,
        })
    return {
        "report_schema_version": 1,
        "complete": True,
        "pytest_exit_status": exit_status,
        "collected_count": len(nodes),
        "nodes": nodes,
    }


def _receipt(report_artifact: dict | None = None) -> dict:
    if report_artifact is None:
        report_artifact = {
            "kind": "acceptance_report",
            "path": "evidence/language/ML-01-pytest.json",
            "sha256": "5" * 64,
            "size_bytes": 1,
        }
    return seal_report({
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "scope": {"kind": "item", "id": "ML-01"},
        "state": "VERIFIED",
        "verification_kind": "luna_self_verified",
        "source_commit": "a" * 40,
        "source_tree_sha256": "1" * 64,
        "spec_sha256": "2" * 64,
        "acceptance_sha256": "3" * 64,
        "tool_lock_sha256": "4" * 64,
        "schema_sha256": "5" * 64,
        "version_map_sha256": "6" * 64,
        "fixture_manifest_sha256": "7" * 64,
        "platform": {"os": "windows", "architecture": "x86_64", "python": "3.14.2"},
        "started_at": "2026-10-08T12:00:00.000000Z",
        "finished_at": "2026-10-08T12:00:01.000000Z",
        "commands": [],
        "test_counts": {"collected": 3, "passed": 3, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0},
        "acceptance_cases": [
            {"acceptance_id": case_id, "outcome": "passed", "node_id": f"tests/test_language_contract.py::case-{index}"}
            for index, case_id in enumerate(("L01", "L02", "L03"))
        ],
        "mutation_results": [],
        "artifacts": [report_artifact],
        "prerequisites": [],
        "limitations": [],
        "errors": [],
        "items": ["ML-01"],
    })


@pytest.mark.acceptance("L03")
@pytest.mark.parametrize(
    ("case_ids", "outcome", "exit_status", "error"),
    [
        (["L01", "L02"], "passed", 0, "language_pytest_case_missing"),
        (["L01", "L02", "L03", "L99"], "passed", 0, "language_pytest_case_unknown_or_missing"),
        ([], "passed", 0, "language_pytest_zero_or_mismatched_collection"),
        (["L01", "L02", "L03"], "skipped", 0, "language_pytest_case_not_passed"),
        (["L01", "L02", "L03"], "xfailed", 0, "language_pytest_case_not_passed"),
        (["L01", "L02", "L03"], "xpassed", 0, "language_pytest_case_not_passed"),
        (["L01", "L02", "L03"], "passed", 9, "language_pytest_nonzero_exit"),
    ],
)
def test_acceptance_report_rejects_missing_unknown_empty_skip_and_failed_runs(
    case_ids: list[str], outcome: str, exit_status: int, error: str
) -> None:
    with pytest.raises(VerificationError, match=error):
        parse_language_pytest_document(_pytest_document(case_ids, outcome=outcome, exit_status=exit_status))


@pytest.mark.acceptance("L03")
def test_acceptance_report_rejects_duplicate_nodes_and_missing_phases() -> None:
    document = _pytest_document()
    document["nodes"][1]["node_id"] = document["nodes"][0]["node_id"]
    with pytest.raises(VerificationError, match="language_pytest_node_duplicate_or_invalid"):
        parse_language_pytest_document(document)

    document = _pytest_document()
    document["nodes"][0]["phases"] = [{"phase": "call", "outcome": "passed"}]
    with pytest.raises(VerificationError, match="language_pytest_case_not_passed"):
        parse_language_pytest_document(document)


@pytest.mark.acceptance("L03")
@pytest.mark.parametrize("identity_field", sorted(LANGUAGE_IDENTITY_FIELDS))
def test_receipt_rejects_stale_source_and_contract_identities(identity_field: str) -> None:
    receipt = _receipt()
    current = {field: receipt[field] for field in LANGUAGE_IDENTITY_FIELDS}
    current[identity_field] = "f" * 64
    with pytest.raises(VerificationError, match="language_receipt_stale"):
        compare_identity(receipt, current)


@pytest.mark.acceptance("L03")
def test_receipt_requires_hash_bound_evidence_and_rejects_forged_verified_result(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "language"
    evidence_dir.mkdir(parents=True)
    pytest_path = evidence_dir / "ML-01-pytest.json"
    encoded = canonical_json_bytes(_pytest_document())
    pytest_path.write_bytes(encoded)
    artifact = {
        "kind": "acceptance_report",
        "path": "evidence/language/ML-01-pytest.json",
        "sha256": sha256_bytes(encoded),
        "size_bytes": len(encoded),
    }
    report_path = evidence_dir / "ML-01.json"
    report_path.write_bytes(canonical_json_bytes(_receipt(artifact)))
    receipt = validate_language_receipt_files(tmp_path, report_path)
    assert receipt["state"] == "VERIFIED"

    forged = _receipt()
    forged["test_counts"]["passed"] = 2
    report_path.write_bytes(canonical_json_bytes(seal_report(forged)))
    with pytest.raises(VerificationError, match="language_receipt_counts_invalid"):
        validate_language_receipt_files(tmp_path, report_path)

    no_evidence = _receipt()
    no_evidence["artifacts"] = []
    report_path.write_bytes(canonical_json_bytes(seal_report(no_evidence)))
    with pytest.raises(VerificationError, match="language_receipt_evidence_missing"):
        validate_language_receipt_files(tmp_path, report_path)


@pytest.mark.acceptance("L03")
def test_receipt_rejects_tampered_or_missing_pytest_artifact(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence" / "language"
    evidence_dir.mkdir(parents=True)
    pytest_path = evidence_dir / "ML-01-pytest.json"
    encoded = canonical_json_bytes(_pytest_document())
    pytest_path.write_bytes(encoded)
    artifact = {
        "kind": "acceptance_report",
        "path": "evidence/language/ML-01-pytest.json",
        "sha256": sha256_bytes(encoded),
        "size_bytes": len(encoded),
    }
    report_path = evidence_dir / "ML-01.json"
    report_path.write_bytes(canonical_json_bytes(_receipt(artifact)))

    pytest_path.write_bytes(encoded + b" ")
    with pytest.raises(VerificationError, match="language_receipt_artifact_hash_mismatch"):
        validate_language_receipt_files(tmp_path, report_path)

    pytest_path.unlink()
    with pytest.raises(VerificationError, match="language_file_missing_or_outside_root"):
        validate_language_receipt_files(tmp_path, report_path)


@pytest.mark.acceptance("L03")
def test_evidence_writer_rejects_symlinked_parent_and_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path.resolve()
    linked_parent = root / "evidence" / "language"
    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "is_symlink", lambda path: path == linked_parent)
        with pytest.raises(VerificationError, match="language_report_path_invalid"):
            _report_path(root, "evidence/language/ML-01.json")

    target = root / "evidence" / "language" / "ML-01.log"
    with monkeypatch.context() as patcher:
        patcher.setattr(Path, "is_symlink", lambda path: path == target)
        with pytest.raises(VerificationError, match="language_report_path_invalid"):
            _atomic_bytes(target, b"must not overwrite a symlink target")
