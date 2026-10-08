"""Shared, dependency-free receipt and fixture checks for gate verification."""

from __future__ import annotations

import hashlib
import json
import math
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


REPORT_SCHEMA_VERSION = 1
REPORT_REQUIRED_FIELDS = {
    "report_schema_version",
    "scope",
    "state",
    "verification_kind",
    "source_commit",
    "source_tree_sha256",
    "spec_sha256",
    "acceptance_sha256",
    "tool_lock_sha256",
    "platform",
    "started_at",
    "finished_at",
    "commands",
    "test_counts",
    "acceptance_cases",
    "mutation_results",
    "artifacts",
    "prerequisites",
    "limitations",
    "errors",
    "items",
    "report_sha256",
}
_EXCLUDED_PARTS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    "build",
    "dist",
    "htmlcov",
    "evidence",
    ".pytest-language-tmp",
}


class VerificationError(Exception):
    """A safe machine-readable failure; the code never contains input data."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_text_bytes(contents: bytes) -> bytes:
    """Normalize Git's CRLF checkout conversion without altering binary data."""
    if b"\0" in contents:
        return contents
    try:
        contents.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return contents
    return contents.replace(b"\r\n", b"\n")


def sha256_text_file(path: Path) -> str:
    return sha256_bytes(canonical_text_bytes(path.read_bytes()))


def strict_json_bytes(data: bytes) -> Any:
    if data.startswith(b"\xef\xbb\xbf"):
        raise VerificationError("invalid_json")

    def pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise VerificationError("duplicate_json_key")
            result[key] = value
        return result

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise VerificationError("invalid_json_number")
        return parsed

    try:
        text = data.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=pairs_no_duplicates,
            parse_float=finite_float,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                VerificationError("invalid_json_number")
            ),
        )
        _reject_surrogates(value)
        return value
    except VerificationError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise VerificationError("invalid_json") from None


