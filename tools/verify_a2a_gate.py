"""Fail-closed current-source verifier for Mudra A2A interoperability (ML-06)."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.verification_report import (  # noqa: E402
    VerificationError,
    canonical_json_bytes,
    read_json,
    report_digest,
    seal_report,
    sha256_file,
    sha256_text_file,
    source_commit,
    source_tree_sha256,
    safe_subprocess_environment,
)


ITEM_ID = "ML-06"
REQUIRED_CASES = {"L50", "L51", "L52", "L53"}
ACCEPTANCE_PATH = "docs/COMMUNICATION_LANGUAGE_ACCEPTANCE.md"
CONTRACT_PATH = "docs/A2A_INTEROPERABILITY_CONTRACT.md"
LANGUAGE_CONTRACT_PATH = "docs/COMMUNICATION_LANGUAGE_CONTRACT.md"
LOCK_PATH = "requirements-dev.lock"
MAX_REPORT_BYTES = 2 * 1024 * 1024
MAX_LOG_BYTES = 512 * 1024
_EXPECTED_LIMITATIONS = [
    "Independent loopback peer only; no public third-party agent or production host qualification.",
    "Human-to-human is schema-only; no human study, user interface, or accessibility/community review is claimed.",
    "The deterministic provider-unavailable result is injected; no model/provider or paid operation is called.",
]
_REPORT_FIELDS = {
    "report_schema_version", "scope", "state", "verification_kind", "source_commit",
    "source_tree_sha256", "acceptance_sha256", "contract_sha256", "tool_lock_sha256",
    "platform", "started_at", "finished_at", "commands", "test_counts",
    "acceptance_cases", "artifacts", "limitations", "errors", "report_sha256",
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _valid_utc_timestamp(value: Any) -> bool:
    if type(value) is not str:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == UTC.utcoffset(parsed)


def _identity(root: Path) -> dict[str, str]:
    return {
        "source_commit": source_commit(root),
        "source_tree_sha256": source_tree_sha256(root),
        "acceptance_sha256": sha256_text_file(root / ACCEPTANCE_PATH),
        "contract_sha256": sha256_text_file(root / CONTRACT_PATH),
        "tool_lock_sha256": sha256_text_file(root / LOCK_PATH),
    }


def _clean_tree(root: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain", "--untracked-files=all"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            env=safe_subprocess_environment(),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError("a2a_git_status_unavailable") from None
    if result.returncode != 0:
        raise VerificationError("a2a_git_status_unavailable")
    return not result.stdout.strip()


def _is_ancestor(root: Path, commit: str) -> bool:
    if type(commit) is not str or len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            env=safe_subprocess_environment(),
        )
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError("a2a_git_ancestry_unavailable") from None
    return result.returncode == 0


def _safe_output_path(root: Path, relative: str) -> Path:
    if type(relative) is not str or not relative or "\\" in relative:
        raise VerificationError("a2a_report_path_invalid")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts:
        raise VerificationError("a2a_report_path_invalid")
    path = root.joinpath(*posix.parts)
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        raise VerificationError("a2a_report_path_invalid") from None
    current = path
    while current != root and current != current.parent:
        if current.is_symlink():
            raise VerificationError("a2a_report_symlink_forbidden")
        current = current.parent
    return path


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=".ml06-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _parse_pytest_report(document: Any) -> tuple[dict[str, int], list[dict[str, str]]]:
    if (
        type(document) is not dict
        or set(document) != {
            "report_schema_version", "complete", "pytest_exit_status", "started_at",
            "finished_at", "collected_count", "nodes",
        }
        or document["report_schema_version"] != 1
        or document["complete"] is not True
        or type(document["pytest_exit_status"]) is not int
        or type(document["collected_count"]) is not int
        or document["collected_count"] <= 0
        or not _valid_utc_timestamp(document["started_at"])
        or not _valid_utc_timestamp(document["finished_at"])
        or not isinstance(document["nodes"], list)
        or not document["nodes"]
        or document["collected_count"] != len(document["nodes"])
    ):
        raise VerificationError("a2a_pytest_report_shape")
    try:
        if datetime.fromisoformat(document["finished_at"].replace("Z", "+00:00")) < datetime.fromisoformat(document["started_at"].replace("Z", "+00:00")):
            raise VerificationError("a2a_pytest_report_shape")
    except ValueError:
        raise VerificationError("a2a_pytest_report_shape") from None
    counts = {"collected": len(document["nodes"]), "passed": 0, "failed": 0,
              "skipped": 0, "xfailed": 0, "xpassed": 0}
    cases: list[dict[str, str]] = []
    seen_nodes: set[str] = set()
    found_cases: set[str] = set()
    for node in document["nodes"]:
        if (
            type(node) is not dict
            or set(node) != {"node_id", "acceptance_id", "parameter_id", "parameters", "phases", "outcome"}
            or type(node["node_id"]) is not str or not node["node_id"]
            or node["node_id"] in seen_nodes
            or type(node["acceptance_id"]) is not str
            or node["acceptance_id"] not in REQUIRED_CASES
            or (node["parameter_id"] is not None and type(node["parameter_id"]) is not str)
            or type(node["parameters"]) is not dict
            or type(node["phases"]) is not list
            or not node["phases"]
            or type(node["outcome"]) is not str
            or node["outcome"] not in {"passed", "failed", "skipped", "xfailed", "xpassed", "not_executed"}
        ):
            raise VerificationError("a2a_pytest_node_invalid")
        seen_nodes.add(node["node_id"])
        found_cases.add(node["acceptance_id"])
        if node["outcome"] != "passed":
            counts[node["outcome"] if node["outcome"] in counts else "failed"] += 1
        else:
            counts["passed"] += 1
        phases = node["phases"]
        if (
            any(
                type(phase) is not dict
                or set(phase) != {"phase", "outcome"}
                or type(phase["phase"]) is not str
                or phase["phase"] not in {"setup", "call", "teardown"}
                or phase["outcome"] != "passed"
                for phase in phases
            )
            or {phase["phase"] for phase in phases} != {"setup", "call", "teardown"}
        ):
            raise VerificationError("a2a_pytest_phase_invalid")
        cases.append({
            "acceptance_id": node["acceptance_id"],
            "outcome": node["outcome"],
            "node_id": node["node_id"],
        })
    if found_cases != REQUIRED_CASES or counts["passed"] != counts["collected"]:
        raise VerificationError("a2a_acceptance_incomplete")
    if document["pytest_exit_status"] != 0:
        raise VerificationError("a2a_pytest_nonzero_exit")
    return counts, cases


def _check_receipt(root: Path, report_path: Path) -> dict[str, Any]:
    try:
        report_path.resolve(strict=True).relative_to(root.resolve(strict=True))
    except (OSError, ValueError):
        raise VerificationError("a2a_report_path_invalid") from None
    if report_path.is_symlink() or not report_path.is_file():
        raise VerificationError("a2a_receipt_missing")
    if not report_path.relative_to(root).as_posix().startswith("evidence/language/"):
        raise VerificationError("a2a_report_path_invalid")
    report = read_json(report_path, max_bytes=MAX_REPORT_BYTES)
    counts = report.get("test_counts") if type(report) is dict else None
    cases = report.get("acceptance_cases") if type(report) is dict else None
    commands = report.get("commands") if type(report) is dict else None
    platform_info = report.get("platform") if type(report) is dict else None
    if (
        type(report) is not dict
        or set(report) != _REPORT_FIELDS
        or report.get("report_sha256") != report_digest(report)
        or report["scope"] != {"kind": "item", "id": ITEM_ID}
        or report["state"] != "VERIFIED"
        or report["verification_kind"] != "luna_self_verified"
        or report["errors"] != []
        or type(counts) is not dict
        or set(counts) != {"collected", "passed", "failed", "skipped", "xfailed", "xpassed"}
        or any(type(value) is not int or value < 0 for value in counts.values())
        or counts["collected"] < len(REQUIRED_CASES)
        or counts["collected"] != counts["passed"]
        or any(counts[key] != 0 for key in ("failed", "skipped", "xfailed", "xpassed"))
        or type(cases) is not list
        or len(cases) != counts["collected"]
        or any(
            type(case) is not dict
            or set(case) != {"acceptance_id", "outcome", "node_id"}
            or type(case["acceptance_id"]) is not str
            or case["acceptance_id"] not in REQUIRED_CASES
            or case["outcome"] != "passed"
            or type(case["node_id"]) is not str
            or not case["node_id"]
            for case in cases
        )
        or {case["acceptance_id"] for case in cases} != REQUIRED_CASES
        or len({case["node_id"] for case in cases}) != len(cases)
        or type(commands) is not list
        or len(commands) != 1
        or type(commands[0]) is not dict
        or set(commands[0]) != {"id", "argv", "exit_code"}
        or commands[0]["id"] != "ml06_a2a_acceptance"
        or type(commands[0]["argv"]) is not list
        or any(type(value) is not str for value in commands[0]["argv"])
        or "pytest" not in commands[0]["argv"]
        or "tests/test_a2a_interop.py" not in commands[0]["argv"]
        or "tests/test_a2a_verification.py" not in commands[0]["argv"]
        or type(commands[0]["exit_code"]) is not int
        or commands[0]["exit_code"] != 0
        or type(platform_info) is not dict
        or set(platform_info) != {"os", "architecture", "python"}
        or any(type(value) is not str or not value for value in platform_info.values())
        or report.get("limitations") != _EXPECTED_LIMITATIONS
        or not _valid_utc_timestamp(report.get("started_at"))
        or not _valid_utc_timestamp(report.get("finished_at"))
        or not isinstance(report.get("source_commit"), str)
        or any(
            not isinstance(report.get(key), str)
            or re.fullmatch(r"[0-9a-f]{64}", report[key]) is None
            for key in ("source_tree_sha256", "acceptance_sha256", "contract_sha256", "tool_lock_sha256")
        )
    ):
        raise VerificationError("a2a_receipt_not_verified")
    try:
        started = datetime.fromisoformat(report["started_at"].replace("Z", "+00:00"))
        finished = datetime.fromisoformat(report["finished_at"].replace("Z", "+00:00"))
    except ValueError:
        raise VerificationError("a2a_receipt_not_verified") from None
    if (
        started.tzinfo is None or finished.tzinfo is None
        or started.utcoffset() != UTC.utcoffset(started)
        or finished.utcoffset() != UTC.utcoffset(finished)
        or finished < started
    ):
        raise VerificationError("a2a_receipt_not_verified")
    identity = _identity(root)
    if (
        not _is_ancestor(root, report.get("source_commit"))
        or any(report.get(key) != value for key, value in identity.items() if key != "source_commit")
    ):
        raise VerificationError("a2a_receipt_stale")
    artifacts = report["artifacts"]
    if type(artifacts) is not list or len(artifacts) != 2:
        raise VerificationError("a2a_receipt_artifacts_invalid")
    kinds: set[str] = set()
    for artifact in artifacts:
        if (
            type(artifact) is not dict
            or set(artifact) != {"kind", "path", "sha256", "size_bytes"}
            or type(artifact["kind"]) is not str
            or artifact["kind"] not in {"acceptance_report", "command_log"}
            or artifact["kind"] in kinds
            or type(artifact["path"]) is not str
            or type(artifact["size_bytes"]) is not int or artifact["size_bytes"] < 0
            or type(artifact["sha256"]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"]) is None
            or not artifact["path"].startswith("evidence/language/")
        ):
            raise VerificationError("a2a_receipt_artifact_invalid")
        path = _safe_output_path(root, artifact["path"])
        if not path.is_file() or path.is_symlink() or path.stat().st_size != artifact["size_bytes"]:
            raise VerificationError("a2a_receipt_artifact_missing")
        if sha256_file(path) != artifact["sha256"]:
            raise VerificationError("a2a_receipt_artifact_hash_mismatch")
        kinds.add(artifact["kind"])
    if kinds != {"acceptance_report", "command_log"}:
        raise VerificationError("a2a_receipt_artifacts_invalid")
    return report


def run_ml06(root: Path, report_path: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    report_path = report_path.resolve(strict=False)
    try:
        report_relative = report_path.relative_to(root).as_posix()
    except ValueError:
        raise VerificationError("a2a_report_path_invalid") from None
    if not report_relative.startswith("evidence/language/"):
        raise VerificationError("a2a_report_path_invalid")
    if not _clean_tree(root):
        raise VerificationError("a2a_candidate_not_committed_clean")
    acceptance_path = _safe_output_path(root, report_relative.replace(".json", "-pytest.json"))
    log_path = _safe_output_path(root, report_relative.replace(".json", ".log"))
    for destination in (report_path, acceptance_path, log_path):
        destination.parent.mkdir(parents=True, exist_ok=True)
    identity_before = _identity(root)
    started = _utc_now()
    temp_directory = tempfile.TemporaryDirectory(prefix="mudra-ml06-")
    fd, temporary_report_name = tempfile.mkstemp(prefix="ml06-pytest-", suffix=".json", dir=temp_directory.name)
    os.close(fd)
    temporary_report = Path(temporary_report_name)
    argv = [
        sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance",
        "--basetemp", "<isolated-temporary-directory>",
        "tests/test_a2a_interop.py", "tests/test_a2a_verification.py",
        "--acceptance-report", "<temporary-acceptance-report>",
    ]
    actual_argv = [
        sys.executable, "-m", "pytest", "-p", "tools.pytest_acceptance",
        "--basetemp", temp_directory.name,
        "tests/test_a2a_interop.py", "tests/test_a2a_verification.py",
        "--acceptance-report", str(temporary_report),
    ]
    try:
        completed = subprocess.run(
            actual_argv,
            cwd=root,
            env=safe_subprocess_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise VerificationError("a2a_pytest_timeout") from None
    except OSError:
        raise VerificationError("a2a_pytest_launch_failed") from None
    log = b"STDOUT\n" + completed.stdout + b"\nSTDERR\n" + completed.stderr
    if len(log) > MAX_LOG_BYTES:
        _write_atomic(log_path, log[:MAX_LOG_BYTES])
        raise VerificationError("a2a_pytest_log_too_large")
    _write_atomic(log_path, log)
    if completed.returncode != 0 or not temporary_report.is_file():
        raise VerificationError("a2a_pytest_failed")
    try:
        pytest_document = read_json(temporary_report, max_bytes=MAX_REPORT_BYTES)
        counts, cases = _parse_pytest_report(pytest_document)
    except VerificationError:
        raise
    _write_atomic(acceptance_path, canonical_json_bytes(pytest_document))
    identity_after = _identity(root)
    if identity_after != identity_before:
        raise VerificationError("a2a_source_changed_during_run")
    report = {
        "report_schema_version": 1,
        "scope": {"kind": "item", "id": ITEM_ID},
        "state": "VERIFIED",
        "verification_kind": "luna_self_verified",
        **identity_after,
        "platform": {
            "os": platform.system().lower(),
            "architecture": platform.machine().lower(),
            "python": platform.python_version(),
        },
        "started_at": started,
        "finished_at": _utc_now(),
        "commands": [{"id": "ml06_a2a_acceptance", "argv": argv, "exit_code": completed.returncode}],
        "test_counts": counts,
        "acceptance_cases": cases,
        "artifacts": [
            {"kind": "acceptance_report", "path": acceptance_path.relative_to(root).as_posix(),
             "sha256": sha256_file(acceptance_path), "size_bytes": acceptance_path.stat().st_size},
            {"kind": "command_log", "path": log_path.relative_to(root).as_posix(),
             "sha256": sha256_file(log_path), "size_bytes": log_path.stat().st_size},
        ],
        "limitations": _EXPECTED_LIMITATIONS,
        "errors": [],
    }
    if set(report) | {"report_sha256"} != _REPORT_FIELDS:
        raise VerificationError("a2a_internal_report_shape")
    sealed = seal_report(report)
    _write_atomic(report_path, canonical_json_bytes(sealed))
    temp_directory.cleanup()
    return _check_receipt(root, report_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", help="Write the ML-06 receipt at this repository-relative path")
    parser.add_argument("--check-receipt", help="Validate a previous ML-06 receipt")
    args = parser.parse_args()
    try:
        if bool(args.report) == bool(args.check_receipt):
            raise VerificationError("a2a_cli_arguments_invalid")
        target = args.report or args.check_receipt
        path = _safe_output_path(_ROOT, target)
        report = run_ml06(_ROOT, path) if args.report else _check_receipt(_ROOT, path)
        print(json.dumps({
            "scope": report["scope"], "state": report["state"],
            "source_commit": report["source_commit"], "report_sha256": report["report_sha256"],
        }, sort_keys=True))
        return 0
    except VerificationError as exc:
        print(json.dumps({"scope": {"id": ITEM_ID}, "state": "BLOCKED", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
