"""Fail-closed verifier for the separate Mudra language acceptance series."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.verification_report import (  # noqa: E402
    REPORT_SCHEMA_VERSION,
    VerificationError,
    canonical_json_bytes,
    canonical_text_bytes,
    read_json,
    seal_report,
    sha256_bytes,
    sha256_file,
    sha256_text_file,
    source_commit,
    tracked_source_files,
    validate_report_integrity,
)


ACCEPTANCE_PATH = "docs/COMMUNICATION_LANGUAGE_ACCEPTANCE.md"
CONTRACT_PATH = "docs/COMMUNICATION_LANGUAGE_CONTRACT.md"
LOCK_PATH = "requirements-dev.lock"
SCHEMA_PATH = "src/mudra_interact_core/schemas/language/v1/language.schema.json"
VERSION_MAP_PATH = "src/mudra_interact_core/schemas/language/v1/version-map.json"
FIXTURE_MANIFEST_PATH = "tests/fixtures/language/v1/manifest.json"
CASE_PATTERN = re.compile(r"^\|\s*(L\d{2})\s*\|")
REQUIRED_ML01_CASES = {"L01", "L02", "L03"}
REQUIRED_ML02_CASES = {"L10", "L11", "L12", "L13"}
REQUIRED_ML03_CASES = {"L20", "L21", "L22", "L23"}
REQUIRED_CASES_BY_ITEM = {
    "ML-01": REQUIRED_ML01_CASES,
    "ML-02": REQUIRED_ML02_CASES,
    "ML-03": REQUIRED_ML03_CASES,
}
COMMAND_ID_BY_ITEM = {
    "ML-01": "ml01_acceptance",
    "ML-02": "ml02_acceptance",
    "ML-03": "ml03_acceptance",
}
PREREQUISITES_BY_ITEM = {
    "ML-01": (),
    "ML-02": ("ML-01",),
    "ML-03": ("ML-02",),
}
KNOWN_DIRECTIONS = {
    "human_to_human",
    "human_to_agent",
    "agent_to_human",
    "agent_to_agent",
}
KNOWN_ACTS = {
    "request", "proposal", "clarification", "accept", "decline",
    "acknowledge", "status", "result", "error",
}
MAX_TEST_REPORT_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 512 * 1024
LANGUAGE_IDENTITY_FIELDS = (
    "source_tree_sha256",
    "spec_sha256",
    "acceptance_sha256",
    "tool_lock_sha256",
    "schema_sha256",
    "version_map_sha256",
    "fixture_manifest_sha256",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def known_case_ids(root: Path = _ROOT) -> set[str]:
    try:
        lines = (root / ACCEPTANCE_PATH).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError):
        raise VerificationError("language_acceptance_unavailable") from None
    found = [match.group(1) for line in lines if (match := CASE_PATTERN.match(line))]
    if not found or len(found) != len(set(found)):
        raise VerificationError("language_acceptance_invalid")
    return set(found)


def _safe_repo_file(root: Path, relative: str, *, parent: Path | None = None) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise VerificationError("language_path_invalid")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise VerificationError("language_path_invalid")
    base = (parent or root).resolve(strict=True)
    candidate = base.joinpath(*posix.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(base)
    except (OSError, ValueError):
        raise VerificationError("language_file_missing_or_outside_root") from None
    current = candidate
    while current != base:
        if current.is_symlink():
            raise VerificationError("language_symlink_forbidden")
        current = current.parent
    if not resolved.is_file():
        raise VerificationError("language_file_not_regular")
    return resolved


def _pointer_value(value: Any, pointer: str) -> Any:
    if not isinstance(pointer, str) or not pointer.startswith("/") or pointer == "/":
        raise VerificationError("language_fixture_pointer_invalid")
    current = value
    for raw_part in pointer[1:].split("/"):
        if "~" in raw_part and re.search(r"~(?![01])", raw_part):
            raise VerificationError("language_fixture_pointer_invalid")
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isascii() and part.isdigit():
            index = int(part)
            if index >= len(current):
                raise VerificationError("language_fixture_pointer_invalid")
            current = current[index]
        else:
            raise VerificationError("language_fixture_pointer_invalid")
    return current


def validate_language_fixture_manifest(
    root: Path = _ROOT,
    manifest_path: Path | None = None,
) -> list[dict[str, Any]]:
    root = root.resolve()
    manifest_path = manifest_path or root / FIXTURE_MANIFEST_PATH
    try:
        manifest_path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        raise VerificationError("language_manifest_path_invalid") from None
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise VerificationError("language_manifest_path_invalid")
    manifest = read_json(manifest_path, max_bytes=MAX_TEST_REPORT_BYTES)
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"manifest_version", "origin", "fixtures"}
        or manifest.get("manifest_version") != 1
        or manifest.get("origin") != "synthetic"
    ):
        raise VerificationError("language_manifest_shape")
    records = manifest["fixtures"]
    if not isinstance(records, list) or not records:
        raise VerificationError("language_manifest_empty")
    known = known_case_ids(root)
    seen_ids: set[str] = set()
    seen_refs: set[tuple[str, str]] = set()
    output: list[dict[str, Any]] = []
    fixture_root = manifest_path.parent.resolve(strict=True)
    expected_keys = {
        "fixture_id", "path", "pointer", "case_id", "direction", "act",
        "expected_outcome", "origin", "sha256",
    }
    for record in records:
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise VerificationError("language_fixture_record_shape")
        fixture_id = record["fixture_id"]
        relative = record["path"]
        pointer = record["pointer"]
        case_id = record["case_id"]
        direction = record["direction"]
        act = record["act"]
        outcome = record["expected_outcome"]
        digest = record["sha256"]
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id in seen_ids:
            raise VerificationError("language_fixture_id_invalid")
        if not isinstance(case_id, str) or case_id not in known:
            raise VerificationError("language_fixture_case_unknown")
        if record["origin"] != "synthetic":
            raise VerificationError("language_fixture_origin_invalid")
        if not isinstance(act, str):
            raise VerificationError("language_fixture_act_invalid")
        if not isinstance(direction, str) or direction not in KNOWN_DIRECTIONS:
            raise VerificationError("language_fixture_direction_invalid")
        if not isinstance(outcome, str) or outcome not in {"valid", "invalid"}:
            raise VerificationError("language_fixture_outcome_invalid")
        if case_id == "L01" and (not isinstance(act, str) or act not in KNOWN_ACTS):
            raise VerificationError("language_fixture_act_invalid")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise VerificationError("language_fixture_digest_invalid")
        if not isinstance(relative, str) or not isinstance(pointer, str):
            raise VerificationError("language_fixture_pointer_invalid")
        ref = (relative, pointer)
        if ref in seen_refs:
            raise VerificationError("language_fixture_duplicate_reference")
        path = _safe_repo_file(root, relative, parent=fixture_root)
        if sha256_file(path) != digest:
            raise VerificationError("language_fixture_hash_mismatch")
        bundle = read_json(path, max_bytes=MAX_TEST_REPORT_BYTES)
        fixture = _pointer_value(bundle, pointer)
        if not isinstance(fixture, dict):
            raise VerificationError("language_fixture_not_object")
        seen_ids.add(fixture_id)
        seen_refs.add(ref)
        output.append({**record, "resolved_path": path, "value": fixture})
    if not {"L01", "L02"}.issubset({item["case_id"] for item in output}):
        raise VerificationError("language_fixture_cases_missing")
    return output


def validate_local_schema_references(schema: Any) -> None:
    if not isinstance(schema, dict):
        raise VerificationError("language_schema_shape")
    if schema.get("$id") != "urn:allyk:mudra-interact:language:1.0.0":
        raise VerificationError("language_schema_id_invalid")

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"$ref", "$dynamicRef", "$recursiveRef"}:
                    if not isinstance(child, str) or not child.startswith("#/"):
                        raise VerificationError("language_remote_schema_reference")
                    target: Any = schema
                    for raw_part in child[2:].split("/"):
                        if "~" in raw_part and re.search(r"~(?![01])", raw_part):
                            raise VerificationError("language_schema_reference_unresolved")
                        part = raw_part.replace("~1", "/").replace("~0", "~")
                        if not isinstance(target, dict) or part not in target:
                            raise VerificationError("language_schema_reference_unresolved")
                        target = target[part]
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(schema)


def parse_language_pytest_document(
    document: Any,
    required_case_ids: Iterable[str] = REQUIRED_ML01_CASES,
) -> tuple[dict[str, int], list[dict[str, str]]]:
    expected = set(required_case_ids)
    if not expected or not expected.issubset(known_case_ids()):
        raise VerificationError("language_required_cases_invalid")
    required_fields = {
        "report_schema_version", "complete", "pytest_exit_status", "collected_count", "nodes"
    }
    if not isinstance(document, dict) or not required_fields.issubset(document):
        raise VerificationError("language_pytest_report_invalid")
    if type(document["report_schema_version"]) is not int or document["report_schema_version"] != 1 or document["complete"] is not True:
        raise VerificationError("language_pytest_report_incomplete")
    if type(document["pytest_exit_status"]) is not int or document["pytest_exit_status"] != 0:
        raise VerificationError("language_pytest_nonzero_exit")
    nodes = document["nodes"]
    if (
        not isinstance(nodes, list)
        or not nodes
        or type(document["collected_count"]) is not int
        or document["collected_count"] != len(nodes)
    ):
        raise VerificationError("language_pytest_zero_or_mismatched_collection")

    seen_node_ids: set[str] = set()
    found_ids: set[str] = set()
    cases: list[dict[str, str]] = []
    counts = {"collected": len(nodes), "passed": 0, "failed": 0, "skipped": 0, "xfailed": 0, "xpassed": 0}
    for node in nodes:
        if not isinstance(node, dict):
            raise VerificationError("language_pytest_node_invalid")
        node_id = node.get("node_id")
        acceptance_id = node.get("acceptance_id")
        outcome = node.get("outcome")
        phases = node.get("phases")
        if not isinstance(node_id, str) or not node_id or node_id in seen_node_ids:
            raise VerificationError("language_pytest_node_duplicate_or_invalid")
        if not isinstance(acceptance_id, str) or acceptance_id not in expected:
            raise VerificationError("language_pytest_case_unknown_or_missing")
        if not isinstance(outcome, str) or outcome not in counts:
            raise VerificationError("language_pytest_outcome_invalid")
        if not isinstance(phases, list) or not phases:
            raise VerificationError("language_pytest_phases_invalid")
        phase_map: dict[str, str] = {}
        for phase in phases:
            if (
                not isinstance(phase, dict)
                or set(phase) != {"phase", "outcome"}
                or not isinstance(phase.get("phase"), str)
                or phase.get("phase") not in {"setup", "call", "teardown"}
                or phase.get("phase") in phase_map
                or not isinstance(phase.get("outcome"), str)
                or phase.get("outcome") not in {"passed", "failed", "skipped", "xfailed", "xpassed"}
            ):
                raise VerificationError("language_pytest_phases_invalid")
            phase_map[phase["phase"]] = phase["outcome"]
        if set(phase_map) != {"setup", "call", "teardown"} or any(v != "passed" for v in phase_map.values()):
            raise VerificationError("language_pytest_case_not_passed")
        if outcome != "passed":
            raise VerificationError("language_pytest_case_not_passed")
        seen_node_ids.add(node_id)
        found_ids.add(acceptance_id)
        counts[outcome] += 1
        cases.append({"acceptance_id": acceptance_id, "outcome": outcome, "node_id": node_id})
    missing = expected - found_ids
    if missing:
        raise VerificationError("language_pytest_case_missing")
    return counts, cases


def _validate_report_shape(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or not isinstance(report.get("state"), str):
        raise VerificationError("language_receipt_shape_invalid")
    report = validate_report_integrity(report)
    scope = report.get("scope")
    if (
        not isinstance(scope, dict)
        or set(scope) != {"kind", "id"}
        or scope.get("kind") != "item"
        or type(scope.get("id")) is not str
        or scope["id"] not in REQUIRED_CASES_BY_ITEM
    ):
        raise VerificationError("language_receipt_scope_invalid")
    item_id = scope["id"]
    required_case_ids = REQUIRED_CASES_BY_ITEM[item_id]
    if report.get("state") != "VERIFIED":
        raise VerificationError("language_receipt_not_verified")
    for key in ("schema_sha256", "version_map_sha256", "fixture_manifest_sha256"):
        if not isinstance(report.get(key), str) or not re.fullmatch(r"[0-9a-f]{64}", report[key]):
            raise VerificationError("language_receipt_identity_invalid")
    if report.get("items") != [item_id]:
        raise VerificationError("language_receipt_item_invalid")
    prerequisites = report.get("prerequisites")
    expected_prerequisites = PREREQUISITES_BY_ITEM[item_id]
    if not isinstance(prerequisites, list) or len(prerequisites) != len(expected_prerequisites):
        raise VerificationError("language_receipt_prerequisites_invalid")
    for prerequisite, expected_id in zip(prerequisites, expected_prerequisites):
        if (
            not isinstance(prerequisite, dict)
            or set(prerequisite) != {"id", "state", "receipt_path", "receipt_sha256"}
            or prerequisite.get("id") != expected_id
            or prerequisite.get("state") != "VERIFIED"
            or prerequisite.get("receipt_path") != f"evidence/language/{expected_id}.json"
            or not isinstance(prerequisite.get("receipt_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", prerequisite["receipt_sha256"])
        ):
            raise VerificationError("language_receipt_prerequisites_invalid")
    counts = report.get("test_counts")
    if not isinstance(counts, dict) or set(counts) != {"collected", "passed", "failed", "skipped", "xfailed", "xpassed"}:
        raise VerificationError("language_receipt_counts_invalid")
    if any(type(value) is not int or value < 0 for value in counts.values()):
        raise VerificationError("language_receipt_counts_invalid")
    if (
        counts["collected"] <= 0
        or counts["collected"] != counts["passed"]
        or any(counts[key] != 0 for key in ("failed", "skipped", "xfailed", "xpassed"))
    ):
        raise VerificationError("language_receipt_counts_invalid")
    cases = report.get("acceptance_cases")
    if not isinstance(cases, list) or not cases:
        raise VerificationError("language_receipt_cases_missing")
    found: set[str] = set()
    for case in cases:
        if (
            not isinstance(case, dict)
            or set(case) != {"acceptance_id", "outcome", "node_id"}
            or not isinstance(case.get("acceptance_id"), str)
            or case.get("acceptance_id") not in required_case_ids
            or case.get("outcome") != "passed"
            or not isinstance(case.get("node_id"), str)
        ):
            raise VerificationError("language_receipt_case_invalid")
        found.add(case["acceptance_id"])
    if found != required_case_ids:
        raise VerificationError("language_receipt_cases_missing")
    artifacts = report.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise VerificationError("language_receipt_evidence_missing")
    acceptance_artifacts = [artifact for artifact in artifacts if isinstance(artifact, dict) and artifact.get("kind") == "acceptance_report"]
    log_artifacts = [artifact for artifact in artifacts if isinstance(artifact, dict) and artifact.get("kind") == "command_log"]
    if len(acceptance_artifacts) != 1 or len(log_artifacts) != 1 or len(artifacts) != 2:
        raise VerificationError("language_receipt_evidence_missing")
    commands = report.get("commands")
    expected_command_id = COMMAND_ID_BY_ITEM[item_id]
    if (
        not isinstance(commands, list)
        or len(commands) != 1
        or not isinstance(commands[0], dict)
        or commands[0].get("id") != expected_command_id
        or not isinstance(commands[0].get("argv"), list)
        or any(not isinstance(argument, str) for argument in commands[0]["argv"])
        or commands[0].get("log_path") != log_artifacts[0].get("path")
        or type(commands[0].get("exit_code")) is not int
        or commands[0]["exit_code"] != 0
        or any(
            type(commands[0].get(key)) is not int or commands[0][key] < 0
            for key in ("stdout_bytes", "stderr_bytes")
        )
        or any(
            not isinstance(commands[0].get(key), str)
            or not re.fullmatch(r"[0-9a-f]{64}", commands[0][key])
            for key in ("stdout_sha256", "stderr_sha256")
        )
    ):
        raise VerificationError("language_receipt_command_invalid")
    return report


def compare_identity(receipt: dict[str, Any], current: dict[str, str]) -> None:
    for key in LANGUAGE_IDENTITY_FIELDS:
        if receipt.get(key) != current.get(key):
            raise VerificationError("language_receipt_stale")


def validate_language_receipt_files(
    root: Path,
    report_path: Path,
    *,
    current_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    try:
        report_path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        raise VerificationError("language_receipt_path_invalid") from None
    if report_path.is_symlink() or not report_path.is_file():
        raise VerificationError("language_receipt_path_invalid")
    report = _validate_report_shape(read_json(report_path, max_bytes=MAX_TEST_REPORT_BYTES))
    if current_identity is not None:
        compare_identity(report, current_identity)
    artifacts = report["artifacts"]
    pytest_artifact = next(artifact for artifact in artifacts if artifact.get("kind") == "acceptance_report")
    for artifact in artifacts:
        if not isinstance(artifact, dict) or set(artifact) != {"kind", "path", "sha256", "size_bytes"}:
            raise VerificationError("language_receipt_artifact_invalid")
        if (
            type(artifact.get("size_bytes")) is not int
            or artifact["size_bytes"] < 0
            or not isinstance(artifact.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
        ):
            raise VerificationError("language_receipt_artifact_invalid")
        path = _safe_repo_file(root, artifact["path"])
        if sha256_file(path) != artifact["sha256"] or path.stat().st_size != artifact["size_bytes"]:
            raise VerificationError("language_receipt_artifact_hash_mismatch")
    pytest_path = _safe_repo_file(root, pytest_artifact["path"])
    item_id = report["scope"]["id"]
    actual_counts, actual_cases = parse_language_pytest_document(
        read_json(pytest_path, max_bytes=MAX_TEST_REPORT_BYTES),
        required_case_ids=REQUIRED_CASES_BY_ITEM[item_id],
    )
    if actual_counts != report["test_counts"] or actual_cases != report["acceptance_cases"]:
        raise VerificationError("language_receipt_evidence_mismatch")
    return report


def language_source_tree_sha256(root: Path = _ROOT) -> str:
    """Hash all source inventory files except the mutable language status ledger."""
    digest = hashlib.sha256()
    for path in tracked_source_files(root):
        if path.relative_to(root).as_posix() == "docs/COMMUNICATION_LANGUAGE_BACKLOG.json":
            continue
        relative = path.relative_to(root).as_posix().encode("utf-8")
        contents = canonical_text_bytes(path.read_bytes())
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def _git_working_tree_clean(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0 and not result.stdout.strip()


def _is_ancestor(root: Path, commit: str) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def current_language_identity(root: Path = _ROOT) -> dict[str, str]:
    paths = {
        "spec_sha256": CONTRACT_PATH,
        "acceptance_sha256": ACCEPTANCE_PATH,
        "tool_lock_sha256": LOCK_PATH,
        "schema_sha256": SCHEMA_PATH,
        "version_map_sha256": VERSION_MAP_PATH,
        "fixture_manifest_sha256": FIXTURE_MANIFEST_PATH,
    }
    result = {
        "source_commit": source_commit(root),
        "source_tree_sha256": language_source_tree_sha256(root),
    }
    for key, relative in paths.items():
        path = _safe_repo_file(root, relative)
        result[key] = sha256_text_file(path)
    return result


def _report_path(root: Path, relative: str) -> Path:
    root = root.resolve(strict=True)
    if not isinstance(relative, str) or "\\" in relative:
        raise VerificationError("language_report_path_invalid")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or posix.parts[:2] != ("evidence", "language"):
        raise VerificationError("language_report_path_invalid")
    path = root.joinpath(*posix.parts)
    current = root
    try:
        for part in posix.parts[:-1]:
            current = current / part
            if current.is_symlink():
                raise VerificationError("language_report_path_invalid")
            if current.exists() and not current.is_dir():
                raise VerificationError("language_report_path_invalid")
            current.resolve().relative_to(root)
        path.parent.resolve().relative_to(root)
    except (OSError, ValueError):
        raise VerificationError("language_report_path_invalid") from None
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise VerificationError("language_report_path_invalid")
    return path


def _atomic_bytes(path: Path, encoded: bytes) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise VerificationError("language_report_path_invalid")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=".language-report-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_bytes(path, canonical_json_bytes(value))


def run_ml01(root: Path, report_path: Path) -> dict[str, Any]:
    root = root.resolve()
    if not _git_working_tree_clean(root):
        raise VerificationError("language_candidate_not_committed_clean")
    validate_local_schema_references(read_json(root / SCHEMA_PATH))
    validate_language_fixture_manifest(root)
    identity_before = current_language_identity(root)
    started = utc_now()
    acceptance_path = report_path.with_name(report_path.stem + "-pytest.json")
    log_path = report_path.with_suffix(".log")
    for output_path in (acceptance_path, log_path):
        try:
            relative_output = output_path.relative_to(root).as_posix()
        except ValueError:
            raise VerificationError("language_report_path_invalid") from None
        if _report_path(root, relative_output) != output_path:
            raise VerificationError("language_report_path_invalid")
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_report_name = tempfile.mkstemp(prefix=".pytest-language-", suffix=".json", dir=acceptance_path.parent)
    os.close(fd)
    temp_report = Path(temp_report_name)
    pytest_temp = tempfile.TemporaryDirectory(prefix="mudra-language-acceptance-")
    try:
        argv = [
            sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance",
            "--basetemp", pytest_temp.name,
            "tests/test_language_contract.py", "tests/test_language_verification.py",
            "--acceptance-report", str(temp_report),
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise VerificationError("language_pytest_timeout") from None
        except OSError:
            raise VerificationError("language_pytest_launch_failed") from None
        log = b"STDOUT\n" + proc.stdout + b"\nSTDERR\n" + proc.stderr
        if len(log) > MAX_LOG_BYTES:
            _atomic_bytes(log_path, log[:MAX_LOG_BYTES])
            raise VerificationError("language_pytest_log_truncated")
        _atomic_bytes(log_path, log)
        if not temp_report.is_file():
            raise VerificationError("language_pytest_report_missing")
        pytest_document = read_json(temp_report, max_bytes=MAX_TEST_REPORT_BYTES)
        counts, cases = parse_language_pytest_document(pytest_document)
        if proc.returncode != 0:
            raise VerificationError("language_pytest_nonzero_exit")
        os.replace(temp_report, acceptance_path)
        identity_after = current_language_identity(root)
        if identity_after != identity_before:
            raise VerificationError("language_source_changed_during_run")
        artifacts = [{
            "kind": "acceptance_report",
            "path": acceptance_path.relative_to(root).as_posix(),
            "sha256": sha256_file(acceptance_path),
            "size_bytes": acceptance_path.stat().st_size,
        }, {
            "kind": "command_log",
            "path": log_path.relative_to(root).as_posix(),
            "sha256": sha256_file(log_path),
            "size_bytes": log_path.stat().st_size,
        }]
        report: dict[str, Any] = {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "scope": {"kind": "item", "id": "ML-01"},
            "state": "VERIFIED",
            "verification_kind": "luna_self_verified",
            **identity_after,
            "platform": {
                "os": platform.system().lower(),
                "architecture": platform.machine().lower(),
                "python": platform.python_version(),
            },
            "started_at": started,
            "finished_at": utc_now(),
            "commands": [{
                "id": "ml01_acceptance",
                "argv": [sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance", "--basetemp", "<isolated-temporary-directory>", "tests/test_language_contract.py", "tests/test_language_verification.py", "--acceptance-report", acceptance_path.relative_to(root).as_posix()],
                "exit_code": proc.returncode,
                "stdout_sha256": sha256_bytes(proc.stdout),
                "stderr_sha256": sha256_bytes(proc.stderr),
                "stdout_bytes": len(proc.stdout),
                "stderr_bytes": len(proc.stderr),
                "log_path": log_path.relative_to(root).as_posix(),
            }],
            "test_counts": counts,
            "acceptance_cases": cases,
            "mutation_results": [],
            "artifacts": artifacts,
            "prerequisites": [],
            "limitations": ["Synthetic schema and reporter evidence only; no runtime implementation or human qualification is claimed."],
            "errors": [],
            "items": ["ML-01"],
        }
    except VerificationError as exc:
        raise exc
    finally:
        try:
            temp_report.unlink(missing_ok=True)
        except OSError:
            pass
        pytest_temp.cleanup()
    return report


def run_ml02(root: Path, report_path: Path) -> dict[str, Any]:
    root = root.resolve()
    if not _git_working_tree_clean(root):
        raise VerificationError("language_candidate_not_committed_clean")
    prerequisite_path = _report_path(root, "evidence/language/ML-01.json")
    prerequisite = check_receipt(root, prerequisite_path)
    if prerequisite["state"] != "VERIFIED":
        raise VerificationError("language_prerequisite_unverified")
    validate_local_schema_references(read_json(root / SCHEMA_PATH))
    validate_language_fixture_manifest(root)
    identity_before = current_language_identity(root)
    started = utc_now()
    acceptance_path = report_path.with_name(report_path.stem + "-pytest.json")
    log_path = report_path.with_suffix(".log")
    for output_path in (acceptance_path, log_path):
        try:
            relative_output = output_path.relative_to(root).as_posix()
        except ValueError:
            raise VerificationError("language_report_path_invalid") from None
        if _report_path(root, relative_output) != output_path:
            raise VerificationError("language_report_path_invalid")
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_report_name = tempfile.mkstemp(prefix=".pytest-language-", suffix=".json", dir=acceptance_path.parent)
    os.close(fd)
    temp_report = Path(temp_report_name)
    pytest_temp = tempfile.TemporaryDirectory(prefix="mudra-language-acceptance-")
    try:
        argv = [
            sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance",
            "--basetemp", pytest_temp.name,
            "tests/test_language_runtime.py",
            "--acceptance-report", str(temp_report),
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise VerificationError("language_pytest_timeout") from None
        except OSError:
            raise VerificationError("language_pytest_launch_failed") from None
        log = b"STDOUT\n" + proc.stdout + b"\nSTDERR\n" + proc.stderr
        if len(log) > MAX_LOG_BYTES:
            _atomic_bytes(log_path, log[:MAX_LOG_BYTES])
            raise VerificationError("language_pytest_log_truncated")
        _atomic_bytes(log_path, log)
        if not temp_report.is_file():
            raise VerificationError("language_pytest_report_missing")
        pytest_document = read_json(temp_report, max_bytes=MAX_TEST_REPORT_BYTES)
        counts, cases = parse_language_pytest_document(pytest_document, required_case_ids=REQUIRED_ML02_CASES)
        if proc.returncode != 0:
            raise VerificationError("language_pytest_nonzero_exit")
        os.replace(temp_report, acceptance_path)
        identity_after = current_language_identity(root)
        if identity_after != identity_before:
            raise VerificationError("language_source_changed_during_run")
        artifacts = [{
            "kind": "acceptance_report",
            "path": acceptance_path.relative_to(root).as_posix(),
            "sha256": sha256_file(acceptance_path),
            "size_bytes": acceptance_path.stat().st_size,
        }, {
            "kind": "command_log",
            "path": log_path.relative_to(root).as_posix(),
            "sha256": sha256_file(log_path),
            "size_bytes": log_path.stat().st_size,
        }]
        return {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "scope": {"kind": "item", "id": "ML-02"},
            "state": "VERIFIED",
            "verification_kind": "luna_self_verified",
            **identity_after,
            "platform": {
                "os": platform.system().lower(),
                "architecture": platform.machine().lower(),
                "python": platform.python_version(),
            },
            "started_at": started,
            "finished_at": utc_now(),
            "commands": [{
                "id": "ml02_acceptance",
                "argv": [sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance", "--basetemp", "<isolated-temporary-directory>", "tests/test_language_runtime.py", "--acceptance-report", acceptance_path.relative_to(root).as_posix()],
                "exit_code": proc.returncode,
                "stdout_sha256": sha256_bytes(proc.stdout),
                "stderr_sha256": sha256_bytes(proc.stderr),
                "stdout_bytes": len(proc.stdout),
                "stderr_bytes": len(proc.stderr),
                "log_path": log_path.relative_to(root).as_posix(),
            }],
            "test_counts": counts,
            "acceptance_cases": cases,
            "mutation_results": [],
            "artifacts": artifacts,
            "prerequisites": [{
                "id": "ML-01",
                "state": "VERIFIED",
                "receipt_path": prerequisite_path.relative_to(root).as_posix(),
                "receipt_sha256": sha256_file(prerequisite_path),
            }],
            "limitations": ["Structural message parsing and freshness only; transcript validation, rendering, human qualification, transport adapters and authorization are not claimed."],
            "errors": [],
            "items": ["ML-02"],
        }
    except VerificationError as exc:
        raise exc
    finally:
        try:
            temp_report.unlink(missing_ok=True)
        except OSError:
            pass
        pytest_temp.cleanup()


def run_ml03(root: Path, report_path: Path) -> dict[str, Any]:
    root = root.resolve()
    if not _git_working_tree_clean(root):
        raise VerificationError("language_candidate_not_committed_clean")
    prerequisite_path = _report_path(root, "evidence/language/ML-02.json")
    prerequisite = check_receipt(root, prerequisite_path)
    if prerequisite["state"] != "VERIFIED":
        raise VerificationError("language_prerequisite_unverified")

    identity_before = current_language_identity(root)
    started = utc_now()
    acceptance_path = report_path.with_name(report_path.stem + "-pytest.json")
    log_path = report_path.with_suffix(".log")
    for output_path in (acceptance_path, log_path):
        try:
            relative_output = output_path.relative_to(root).as_posix()
        except ValueError:
            raise VerificationError("language_report_path_invalid") from None
        if _report_path(root, relative_output) != output_path:
            raise VerificationError("language_report_path_invalid")
    acceptance_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_report_name = tempfile.mkstemp(prefix=".pytest-language-", suffix=".json", dir=acceptance_path.parent)
    os.close(fd)
    temp_report = Path(temp_report_name)
    pytest_temp = tempfile.TemporaryDirectory(prefix="mudra-language-acceptance-")
    try:
        argv = [
            sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance",
            "--basetemp", pytest_temp.name,
            "tests/test_language_transcript.py",
            "--acceptance-report", str(temp_report),
        ]
        try:
            proc = subprocess.run(
                argv,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise VerificationError("language_pytest_timeout") from None
        except OSError:
            raise VerificationError("language_pytest_launch_failed") from None
        log = b"STDOUT\n" + proc.stdout + b"\nSTDERR\n" + proc.stderr
        if len(log) > MAX_LOG_BYTES:
            _atomic_bytes(log_path, log[:MAX_LOG_BYTES])
            raise VerificationError("language_pytest_log_truncated")
        _atomic_bytes(log_path, log)
        if not temp_report.is_file():
            raise VerificationError("language_pytest_report_missing")
        pytest_document = read_json(temp_report, max_bytes=MAX_TEST_REPORT_BYTES)
        counts, cases = parse_language_pytest_document(
            pytest_document, required_case_ids=REQUIRED_ML03_CASES,
        )
        if proc.returncode != 0:
            raise VerificationError("language_pytest_nonzero_exit")
        os.replace(temp_report, acceptance_path)
        identity_after = current_language_identity(root)
        if identity_after != identity_before:
            raise VerificationError("language_source_changed_during_run")
        artifacts = [{
            "kind": "acceptance_report",
            "path": acceptance_path.relative_to(root).as_posix(),
            "sha256": sha256_file(acceptance_path),
            "size_bytes": acceptance_path.stat().st_size,
        }, {
            "kind": "command_log",
            "path": log_path.relative_to(root).as_posix(),
            "sha256": sha256_file(log_path),
            "size_bytes": log_path.stat().st_size,
        }]
        return {
            "report_schema_version": REPORT_SCHEMA_VERSION,
            "scope": {"kind": "item", "id": "ML-03"},
            "state": "VERIFIED",
            "verification_kind": "luna_self_verified",
            **identity_after,
            "platform": {
                "os": platform.system().lower(),
                "architecture": platform.machine().lower(),
                "python": platform.python_version(),
            },
            "started_at": started,
            "finished_at": utc_now(),
            "commands": [{
                "id": "ml03_acceptance",
                "argv": [sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance", "--basetemp", "<isolated-temporary-directory>", "tests/test_language_transcript.py", "--acceptance-report", acceptance_path.relative_to(root).as_posix()],
                "exit_code": proc.returncode,
                "stdout_sha256": sha256_bytes(proc.stdout),
                "stderr_sha256": sha256_bytes(proc.stderr),
                "stdout_bytes": len(proc.stdout),
                "stderr_bytes": len(proc.stderr),
                "log_path": log_path.relative_to(root).as_posix(),
            }],
            "test_counts": counts,
            "acceptance_cases": cases,
            "mutation_results": [],
            "artifacts": artifacts,
            "prerequisites": [{
                "id": "ML-02",
                "state": "VERIFIED",
                "receipt_path": prerequisite_path.relative_to(root).as_posix(),
                "receipt_sha256": sha256_file(prerequisite_path),
            }],
            "limitations": ["Bounded transcript validation and deterministic plain-text rendering only; no identity, authorization, transport, execution, model/provider calls, live host plugin or human qualification is claimed."],
            "errors": [],
            "items": ["ML-03"],
        }
    finally:
        try:
            temp_report.unlink(missing_ok=True)
        except OSError:
            pass
        pytest_temp.cleanup()


def check_receipt(root: Path, path: Path) -> dict[str, Any]:
    current = current_language_identity(root)
    receipt = validate_language_receipt_files(root, path, current_identity=current)
    if not _is_ancestor(root, receipt["source_commit"]):
        raise VerificationError("language_receipt_commit_not_ancestor")
    validate_language_fixture_manifest(root)
    for prerequisite in receipt["prerequisites"]:
        prerequisite_path = _report_path(root, prerequisite["receipt_path"])
        if sha256_file(prerequisite_path) != prerequisite["receipt_sha256"]:
            raise VerificationError("language_prerequisite_receipt_stale")
        prerequisite_receipt = check_receipt(root, prerequisite_path)
        if prerequisite_receipt["state"] != "VERIFIED":
            raise VerificationError("language_prerequisite_unverified")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--item", choices=["ML-01", "ML-02", "ML-03"])
    group.add_argument("--check-receipt")
    parser.add_argument("--report", help="Repository-relative receipt path under evidence/language")
    args = parser.parse_args(argv)
    try:
        if args.check_receipt:
            path = _report_path(_ROOT, args.check_receipt)
            receipt = check_receipt(_ROOT, path)
            print(f"VERIFIED {receipt['scope']['id']} receipt")
            return 0
        if not args.report:
            parser.error("--report is required with --item")
        path = _report_path(_ROOT, args.report)
        runner = {"ML-01": run_ml01, "ML-02": run_ml02, "ML-03": run_ml03}[args.item]
        report = runner(_ROOT, path)
        _atomic_json(path, seal_report(report))
        print(f"VERIFIED {args.item}: {report['test_counts']['passed']} acceptance tests; 0 skips")
        return 0
    except VerificationError as exc:
        print(f"BLOCKED: {exc.code}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
