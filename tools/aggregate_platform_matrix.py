"""Fail-closed aggregation of actual MI-08 platform receipts."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.verification_report import (  # noqa: E402
    REPORT_SCHEMA_VERSION,
    VerificationError,
    canonical_json_bytes,
    read_json,
    seal_report,
    sha256_bytes,
    sha256_file,
    sha256_text_file,
    source_commit,
    source_tree_sha256,
    validate_receipt_file,
    validate_report_integrity,
)
from tools.verify_release import (  # noqa: E402
    REQUIRED_PLATFORMS,
    REQUIRED_PYTHONS,
    current_platform,
)


REQUIRED_CASES = tuple(f"E{number}" for number in range(73, 85))
EXPECTED_CELLS = tuple(
    (os_name, architecture, python_version)
    for os_name, architecture in REQUIRED_PLATFORMS
    for python_version in REQUIRED_PYTHONS
)
DIGEST = re.compile(r"^[0-9a-f]{64}$")
COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize_os(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.lower()
    if name == "darwin":
        name = "macos"
    return name if name in {item[0] for item in REQUIRED_PLATFORMS} else None


def _normalize_architecture(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    name = value.lower()
    if name in {"amd64", "x64"}:
        name = "x86_64"
    elif name in {"aarch64", "arm64"}:
        name = "arm64"
    return name if name in {item[1] for item in REQUIRED_PLATFORMS} else None


def _python_minor(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r"^(\d+\.\d+)(?:\.\d+.*)?$", value)
    return match.group(1) if match else None


def _current_identity(root: Path) -> dict[str, str]:
    return {
        "source_tree_sha256": source_tree_sha256(root),
        "spec_sha256": sha256_text_file(root / "MUDRA_INTERACT_CORE_SPEC.md"),
        "acceptance_sha256": sha256_text_file(root / "docs" / "ACCEPTANCE.md"),
        "tool_lock_sha256": sha256_text_file(root / "requirements-dev.lock"),
    }


def _commit_is_ancestor(root: Path, candidate: str, head: str) -> bool:
    if not COMMIT.fullmatch(candidate) or not COMMIT.fullmatch(head):
        return False
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", candidate, head],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def aggregate_receipt_documents(
    receipts: Iterable[tuple[str, str, dict[str, Any]]],
    *,
    current_identity: dict[str, str],
    candidate_is_ancestor: bool | None,
    collector_platform: dict[str, str],
    collector_commit: str,
    started_at: str | None = None,
    command: list[str] | None = None,
    input_errors: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate one exact receipt for each required OS/Python cell."""
    started = started_at or now()
    errors = list(input_errors or [])
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    commits: set[str] = set()
    for relative_path, file_digest, raw_report in receipts:
        if not DIGEST.fullmatch(file_digest):
            errors.append({"code": "receipt_file_digest_invalid"})
            continue
        try:
            report = validate_report_integrity(raw_report)
        except VerificationError:
            errors.append({"code": "receipt_invalid"})
            continue
        if sha256_bytes(canonical_json_bytes(report)) != file_digest:
            errors.append({"code": "receipt_file_digest_mismatch"})
            continue
        if report.get("scope") != {"kind": "item", "id": "MI-08"}:
            errors.append({"code": "receipt_scope_mismatch"})
            continue
        if report.get("state") != "VERIFIED":
            errors.append({"code": "receipt_not_verified"})
            continue
        if any(report.get(key) != value for key, value in current_identity.items()):
            errors.append({"code": "receipt_stale"})
            continue
        commit = report.get("source_commit")
        if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
            errors.append({"code": "receipt_source_commit_invalid"})
            continue
        commits.add(commit)
        platform_info = report.get("platform")
        if not isinstance(platform_info, dict):
            errors.append({"code": "receipt_platform_invalid"})
            continue
        cell = (
            _normalize_os(platform_info.get("os")),
            _normalize_architecture(platform_info.get("architecture")),
            _python_minor(platform_info.get("python")),
        )
        if None in cell or cell not in EXPECTED_CELLS:
            errors.append({"code": "receipt_platform_unexpected"})
            continue
        counts = report.get("test_counts")
        cases = report.get("acceptance_cases")
        valid_case_entries = (
            isinstance(cases, list)
            and all(
                isinstance(item, dict)
                and item.get("acceptance_id") in REQUIRED_CASES
                and item.get("outcome") == "passed"
                for item in cases
            )
        )
        actual_cases = (
            {item["acceptance_id"] for item in cases}
            if valid_case_entries
            else set()
        )
        valid_counts = isinstance(counts, dict) and all(
            type(counts.get(name)) is int
            for name in ("collected", "passed", "failed", "skipped", "xfailed", "xpassed")
        )
        if (
            not valid_counts
            or not valid_case_entries
            or counts["collected"] != len(cases)
            or counts["collected"] < len(REQUIRED_CASES)
            or counts["passed"] != counts["collected"]
            or counts.get("failed") != 0
            or counts.get("skipped") != 0
            or counts.get("xfailed") != 0
            or counts.get("xpassed") != 0
            or actual_cases != set(REQUIRED_CASES)
        ):
            errors.append({"code": "receipt_acceptance_cases_invalid"})
            continue
        row = {
            "os": cell[0],
            "architecture": cell[1],
            "python": cell[2],
            "state": "VERIFIED",
            "receipt_path": relative_path,
            "receipt_sha256": file_digest,
            "receipt_report_sha256": report["report_sha256"],
            "acceptance_cases_passed": len(actual_cases),
            "source_commit": commit,
        }
        if cell in seen:
            errors.append({"code": "duplicate_platform_cell"})
            continue
        seen[cell] = row

    if len(commits) > 1:
        errors.append({"code": "platform_receipt_source_mismatch"})
    candidate = next(iter(commits)) if len(commits) == 1 else collector_commit
    if candidate_is_ancestor is False:
        errors.append({"code": "platform_receipt_source_not_in_history"})
    missing = [cell for cell in EXPECTED_CELLS if cell not in seen]
    ordered_rows = [
        seen.get(cell, {
            "os": cell[0],
            "architecture": cell[1],
            "python": cell[2],
            "state": "BLOCKED",
            "receipt_path": None,
            "receipt_sha256": None,
            "receipt_report_sha256": None,
            "acceptance_cases_passed": 0,
            "source_commit": None,
        })
        for cell in EXPECTED_CELLS
    ]
    state = "FAILED" if errors else "BLOCKED" if missing else "VERIFIED"
    limitations = [
        f"missing_platform_cell:{os_name}/{architecture}/python-{python_version}"
        for os_name, architecture, python_version in missing
    ]
    report = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "scope": {"kind": "platform_matrix", "id": "M3"},
        "state": state,
        "verification_kind": "luna_self_verified",
        "source_commit": candidate,
        **current_identity,
        "platform": collector_platform,
        "started_at": started,
        "finished_at": now(),
        "commands": [{"argv": command or ["python", "tools/aggregate_platform_matrix.py"], "exit": 0 if state == "VERIFIED" else 2}],
        "test_counts": {"required_platform_cells": len(EXPECTED_CELLS), "verified_platform_cells": len(seen)},
        "acceptance_cases": [],
        "mutation_results": [],
        "artifacts": [],
        "prerequisites": ["MI-07", "MI-08 locked verification tools"],
        "limitations": limitations,
        "errors": errors,
        "items": ["MI-08"],
        "matrix": {
            "required_cells": len(EXPECTED_CELLS),
            "verified_cells": len(seen),
            "missing_cells": len(missing),
            "cells": ordered_rows,
        },
        "report_sha256": "",
    }
    return seal_report(report)


