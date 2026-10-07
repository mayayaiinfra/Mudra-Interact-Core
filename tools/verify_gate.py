"""Execute acceptance cases and create fail-closed Mudra gate receipts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from uuid import uuid4

_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

from tools.verification_report import (
    REPORT_SCHEMA_VERSION,
    VerificationError,
    canonical_json_bytes,
    read_json,
    seal_report,
    sha256_bytes,
    sha256_file,
    source_commit,
    source_tree_sha256,
    validate_fixture_manifest,
    validate_receipt_file,
)


ACCEPTANCE_PATTERN = re.compile(r"^\|\s*(E\d{2})\s*\|\s*(MI-\d{2})\s*/\s*([^|]+)\|")
STATES = {"NOT_STARTED", "IN_PROGRESS", "IMPLEMENTED", "VERIFIED", "FAILED", "BLOCKED"}
OUTPUT_LIMIT = 512 * 1024
REQUIRED_TEST_REPORT_FIELDS = {
    "report_schema_version", "complete", "pytest_exit_status", "started_at",
    "finished_at", "collected_count", "nodes",
}
SAFE_REPORT_ERROR_CODES = {
    "invalid_json", "duplicate_json_key", "invalid_json_number", "invalid_unicode",
    "file_unavailable", "file_too_large", "source_inventory_unavailable",
    "source_path_invalid", "source_commit_unavailable", "fixture_manifest_shape",
    "fixture_manifest_version_or_origin", "fixture_manifest_empty", "fixture_record_shape",
    "fixture_manifest_path_invalid",
    "fixture_id_duplicate_or_invalid", "fixture_path_duplicate_or_invalid",
    "fixture_case_unknown", "fixture_origin_not_synthetic", "fixture_digest_shape",
    "fixture_expectation_shape", "fixture_expected_fields_shape", "fixture_expected_error_missing",
    "fixture_valid_has_error", "fixture_path_invalid", "fixture_missing_or_outside_root",
    "fixture_symlink_forbidden", "fixture_not_regular_file", "fixture_hash_mismatch",
    "report_not_serializable", "report_shape_invalid", "report_version_invalid",
    "report_hash_mismatch", "receipt_path_invalid", "receipt_missing_or_outside_root",
    "receipt_not_regular_file", "receipt_file_hash_mismatch", "receipt_not_verified",
    "receipt_scope_mismatch", "receipt_acceptance_cases_missing", "receipt_stale",
    "receipt_artifact_invalid", "receipt_artifact_missing", "receipt_artifact_hash_mismatch",
    "receipt_artifact_size_mismatch", "source_symlink_forbidden",
    "ledger_shape_invalid", "ledger_item_duplicate", "ledger_gate_duplicate", "ledger_state_invalid",
    "ledger_unknown_item", "ledger_unknown_gate", "ledger_gate_membership_invalid",
    "ledger_acceptance_mapping_invalid", "ledger_dependency_cycle", "ledger_active_item_invalid",
    "ledger_verified_without_evidence", "ledger_gate_prematurely_verified", "ledger_evidence_invalid",
    "item_unknown", "gate_unknown", "prerequisite_not_verified", "active_item_mismatch",
    "acceptance_matrix_unavailable", "acceptance_module_unavailable", "report_path_invalid",
    "command_unavailable", "command_timeout", "command_launch_failed", "command_output_truncated",
    "command_exit_nonzero", "pytest_report_unavailable", "pytest_report_invalid",
    "pytest_zero_tests", "pytest_nonzero_exit", "pytest_node_duplicate", "pytest_node_invalid",
    "pytest_case_missing", "pytest_case_unexpected", "pytest_case_not_passed", "source_changed_during_run",
    "specification_unavailable", "acceptance_document_unavailable", "tool_lock_unavailable",
    "fixture_case_not_executed", "verification_error",
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def acceptance_owners(root: Path) -> dict[str, tuple[str, str]]:
    path = root / "docs" / "ACCEPTANCE.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise VerificationError("acceptance_matrix_unavailable") from None
    owners: dict[str, tuple[str, str]] = {}
    for line in lines:
        match = ACCEPTANCE_PATTERN.match(line)
        if not match:
            continue
        case_id, item_id, module = match.groups()
        module_name = module.strip().split()[0]
        if case_id in owners:
            raise VerificationError("acceptance_matrix_unavailable")
        owners[case_id] = (item_id, module_name)
    if not owners:
        raise VerificationError("acceptance_matrix_unavailable")
    return owners


def _acyclic(graph: dict[str, list[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return False
        if node in visited:
            return True
        visiting.add(node)
        for dependency in graph.get(node, []):
            if dependency not in graph or not visit(dependency):
                return False
        visiting.remove(node)
        visited.add(node)
        return True

    return all(visit(node) for node in graph)


def _evidence_for_status(
    root: Path,
    evidence: Any,
    *,
    accepted_cases: Iterable[str],
    expected_kind: str,
    expected_id: str,
    require_gate_scope: bool = False,
) -> None:
    if not isinstance(evidence, list) or not evidence:
        raise VerificationError("ledger_verified_without_evidence")
    required = set(accepted_cases)
    found = False
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise VerificationError("ledger_evidence_invalid")
        receipt = validate_receipt_file(
            root,
            item["path"],
            item["sha256"],
            required_case_ids=required,
        )
        scope = receipt.get("scope")
        covers = False
        if isinstance(scope, dict):
            if scope == {"kind": expected_kind, "id": expected_id}:
                covers = True
            elif expected_kind == "item" and scope.get("kind") == "gate":
                covers = expected_id in receipt.get("items", [])
            elif expected_kind == "gate" and scope.get("kind") == "gate" and scope.get("id") == expected_id:
                covers = True
        if covers:
            if require_gate_scope and (scope.get("kind") != "gate" or scope.get("id") != expected_id):
                continue
            found = True
    if not found:
        raise VerificationError("ledger_evidence_invalid")


def validate_ledger(root: Path, ledger: Any, owners: dict[str, tuple[str, str]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if not isinstance(ledger, dict) or not isinstance(ledger.get("items"), list) or not isinstance(ledger.get("gates"), list):
        raise VerificationError("ledger_shape_invalid")
    items: dict[str, dict[str, Any]] = {}
    gates: dict[str, dict[str, Any]] = {}
    for item in ledger["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or item["id"] in items:
            raise VerificationError("ledger_item_duplicate")
        items[item["id"]] = item
    for gate in ledger["gates"]:
        if not isinstance(gate, dict) or not isinstance(gate.get("id"), str) or gate["id"] in gates:
            raise VerificationError("ledger_gate_duplicate")
        gates[gate["id"]] = gate
    if not items or not gates:
        raise VerificationError("ledger_shape_invalid")
    item_graph: dict[str, list[str]] = {}
    gate_graph: dict[str, list[str]] = {}
    seen_cases: set[str] = set()
    for item_id, item in items.items():
        if item.get("state") not in STATES or item.get("gate") not in gates:
            raise VerificationError("ledger_state_invalid")
        dependencies = item.get("requires", [])
        case_ids = item.get("acceptance_ids", [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise VerificationError("ledger_shape_invalid")
        if any(dep not in items for dep in dependencies):
            raise VerificationError("ledger_unknown_item")
        if not isinstance(case_ids, list) or any(not isinstance(case, str) for case in case_ids):
            raise VerificationError("ledger_shape_invalid")
        item_graph[item_id] = dependencies
        for case_id in case_ids:
            if case_id not in owners or owners[case_id][0] != item_id or case_id in seen_cases:
                raise VerificationError("ledger_acceptance_mapping_invalid")
            seen_cases.add(case_id)
        if item.get("state") == "VERIFIED":
            _evidence_for_status(
                root, item.get("evidence"), accepted_cases=case_ids,
                expected_kind="item", expected_id=item_id,
            )
    for gate_id, gate in gates.items():
        if gate.get("state") not in STATES:
            raise VerificationError("ledger_state_invalid")
        dependencies = gate.get("requires", [])
        member_ids = gate.get("items", [])
        if not isinstance(dependencies, list) or any(not isinstance(dep, str) for dep in dependencies):
            raise VerificationError("ledger_shape_invalid")
        if any(dep not in gates for dep in dependencies):
            raise VerificationError("ledger_unknown_gate")
        if not isinstance(member_ids, list) or any(item_id not in items for item_id in member_ids):
            raise VerificationError("ledger_unknown_item")
        expected_members = {item_id for item_id, item in items.items() if item["gate"] == gate_id}
        if set(member_ids) != expected_members or len(member_ids) != len(expected_members):
            raise VerificationError("ledger_gate_membership_invalid")
        gate_graph[gate_id] = dependencies
        if gate.get("state") == "VERIFIED":
            if any(items[item_id].get("state") != "VERIFIED" for item_id in member_ids):
                raise VerificationError("ledger_gate_prematurely_verified")
            required_cases = [case for item_id in member_ids for case in items[item_id]["acceptance_ids"]]
            _evidence_for_status(
                root, gate.get("evidence"), accepted_cases=required_cases,
                expected_kind="gate", expected_id=gate_id, require_gate_scope=True,
            )
    expected_cases = {case for item in items.values() for case in item.get("acceptance_ids", [])}
    if seen_cases != expected_cases or expected_cases != set(owners):
        raise VerificationError("ledger_acceptance_mapping_invalid")
    if not _acyclic(item_graph) or not _acyclic(gate_graph):
        raise VerificationError("ledger_dependency_cycle")
    in_progress = [item_id for item_id, item in items.items() if item["state"] == "IN_PROGRESS"]
    active = ledger.get("active_item")
    if len(in_progress) > 1 or (in_progress[0] if in_progress else None) != active:
        raise VerificationError("ledger_active_item_invalid")
    if type(ledger.get("implementation_started")) is not bool:
        raise VerificationError("ledger_shape_invalid")
    return items, gates


@dataclass(frozen=True)
class CommandResult:
    exit_code: int | None
    error_code: str | None
    timed_out: bool
    elapsed_seconds: float
    stdout_path: str | None
    stdout_sha256: str | None
    stdout_bytes: int
    stdout_truncated: bool
    stderr_path: str | None
    stderr_sha256: str | None
    stderr_bytes: int
    stderr_truncated: bool


def _drain(stream: Any, path: Path, result: dict[str, Any]) -> None:
    digest = hashlib.sha256()
    kept = 0
    total = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as output:
        while True:
            chunk = stream.read(65536)
            if not chunk:
                break
            total += len(chunk)
            digest.update(chunk)
            if kept < OUTPUT_LIMIT:
                selected = chunk[: OUTPUT_LIMIT - kept]
                output.write(selected)
                kept += len(selected)
        output.flush()
        os.fsync(output.fileno())
    result.update({"sha256": digest.hexdigest(), "bytes": total, "truncated": total > OUTPUT_LIMIT})


def _terminate_tree(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill:
            try:
                subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
        if process.poll() is None:
            process.kill()
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            if process.poll() is None:
                process.kill()


def run_command(
    argv: list[str],
    *,
    cwd: Path,
    log_directory: Path,
    timeout_seconds: float,
    command_id: str,
) -> CommandResult:
    if not argv or not isinstance(argv[0], str) or not shutil.which(argv[0]):
        return CommandResult(None, "command_unavailable", False, 0.0, None, None, 0, False, None, None, 0, False)
    safe_id = re.sub(r"[^A-Za-z0-9_-]", "_", command_id)[:64] or "command"
    stdout_file = log_directory / f"{safe_id}.stdout.log"
    stderr_file = log_directory / f"{safe_id}.stderr.log"
    collector: dict[str, dict[str, Any]] = {"stdout": {}, "stderr": {}}
    started = time.monotonic()
    try:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            close_fds=True,
            start_new_session=(os.name != "nt"),
            creationflags=flags,
        )
    except FileNotFoundError:
        return CommandResult(None, "command_unavailable", False, time.monotonic() - started, None, None, 0, False, None, None, 0, False)
    except (OSError, ValueError):
        return CommandResult(None, "command_launch_failed", False, time.monotonic() - started, None, None, 0, False, None, None, 0, False)
    assert process.stdout is not None and process.stderr is not None
    threads = [
        threading.Thread(target=_drain, args=(process.stdout, stdout_file, collector["stdout"]), daemon=True),
        threading.Thread(target=_drain, args=(process.stderr, stderr_file, collector["stderr"]), daemon=True),
    ]
    for thread in threads:
        thread.start()
    timed_out = False
    try:
        process.wait(timeout=max(0.01, timeout_seconds))
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_tree(process)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    for thread in threads:
        thread.join(timeout=5)
    if any(thread.is_alive() for thread in threads):
        for stream in (process.stdout, process.stderr):
            try:
                stream.close()
            except OSError:
                pass
        for thread in threads:
            thread.join(timeout=1)
    error_code = "command_timeout" if timed_out else None
    return CommandResult(
        process.returncode,
        error_code,
        timed_out,
        time.monotonic() - started,
        stdout_file.as_posix(),
        collector["stdout"].get("sha256"),
        collector["stdout"].get("bytes", 0),
        collector["stdout"].get("truncated", False),
        stderr_file.as_posix(),
        collector["stderr"].get("sha256"),
        collector["stderr"].get("bytes", 0),
        collector["stderr"].get("truncated", False),
    )


def parse_pytest_document(document: Any, required_case_ids: Iterable[str], *, parser_available: bool = True) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if not parser_available:
        raise VerificationError("pytest_report_unavailable")
    if not isinstance(document, dict) or not REQUIRED_TEST_REPORT_FIELDS.issubset(document):
        raise VerificationError("pytest_report_invalid")
    if document.get("report_schema_version") != 1 or document.get("complete") is not True:
        raise VerificationError("pytest_report_invalid")
    nodes = document.get("nodes")
    if not isinstance(nodes, list) or document.get("collected_count") != len(nodes):
        raise VerificationError("pytest_report_invalid")
    if not nodes:
        raise VerificationError("pytest_zero_tests")
    required = set(required_case_ids)
    seen_node_ids: set[str] = set()
    case_outcomes: dict[str, list[str]] = {}
    counts = {"collected": len(nodes), "passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    normalized_nodes: list[dict[str, Any]] = []
    for node in nodes:
        if not isinstance(node, dict):
            raise VerificationError("pytest_node_invalid")
        node_id = node.get("node_id")
        case_id = node.get("acceptance_id")
        outcome = node.get("outcome")
        if not isinstance(node_id, str) or not node_id or node_id in seen_node_ids:
            raise VerificationError("pytest_node_duplicate")
        if not isinstance(case_id, str) or case_id not in required or outcome not in {"passed", "failed", "skipped", "xfailed", "xpassed"}:
            raise VerificationError("pytest_node_invalid")
        phases = node.get("phases")
        if not isinstance(phases, list) or not phases:
            raise VerificationError("pytest_node_invalid")
        phase_outcomes: dict[str, str] = {}
        for phase in phases:
            if (
                not isinstance(phase, dict)
                or phase.get("phase") not in {"setup", "call", "teardown"}
                or phase.get("outcome") not in {"passed", "failed", "skipped", "xfailed", "xpassed"}
                or phase.get("phase") in phase_outcomes
            ):
                raise VerificationError("pytest_node_invalid")
            phase_outcomes[phase["phase"]] = phase["outcome"]
        phase_values = set(phase_outcomes.values())
        derived_outcome = (
            "xpassed" if "xpassed" in phase_values else
            "failed" if "failed" in phase_values else
            "xfailed" if "xfailed" in phase_values else
            "skipped" if "skipped" in phase_values else
            "passed" if phase_values == {"passed"} else
            "not_executed"
        )
        if derived_outcome != outcome:
            raise VerificationError("pytest_node_invalid")
        seen_node_ids.add(node_id)
        case_outcomes.setdefault(case_id, []).append(outcome)
        if outcome == "not_executed":
            raise VerificationError("pytest_node_invalid")
        counts[outcome] += 1
        normalized_nodes.append({
            "node_id": node_id,
            "acceptance_id": case_id,
            "parameter_id": node.get("parameter_id"),
            "parameters": node.get("parameters", {}),
            "phases": phases,
            "outcome": outcome,
        })
    actual = set(case_outcomes)
    if actual - required:
        raise VerificationError("pytest_case_unexpected")
    if required - actual:
        raise VerificationError("pytest_case_missing")
    if document.get("pytest_exit_status") != 0:
        raise VerificationError("pytest_nonzero_exit")
    for case_id in required:
        if any(outcome != "passed" for outcome in case_outcomes[case_id]):
            raise VerificationError("pytest_case_not_passed")
    return counts, normalized_nodes


def parse_pytest_report(path: Path, required_case_ids: Iterable[str], *, parser_available: bool = True) -> tuple[dict[str, int], list[dict[str, Any]]]:
    if not parser_available or not path.is_file():
        raise VerificationError("pytest_report_unavailable")
    return parse_pytest_document(read_json(path, max_bytes=4 * 1024 * 1024), required_case_ids, parser_available=parser_available)


def command_error_codes(result: CommandResult) -> list[str]:
    errors: list[str] = []
    if result.error_code:
        errors.append(result.error_code)
    if result.exit_code != 0 and result.error_code is None:
        errors.append("command_exit_nonzero")
    if result.stdout_truncated or result.stderr_truncated:
        errors.append("command_output_truncated")
    return errors


def check_fresh_identity(receipt: dict[str, Any], current_identity: dict[str, str]) -> None:
    for key, current in current_identity.items():
        if receipt.get(key) != current:
            raise VerificationError("receipt_stale")


def _validate_receipt_record(
    root: Path,
    receipt: dict[str, Any],
    *,
    target: dict[str, str],
    required_cases: set[str],
    current_identity: dict[str, str] | None = None,
) -> None:
    if not isinstance(receipt, dict) or receipt.get("state") != "VERIFIED":
        raise VerificationError("prerequisite_not_verified")
    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise VerificationError("prerequisite_not_verified")
    for entry in evidence:
        if not isinstance(entry, dict) or set(entry) != {"path", "sha256"}:
            continue
        actual = validate_receipt_file(
            root,
            entry["path"],
            entry["sha256"],
            required_case_ids=required_cases,
            current_identity=current_identity,
        )
        if target.get("id") in actual.get("items", []):
            return
        if actual.get("scope") == target:
            return
    raise VerificationError("prerequisite_not_verified")


def _gate_closure(gate_id: str, gates: dict[str, dict[str, Any]]) -> set[str]:
    closure: set[str] = set()

    def add(current: str) -> None:
        if current in closure:
            return
        gate = gates.get(current)
        if gate is None:
            raise VerificationError("ledger_unknown_gate")
        closure.add(current)
        for dependency in gate.get("requires", []):
            add(dependency)

    add(gate_id)
    return closure


def _prepare_scope(
    root: Path,
    selector_kind: str,
    selector_id: str,
    items: dict[str, dict[str, Any]],
    gates: dict[str, dict[str, Any]],
) -> tuple[list[str], set[str], dict[str, str], list[dict[str, Any]]]:
    prerequisites: list[dict[str, Any]] = []
    if selector_kind == "item":
        if selector_id not in items:
            raise VerificationError("item_unknown")
        target = items[selector_id]
        selected_item_ids = [selector_id]
        gate_id = target["gate"]
        current_identity = _current_identity(root)
        for dependency in target.get("requires", []):
            dep_item = items[dependency]
            _validate_receipt_record(
                root,
                dep_item,
                target={"kind": "item", "id": dependency},
                required_cases=set(dep_item["acceptance_ids"]),
                current_identity=current_identity,
            )
            prerequisites.append({"id": dependency, "state": dep_item["state"]})
        for dependency_gate in gates[gate_id].get("requires", []):
            gate = gates[dependency_gate]
            if gate.get("state") != "VERIFIED":
                raise VerificationError("prerequisite_not_verified")
            all_cases = [case for item_id in gate["items"] for case in items[item_id]["acceptance_ids"]]
            _validate_receipt_record(
                root,
                gate,
                target={"kind": "gate", "id": dependency_gate},
                required_cases=set(all_cases),
                current_identity=current_identity,
            )
            prerequisites.append({"id": dependency_gate, "state": gate["state"]})
        scope = {"kind": "item", "id": selector_id}
    else:
        if selector_id not in gates:
            raise VerificationError("gate_unknown")
        gate = gates[selector_id]
        current_identity = _current_identity(root)
        for dependency_gate in gate.get("requires", []):
            dep = gates[dependency_gate]
            if dep.get("state") != "VERIFIED":
                raise VerificationError("prerequisite_not_verified")
            dep_cases = [case for item_id in dep["items"] for case in items[item_id]["acceptance_ids"]]
            _validate_receipt_record(
                root,
                dep,
                target={"kind": "gate", "id": dependency_gate},
                required_cases=set(dep_cases),
                current_identity=current_identity,
            )
            prerequisites.append({"id": dependency_gate, "state": dep["state"]})
        gate_ids = _gate_closure(selector_id, gates)
        selected_item_ids = [
            item_id for item_id, item in items.items() if item.get("gate") in gate_ids
        ]
        scope = {"kind": "gate", "id": selector_id}
    required_case_ids = {
        case_id for item_id in selected_item_ids for case_id in items[item_id]["acceptance_ids"]
    }
    test_modules: dict[str, str] = {}
    owners = acceptance_owners(root)
    for case_id in sorted(required_case_ids):
        if case_id not in owners:
            raise VerificationError("ledger_acceptance_mapping_invalid")
        module = owners[case_id][1]
        module_path = root / "tests" / module
        if not module_path.is_file():
            raise VerificationError("acceptance_module_unavailable")
        test_modules[module] = (Path("tests") / module).as_posix()
    return selected_item_ids, required_case_ids, test_modules, prerequisites


def _current_identity(root: Path) -> dict[str, str]:
    files = {
        "source_tree_sha256": None,
        "spec_sha256": None,
        "acceptance_sha256": None,
        "tool_lock_sha256": None,
    }
    paths = {
        "source_tree_sha256": None,
        "spec_sha256": root / "MUDRA_INTERACT_CORE_SPEC.md",
        "acceptance_sha256": root / "docs" / "ACCEPTANCE.md",
        "tool_lock_sha256": root / "requirements-dev.lock",
    }
    for key, path in paths.items():
        if path is None:
            files[key] = source_tree_sha256(root)
        else:
            try:
                files[key] = sha256_file(path)
            except OSError:
                code = {
                    "spec_sha256": "specification_unavailable",
                    "acceptance_sha256": "acceptance_document_unavailable",
                    "tool_lock_sha256": "tool_lock_unavailable",
                }[key]
                raise VerificationError(code) from None
    return {key: str(value) for key, value in files.items()}


def _safe_display_argv(argv: list[str], report_path: Path, root: Path) -> list[str]:
    display: list[str] = []
    for index, argument in enumerate(argv):
        if index == 0:
            display.append("python")
        else:
            try:
                path = Path(argument)
                relative = path.resolve(strict=False).relative_to(root.resolve())
                display.append(relative.as_posix())
            except (ValueError, OSError):
                text = str(argument)
                display.append(text.replace(str(root), "<repository>")[:512])
    return display


def _counts_for(cases: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"collected": len(cases), "passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    for case in cases:
        outcome = case.get("outcome")
        if outcome in counts:
            counts[outcome] += 1
    return counts


def _write_report(root: Path, path: Path, report: dict[str, Any]) -> str:
    try:
        # The caller supplies a repository-relative report path under evidence/local.
        relative_parts = path.as_posix().split("/")
        if (
            relative_parts[:2] != ["evidence", "local"]
            or path.is_absolute()
            or ".." in relative_parts
            or len(relative_parts) < 3
        ):
            raise VerificationError("report_path_invalid")
        destination = root.joinpath(*relative_parts)
        destination.resolve(strict=False).relative_to(root.resolve())
        current = destination
        while current != root:
            if current.is_symlink():
                raise VerificationError("report_path_invalid")
            current = current.parent
        destination.parent.mkdir(parents=True, exist_ok=True)
        encoded = canonical_json_bytes(seal_report(report))
        temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
        with temporary.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        return sha256_bytes(encoded)
    except VerificationError:
        raise
    except (OSError, ValueError):
        raise VerificationError("report_path_invalid") from None


def _make_report_skeleton(root: Path, scope: dict[str, str], started_at: str) -> dict[str, Any]:
    identity: dict[str, str]
    try:
        identity = _current_identity(root)
    except VerificationError:
        identity = {
            "source_tree_sha256": "0" * 64,
            "spec_sha256": "0" * 64,
            "acceptance_sha256": "0" * 64,
            "tool_lock_sha256": "0" * 64,
        }
    try:
        commit = source_commit(root)
    except VerificationError:
        commit = "unavailable"
    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "scope": scope,
        "state": "BLOCKED",
        "verification_kind": "luna_self_verified",
        "source_commit": commit,
        **identity,
        "platform": {
            "os": platform.system().lower(),
            "os_release": platform.release()[:128],
            "architecture": platform.machine()[:64],
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "python_build": list(platform.python_build()),
        },
        "started_at": started_at,
        "finished_at": started_at,
        "commands": [],
        "test_counts": {"collected": 0, "passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0},
        "acceptance_cases": [],
        "mutation_results": [],
        "artifacts": [],
        "prerequisites": [],
        "limitations": [],
        "errors": [],
        "items": [],
    }


def _safe_error(error: VerificationError) -> dict[str, str]:
    code = error.code if error.code in SAFE_REPORT_ERROR_CODES else "verification_error"
    return {"code": code}


def execute_scope(root: Path, selector_kind: str, selector_id: str, report_path: str, *, timeout_seconds: float = 180.0) -> tuple[int, dict[str, Any]]:
    root = root.resolve()
    scope = {"kind": selector_kind, "id": selector_id}
    started_at = utc_now()
    report = _make_report_skeleton(root, scope, started_at)
    local_report = Path(report_path)
    try:
        backlog = read_json(root / "IMPLEMENTATION_BACKLOG.json")
        owners = acceptance_owners(root)
        items, gates = validate_ledger(root, backlog, owners)
        selected_item_ids, required_case_ids, test_modules, prerequisites = _prepare_scope(
            root, selector_kind, selector_id, items, gates
        )
        if selector_kind == "item" and backlog.get("active_item") not in {None, selector_id}:
            raise VerificationError("active_item_mismatch")
        if selector_kind == "item":
            item = items[selector_id]
            if item.get("state") == "IN_PROGRESS" and backlog.get("active_item") != selector_id:
                raise VerificationError("active_item_mismatch")
        current_before = _current_identity(root)
        source_before = current_before["source_tree_sha256"]
        run_id = f"{selector_id.lower()}-{uuid4().hex[:12]}"
        evidence_local = Path("evidence") / "local"
        result_relative = evidence_local / f"pytest-{run_id}.json"
        log_directory = root / evidence_local / "logs"
        argv = [
            sys.executable,
            "-m", "pytest", "-q", "--tb=short", "--maxfail=1",
            "-p", "tools.pytest_acceptance",
            f"--acceptance-report={result_relative.as_posix()}",
            *test_modules.values(),
        ]
        command = run_command(
            argv,
            cwd=root,
            log_directory=log_directory,
            timeout_seconds=timeout_seconds,
            command_id=f"pytest-{run_id}",
        )
        command_display = {
            "id": "acceptance_tests",
            "argv": _safe_display_argv(argv, result_relative, root),
            "exit_code": command.exit_code,
            "error_code": command.error_code,
            "timed_out": command.timed_out,
            "elapsed_seconds": round(command.elapsed_seconds, 6),
            "stdout": {
                "path": Path(command.stdout_path).relative_to(root).as_posix() if command.stdout_path else None,
                "sha256": command.stdout_sha256,
                "bytes": command.stdout_bytes,
                "truncated": command.stdout_truncated,
            },
            "stderr": {
                "path": Path(command.stderr_path).relative_to(root).as_posix() if command.stderr_path else None,
                "sha256": command.stderr_sha256,
                "bytes": command.stderr_bytes,
                "truncated": command.stderr_truncated,
            },
        }
        report["commands"].append(command_display)
        report["items"] = selected_item_ids
        report["prerequisites"] = prerequisites
        errors: list[dict[str, str]] = [{"code": code} for code in command_error_codes(command)]
        result_file = root / result_relative
        parser_available = (root / "tools" / "pytest_acceptance.py").is_file()
        if not parser_available or not result_file.is_file():
            errors.append({"code": "pytest_report_unavailable"})
        else:
            try:
                counts, actual_cases = parse_pytest_report(result_file, required_case_ids, parser_available=parser_available)
                report["test_counts"] = counts
                report["acceptance_cases"] = actual_cases
            except VerificationError as error:
                errors.append(_safe_error(error))
            else:
                report["artifacts"].append({
                    "path": result_relative.as_posix(),
                    "sha256": sha256_file(result_file),
                    "size_bytes": result_file.stat().st_size,
                    "kind": "pytest_acceptance_receipt",
                })
        current_after = _current_identity(root)
        if current_after != current_before:
            errors.append({"code": "source_changed_during_run"})
        report.update(current_after)
        report["source_commit"] = source_commit(root)
        report["finished_at"] = utc_now()
        report["items"] = selected_item_ids
        report["prerequisites"] = prerequisites
        report["limitations"] = [
            "This receipt covers only the declared local acceptance scope and actual current platform.",
            "It does not establish cross-platform, release, camera-adapter, cultural-review or production-integration readiness.",
        ]
        report["errors"] = errors
        if not errors and report["test_counts"]["collected"] > 0:
            report["state"] = "VERIFIED"
            exit_code = 0
        else:
            report["state"] = "FAILED" if any(code["code"].startswith(("pytest_case", "pytest_nonzero", "pytest_zero", "command_exit", "command_output")) for code in errors) else "BLOCKED"
            exit_code = 1 if report["state"] == "FAILED" else 2
    except VerificationError as error:
        report["finished_at"] = utc_now()
        report["errors"] = [_safe_error(error)]
        report["state"] = "BLOCKED"
        exit_code = 2
    except Exception:
        report["finished_at"] = utc_now()
        report["errors"] = [{"code": "verification_error"}]
        report["state"] = "BLOCKED"
        exit_code = 2
    _write_report(root, local_report, report)
    sealed_report = seal_report(report)
    return exit_code, sealed_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execute a Mudra Interact Core acceptance item or gate.")
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--item")
    selector.add_argument("--gate")
    parser.add_argument("--report", required=True, help="Report path under evidence/local/")
    parser.add_argument("--root", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--timeout-seconds", type=float, default=180.0, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    root = Path(arguments.root).resolve() if arguments.root else Path(__file__).resolve().parents[1]
    scope_kind = "item" if arguments.item else "gate"
    scope_id = arguments.item or arguments.gate
    try:
        exit_code, report = execute_scope(
            root,
            scope_kind,
            scope_id,
            arguments.report,
            timeout_seconds=arguments.timeout_seconds,
        )
        print(json.dumps({"scope": report["scope"], "state": report["state"], "report_sha256": report["report_sha256"], "errors": report["errors"]}, sort_keys=True))
        return exit_code
    except VerificationError as error:
        print(json.dumps({"error": {"code": _safe_error(error)["code"]}}, sort_keys=True))
        return 2
    except Exception:
        print(json.dumps({"error": {"code": "verification_error"}}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
