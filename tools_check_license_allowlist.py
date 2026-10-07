"""Validate the exact licence and byte inventory of the distributable tree.

This is a release evidence check, not a legal-compliance certification. The
validator never adds an asset or expands the allowlist. ``--write-inventory``
is an explicit maintainer operation used after a deliberate source change;
ordinary validation only compares the committed inventory with actual bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


ROOT = Path(__file__).resolve().parent
POLICY = ROOT / "licenses" / "approved_components.json"
DEFAULT_INVENTORY = ROOT / "licenses" / "shipped_inventory.json"
POLICY_VERSION = "1.0.0"
INVENTORY_VERSION = "1.0.0"
ALLOWED_STATUSES = frozenset({"included", "approved_in_principle_pending_model_asset_review", "approved_in_principle_pending_distribution_review"})
EXCLUDED_PARTS = frozenset({".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "evidence", "tests"})


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def _safe_relative(value: Any) -> str | None:
    if type(value) is not str or not value:
        return None
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or "\\" in value or value.startswith("./"):
        return None
    return posix.as_posix()


def _tracked_or_present_files(root: Path) -> list[Path]:
    """Return the source/distribution files that a source release ships."""

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if result.returncode != 0:
            candidates = list(root.rglob("*"))
        else:
            candidates = [root.joinpath(*PurePosixPath(raw.decode("utf-8")).parts) for raw in result.stdout.split(b"\0") if raw]
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        candidates = []
        for candidate in root.rglob("*"):
            try:
                candidates.append(candidate)
            except OSError:
                continue
    selected: list[Path] = []
    for path in candidates:
        try:
            relative = path.relative_to(root).as_posix()
        except ValueError:
            continue
        parts = PurePosixPath(relative).parts
        if not parts or any(part in EXCLUDED_PARTS or part.endswith(".egg-info") for part in parts):
            continue
        if relative == "IMPLEMENTATION_BACKLOG.json" or relative.endswith(".pyc"):
            continue
        if path.is_symlink() or not path.is_file():
            continue
        selected.append(path)
    return sorted(selected, key=lambda item: item.relative_to(root).as_posix())


def _policy_errors(payload: Any) -> tuple[list[str], dict[str, dict[str, Any]], str | None]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["policy_missing_or_malformed"], {}, None
    required = {"policy_version", "approved_spdx_licenses", "release_rule", "components", "blocked_examples", "inventory_path"}
    if set(payload) != required or payload.get("policy_version") != POLICY_VERSION:
        errors.append("policy_missing_or_malformed")
    allowlist = payload.get("approved_spdx_licenses")
    if type(allowlist) is not list or not allowlist or any(type(value) is not str or not value for value in allowlist) or len(allowlist) != len(set(allowlist or [])):
        errors.append("policy_allowlist_invalid")
        allowed: set[str] = set()
    else:
        allowed = set(allowlist)
    components = payload.get("components")
    by_name: dict[str, dict[str, Any]] = {}
    if type(components) is not list or not components:
        errors.append("component_inventory_missing")
        components = []
    for component in components:
        expected = {"name", "kind", "license", "status", "notice_required"}
        if not isinstance(component, dict) or set(component) != expected:
            errors.append("component_record_malformed")
            continue
        name = component["name"]
        if type(name) is not str or not name or name in by_name:
            errors.append("component_name_invalid_or_duplicate")
            continue
        if component["status"] not in ALLOWED_STATUSES:
            errors.append("component_status_unknown")
        if type(component["license"]) is not str or not component["license"]:
            errors.append("component_license_unknown")
        elif component["license"] not in allowed:
            errors.append("component_license_not_allowlisted")
        if type(component["notice_required"]) is not bool:
            errors.append("component_notice_flag_invalid")
        by_name[name] = component
    if "Mudra Interact Core" not in by_name:
        errors.append("core_component_missing")
    elif by_name["Mudra Interact Core"].get("status") != "included":
        errors.append("core_component_not_included")
    inventory_path = _safe_relative(payload.get("inventory_path"))
    if inventory_path is None:
        errors.append("inventory_path_invalid")
    return errors, by_name, inventory_path


def _inventory_errors(root: Path, inventory_path: str | None, components: dict[str, dict[str, Any]], allowed: set[str]) -> list[str]:
    errors: list[str] = []
    if inventory_path is None:
        return ["inventory_missing_or_malformed"]
    path = root.joinpath(*PurePosixPath(inventory_path).parts)
    payload = _read_json(path)
    if not isinstance(payload, dict) or set(payload) != {"inventory_version", "files"} or payload.get("inventory_version") != INVENTORY_VERSION:
        return ["inventory_missing_or_malformed"]
    records = payload.get("files")
    if type(records) is not list or not records:
        return ["inventory_empty"]
    seen: set[str] = set()
    listed: set[str] = set()
    for record in records:
        expected = {"path", "sha256", "component", "license", "status"}
        if not isinstance(record, dict) or set(record) != expected:
            errors.append("inventory_record_malformed")
            continue
        relative = _safe_relative(record.get("path"))
        if relative is None or relative in seen:
            errors.append("inventory_path_invalid_or_duplicate")
            continue
        seen.add(relative)
        listed.add(relative)
        digest = record.get("sha256")
        if type(digest) is not str or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            errors.append("inventory_digest_invalid")
        component_name = record.get("component")
        component = components.get(component_name) if isinstance(component_name, str) else None
        if component is None:
            errors.append("inventory_component_missing")
        else:
            if record.get("status") != "included" or component.get("status") != "included":
                errors.append("pending_asset_included")
            if record.get("license") != component.get("license") or record.get("license") not in allowed:
                errors.append("inventory_license_mismatch")
        file_path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            if file_path.is_symlink() or not file_path.is_file():
                errors.append("inventory_file_missing")
            elif type(digest) is str and _sha256(file_path) != digest:
                errors.append("inventory_hash_mismatch")
        except OSError:
            errors.append("inventory_file_unreadable")
    actual = {
        file.relative_to(root).as_posix()
        for file in _tracked_or_present_files(root)
        if file.relative_to(root).as_posix() != inventory_path
    }
    if actual != listed:
        errors.append("inventory_file_set_mismatch")
    if "LICENSE" not in listed or "NOTICE" not in listed:
        errors.append("core_notice_coverage_missing")
    if any(component.get("status") == "included" and component.get("notice_required") is True for component in components.values()):
        notice = root / "NOTICE"
        if not notice.is_file():
            errors.append("notice_missing")
    return errors


def validate(root: Path | None = None, *, policy_path: Path | None = None, inventory_path: Path | None = None) -> list[str]:
    root = (root or ROOT).resolve()
    policy_file = policy_path or root / "licenses" / "approved_components.json"
    payload = _read_json(policy_file)
    policy_errors, components, configured_inventory = _policy_errors(payload)
    if policy_errors:
        return policy_errors
    allowed = set(payload["approved_spdx_licenses"])
    selected_inventory = inventory_path or root / configured_inventory  # type: ignore[arg-type]
    try:
        relative_inventory = selected_inventory.resolve().relative_to(root).as_posix()
    except (OSError, ValueError):
        return ["inventory_path_invalid"]
    return _inventory_errors(root, relative_inventory, components, allowed)


def write_inventory(root: Path | None = None, *, output: Path | None = None) -> Path:
    root = (root or ROOT).resolve()
    destination = output or root / "licenses" / "shipped_inventory.json"
    records = []
    for path in _tracked_or_present_files(root):
        relative = path.relative_to(root).as_posix()
        if relative == destination.relative_to(root).as_posix():
            continue
        records.append({
            "path": relative,
            "sha256": _sha256(path),
            "component": "Mudra Interact Core",
            "license": "Apache-2.0",
            "status": "included",
        })
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps({"inventory_version": INVENTORY_VERSION, "files": records}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the Mudra Interact shipped licence and byte inventory.")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--inventory", type=Path, default=None)
    parser.add_argument("--write-inventory", action="store_true")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.write_inventory:
        write_inventory(root, output=args.inventory)
    failures = validate(root, policy_path=args.policy, inventory_path=args.inventory)
    if failures:
        print("\n".join(sorted(set(failures))))
        return 1
    print("Mudra Interact licence and byte inventory: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