def _safe_relative_path(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or "\\" in value or not relative.parts:
        raise VerificationError("report_path_invalid")
    return relative


def _reject_symlink_components(root: Path, relative: PurePosixPath, code: str) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise VerificationError(code)
    try:
        current.resolve(strict=False).relative_to(root.resolve())
    except (OSError, ValueError):
        raise VerificationError(code) from None
    return current


def aggregate_directory(
    root: Path,
    receipt_directory: str,
    report_path: str,
) -> dict[str, Any]:
    receipt_relative = _safe_relative_path(receipt_directory)
    output_relative = _safe_relative_path(report_path)
    if output_relative.parts[:2] != ("evidence", "local"):
        raise VerificationError("report_path_invalid")
    receipt_root = _reject_symlink_components(root, receipt_relative, "receipt_directory_unavailable")
    try:
        receipt_root.resolve(strict=True).relative_to(root.resolve())
    except (OSError, ValueError):
        raise VerificationError("receipt_directory_unavailable") from None
    if receipt_root.is_symlink() or not receipt_root.is_dir():
        raise VerificationError("receipt_directory_unavailable")

    identity = _current_identity(root)
    head = source_commit(root)
    loaded: list[tuple[str, str, dict[str, Any]]] = []
    input_errors: list[dict[str, str]] = []
    for path in sorted(receipt_root.glob("*.json"), key=lambda item: item.name):
        relative = path.relative_to(root).as_posix()
        try:
            digest = sha256_file(path)
            receipt = validate_receipt_file(
                root,
                relative,
                digest,
                expected_scope={"kind": "item", "id": "MI-08"},
                required_case_ids=REQUIRED_CASES,
                current_identity=identity,
            )
        except VerificationError as exc:
            input_errors.append({"code": exc.code})
            continue
        loaded.append((relative, digest, receipt))
    candidate = loaded[0][2]["source_commit"] if loaded else head
    candidate_is_ancestor = _commit_is_ancestor(root, candidate, head)
    command = [
        "python", "tools/aggregate_platform_matrix.py",
        "--receipt-dir", receipt_relative.as_posix(),
        "--report", output_relative.as_posix(),
    ]
    return aggregate_receipt_documents(
        loaded,
        current_identity=identity,
        candidate_is_ancestor=candidate_is_ancestor,
        collector_platform=current_platform(),
        collector_commit=head,
        command=command,
        input_errors=input_errors,
    )


def validate_aggregate_report(
    root: Path,
    relative_path: str,
    *,
    current_identity: dict[str, str],
    current_commit: str,
) -> dict[str, Any]:
    relative = _safe_relative_path(relative_path)
    if relative.parts[:2] != ("evidence", "local"):
        raise VerificationError("platform_matrix_report_invalid")
    path = _reject_symlink_components(root, relative, "platform_matrix_report_invalid")
    report = validate_report_integrity(read_json(path))
    if report.get("scope") != {"kind": "platform_matrix", "id": "M3"}:
        raise VerificationError("platform_matrix_report_invalid")
    if report.get("state") != "VERIFIED":
        raise VerificationError("platform_matrix_unavailable")
    if any(report.get(key) != value for key, value in current_identity.items()):
        raise VerificationError("platform_matrix_report_stale")
    if not _commit_is_ancestor(root, report.get("source_commit", ""), current_commit):
        raise VerificationError("platform_matrix_report_stale")
    matrix = report.get("matrix")
    cells = matrix.get("cells") if isinstance(matrix, dict) else None
    if not isinstance(cells, list) or len(cells) != len(EXPECTED_CELLS):
        raise VerificationError("platform_matrix_incomplete")
    actual: list[tuple[str, str, str]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            raise VerificationError("platform_matrix_incomplete")
        cell_key = (cell.get("os"), cell.get("architecture"), cell.get("python"))
        if (
            any(not isinstance(value, str) for value in cell_key)
            or cell.get("state") != "VERIFIED"
            or not isinstance(cell.get("receipt_path"), str)
            or not isinstance(cell.get("receipt_sha256"), str)
            or not DIGEST.fullmatch(cell.get("receipt_sha256", ""))
            or not isinstance(cell.get("receipt_report_sha256"), str)
            or not DIGEST.fullmatch(cell.get("receipt_report_sha256", ""))
            or cell.get("acceptance_cases_passed") != len(REQUIRED_CASES)
            or cell.get("source_commit") != report.get("source_commit")
        ):
            raise VerificationError("platform_matrix_incomplete")
        receipt_path = _safe_relative_path(cell["receipt_path"])
        if receipt_path.parts[:3] != ("evidence", "local", "mi08-platform-receipts"):
            raise VerificationError("platform_matrix_incomplete")
        actual.append(cell_key)
    if (
        len(actual) != len(cells)
        or len(set(actual)) != len(EXPECTED_CELLS)
        or set(actual) != set(EXPECTED_CELLS)
        or matrix.get("required_cells") != len(EXPECTED_CELLS)
        or matrix.get("verified_cells") != len(EXPECTED_CELLS)
        or matrix.get("missing_cells") != 0
    ):
        raise VerificationError("platform_matrix_incomplete")
    return report


def write_report(root: Path, relative_path: str, report: dict[str, Any]) -> None:
    relative = _safe_relative_path(relative_path)
    if relative.parts[:2] != ("evidence", "local"):
        raise VerificationError("report_path_invalid")
    destination = _reject_symlink_components(root, relative, "report_path_invalid")
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(canonical_json_bytes(report))
    except (OSError, ValueError):
        raise VerificationError("report_path_invalid") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt-dir", required=True, help="Directory with the eight MI-08 runner receipts")
    parser.add_argument("--report", required=True, help="Aggregate report path under evidence/local/")
    args = parser.parse_args(argv)
    try:
        report = aggregate_directory(ROOT, args.receipt_dir, args.report)
        write_report(ROOT, args.report, report)
        print(json.dumps({
            "scope": report["scope"],
            "state": report["state"],
            "report_sha256": report["report_sha256"],
            "verified_cells": report["matrix"]["verified_cells"],
            "required_cells": report["matrix"]["required_cells"],
            "errors": report["errors"],
        }, sort_keys=True))
        return 0 if report["state"] == "VERIFIED" else 2 if report["state"] == "BLOCKED" else 1
    except VerificationError as exc:
        print(json.dumps({"error": {"code": exc.code}}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