def _reject_surrogates(value: Any) -> None:
    if isinstance(value, str):
        if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
            raise VerificationError("invalid_unicode")
    elif isinstance(value, list):
        for item in value:
            _reject_surrogates(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _reject_surrogates(key)
            _reject_surrogates(item)


def read_json(path: Path, *, max_bytes: int = 2 * 1024 * 1024) -> Any:
    try:
        with path.open("rb") as stream:
            data = stream.read(max_bytes + 1)
    except OSError:
        raise VerificationError("file_unavailable") from None
    if len(data) > max_bytes:
        raise VerificationError("file_too_large")
    return strict_json_bytes(data)


def _fixture_path(root: Path, fixture_root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise VerificationError("fixture_path_invalid")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or "\\" in relative:
        raise VerificationError("fixture_path_invalid")
    candidate = fixture_root.joinpath(*posix.parts)
    try:
        resolved_root = fixture_root.resolve(strict=True)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(resolved_root)
    except (OSError, ValueError):
        raise VerificationError("fixture_missing_or_outside_root") from None
    current = candidate
    while current != fixture_root:
        if current.is_symlink():
            raise VerificationError("fixture_symlink_forbidden")
        current = current.parent
    if not resolved.is_file():
        raise VerificationError("fixture_not_regular_file")
    return resolved


def validate_fixture_manifest(
    root: Path,
    manifest_path: Path | None = None,
    *,
    known_case_ids: Iterable[str],
) -> list[dict[str, Any]]:
    root = root.resolve()
    manifest_path = manifest_path or root / "tests" / "fixtures" / "v2" / "manifest.json"
    try:
        manifest_path.resolve(strict=True).relative_to(root)
    except (OSError, ValueError):
        raise VerificationError("fixture_manifest_path_invalid") from None
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise VerificationError("fixture_manifest_path_invalid")
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or set(manifest) != {"manifest_version", "origin", "fixtures"}:
        raise VerificationError("fixture_manifest_shape")
    if manifest["manifest_version"] != 1 or manifest["origin"] != "synthetic":
        raise VerificationError("fixture_manifest_version_or_origin")
    records = manifest["fixtures"]
    if not isinstance(records, list) or not records:
        raise VerificationError("fixture_manifest_empty")
    case_ids = set(known_case_ids)
    fixture_ids: set[str] = set()
    paths: set[str] = set()
    validated: list[dict[str, Any]] = []
    fixture_root = manifest_path.parent.resolve()
    for record in records:
        expected_keys = {"fixture_id", "path", "sha256", "case_id", "expected", "origin"}
        if not isinstance(record, dict) or set(record) != expected_keys:
            raise VerificationError("fixture_record_shape")
        fixture_id = record["fixture_id"]
        relative = record["path"]
        case_id = record["case_id"]
        digest = record["sha256"]
        expected = record["expected"]
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id in fixture_ids:
            raise VerificationError("fixture_id_duplicate_or_invalid")
        if not isinstance(relative, str) or relative in paths:
            raise VerificationError("fixture_path_duplicate_or_invalid")
        if not isinstance(case_id, str) or case_id not in case_ids:
            raise VerificationError("fixture_case_unknown")
        if record["origin"] != "synthetic":
            raise VerificationError("fixture_origin_not_synthetic")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise VerificationError("fixture_digest_shape")
        if not isinstance(expected, dict) or not {"outcome", "schema", "expected_fields"}.issubset(expected):
            raise VerificationError("fixture_expectation_shape")
        if expected["outcome"] not in {"valid", "invalid"} or expected["schema"] not in {
            "Frame", "Recognition", "Event", "Catalogue", "Batch", "LocalReport"
        }:
            raise VerificationError("fixture_expectation_shape")
        if (
            not isinstance(expected["expected_fields"], list)
            or any(not isinstance(field, str) for field in expected["expected_fields"])
            or len(expected["expected_fields"]) != len(set(expected["expected_fields"]))
        ):
            raise VerificationError("fixture_expected_fields_shape")
        if expected["outcome"] == "invalid":
            if set(expected) != {"outcome", "schema", "expected_fields", "expected_error"}:
                raise VerificationError("fixture_expected_error_missing")
            if not isinstance(expected["expected_error"], str) or not expected["expected_error"]:
                raise VerificationError("fixture_expected_error_missing")
        elif set(expected) != {"outcome", "schema", "expected_fields"}:
            raise VerificationError("fixture_valid_has_error")
        file_path = _fixture_path(root, fixture_root, relative)
        if sha256_file(file_path) != digest:
            raise VerificationError("fixture_hash_mismatch")
        fixture_ids.add(fixture_id)
        paths.add(relative)
        validated.append({**record, "resolved_path": file_path})
    return validated


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8", errors="strict")
    except (TypeError, ValueError, UnicodeError):
        raise VerificationError("report_not_serializable") from None


def report_digest(report: dict[str, Any]) -> str:
    body = dict(report)
    body.pop("report_sha256", None)
    return sha256_bytes(canonical_json_bytes(body))


def seal_report(report: dict[str, Any]) -> dict[str, Any]:
    sealed = dict(report)
    sealed.pop("report_sha256", None)
    sealed["report_sha256"] = report_digest(sealed)
    return sealed


def validate_report_integrity(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict) or not REPORT_REQUIRED_FIELDS.issubset(report):
        raise VerificationError("report_shape_invalid")
    if report.get("report_schema_version") != REPORT_SCHEMA_VERSION:
        raise VerificationError("report_version_invalid")
    expected = report.get("report_sha256")
    if not isinstance(expected, str) or len(expected) != 64 or report_digest(report) != expected:
        raise VerificationError("report_hash_mismatch")
    if report.get("state") not in {"VERIFIED", "FAILED", "BLOCKED"}:
        raise VerificationError("report_shape_invalid")
    if report.get("verification_kind") != "luna_self_verified":
        raise VerificationError("report_shape_invalid")
    for key in ("source_tree_sha256", "spec_sha256", "acceptance_sha256", "tool_lock_sha256"):
        value = report.get(key)
        if not isinstance(value, str) or len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
            raise VerificationError("report_shape_invalid")
    if not isinstance(report.get("scope"), dict) or not isinstance(report.get("acceptance_cases"), list):
        raise VerificationError("report_shape_invalid")
    if not isinstance(report.get("commands"), list) or not isinstance(report.get("artifacts"), list):
        raise VerificationError("report_shape_invalid")
    return report


def validate_receipt_file(
    root: Path,
    relative_path: str,
    expected_sha256: str,
    *,
    expected_scope: dict[str, str] | None = None,
    required_case_ids: Iterable[str] = (),
    current_identity: dict[str, str] | None = None,
) -> dict[str, Any]:
    posix = PurePosixPath(relative_path)
    if posix.is_absolute() or ".." in posix.parts or "\\" in relative_path:
        raise VerificationError("receipt_path_invalid")
    path = root.joinpath(*posix.parts)
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(root.resolve())
    except (OSError, ValueError):
        raise VerificationError("receipt_missing_or_outside_root") from None
    if path.is_symlink() or not resolved.is_file():
        raise VerificationError("receipt_not_regular_file")
    if sha256_file(resolved) != expected_sha256:
        raise VerificationError("receipt_file_hash_mismatch")
    receipt = validate_report_integrity(read_json(resolved))
    if receipt.get("state") != "VERIFIED" or receipt.get("verification_kind") != "luna_self_verified":
        raise VerificationError("receipt_not_verified")
    if expected_scope is not None and receipt.get("scope") != expected_scope:
        raise VerificationError("receipt_scope_mismatch")
    actual_cases = {
        item.get("acceptance_id")
        for item in receipt.get("acceptance_cases", [])
        if isinstance(item, dict) and item.get("outcome") == "passed"
    }
    if not set(required_case_ids).issubset(actual_cases):
        raise VerificationError("receipt_acceptance_cases_missing")
    for artifact in receipt.get("artifacts", []):
        if not isinstance(artifact, dict) or not isinstance(artifact.get("path"), str):
            raise VerificationError("receipt_artifact_invalid")
        artifact_path = PurePosixPath(artifact["path"])
        if artifact_path.is_absolute() or ".." in artifact_path.parts or "\\" in artifact["path"]:
            raise VerificationError("receipt_artifact_invalid")
        full_artifact = root.joinpath(*artifact_path.parts)
        try:
            resolved_artifact = full_artifact.resolve(strict=True)
            resolved_artifact.relative_to(root.resolve())
        except (OSError, ValueError):
            raise VerificationError("receipt_artifact_missing") from None
        if full_artifact.is_symlink() or not resolved_artifact.is_file():
            raise VerificationError("receipt_artifact_invalid")
        if sha256_file(resolved_artifact) != artifact.get("sha256"):
            raise VerificationError("receipt_artifact_hash_mismatch")
        if resolved_artifact.stat().st_size != artifact.get("size_bytes"):
            raise VerificationError("receipt_artifact_size_mismatch")
    if current_identity:
        for key, value in current_identity.items():
            if receipt.get(key) != value:
                raise VerificationError("receipt_stale")
    return receipt


def tracked_source_files(root: Path) -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError("source_inventory_unavailable") from None
    if result.returncode != 0:
        raise VerificationError("source_inventory_unavailable")
    selected: list[Path] = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        try:
            rel = raw.decode("utf-8", errors="strict").replace("\\", "/")
        except UnicodeError:
            raise VerificationError("source_path_invalid") from None
        parts = PurePosixPath(rel).parts
        if not parts or any(part in _EXCLUDED_PARTS or part.endswith(".egg-info") for part in parts):
            continue
        if rel == "IMPLEMENTATION_BACKLOG.json" or rel.endswith(".pyc"):
            continue
        path = root.joinpath(*parts)
        if path.is_symlink():
            raise VerificationError("source_symlink_forbidden")
        if not path.is_file():
            continue
        selected.append(path)
    return sorted(selected, key=lambda path: path.relative_to(root).as_posix())


def source_tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in tracked_source_files(root):
        rel = path.relative_to(root).as_posix().encode("utf-8")
        contents = canonical_text_bytes(path.read_bytes())
        digest.update(len(rel).to_bytes(4, "big"))
        digest.update(rel)
        digest.update(len(contents).to_bytes(8, "big"))
        digest.update(contents)
    return digest.hexdigest()


def source_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            text=True,
            encoding="ascii",
        )
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationError("source_commit_unavailable") from None
    if result.returncode != 0:
        raise VerificationError("source_commit_unavailable")
    return result.stdout.strip()
