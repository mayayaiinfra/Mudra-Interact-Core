from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from tools_check_license_allowlist import validate


ROOT = Path(__file__).resolve().parents[1]


def _copy_tree(destination: Path) -> Path:
    shutil.copytree(
        ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", "evidence", "build", "dist", ".pytest_cache",
            ".pytest-language-tmp", "__pycache__",
        ),
    )
    return destination


def _policy(root: Path) -> dict[str, object]:
    return json.loads((root / "licenses" / "approved_components.json").read_text(encoding="utf-8"))


def _write_policy(root: Path, payload: dict[str, object]) -> None:
    (root / "licenses" / "approved_components.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.acceptance("E67")
@pytest.mark.parametrize("mutation", ["empty", "missing", "malformed", "missing_core", "unknown_status", "unknown_license", "missing_notice"])
def test_license_policy_and_notice_fail_closed(tmp_path: Path, mutation: str) -> None:
    root = _copy_tree(tmp_path / mutation)
    policy_path = root / "licenses" / "approved_components.json"
    if mutation == "empty":
        policy_path.write_text("{}", encoding="utf-8")
    elif mutation == "missing":
        policy_path.unlink()
    elif mutation == "malformed":
        policy_path.write_text("{not-json", encoding="utf-8")
    elif mutation == "missing_core":
        payload = _policy(root)
        payload["components"] = [component for component in payload["components"] if component["name"] != "Mudra Interact"]  # type: ignore[index]
        _write_policy(root, payload)
    elif mutation == "unknown_status":
        payload = _policy(root)
        payload["components"][0]["status"] = "secretly_included"  # type: ignore[index]
        _write_policy(root, payload)
    elif mutation == "unknown_license":
        payload = _policy(root)
        payload["components"][0]["license"] = "Unknown-License"  # type: ignore[index]
        _write_policy(root, payload)
    else:
        (root / "NOTICE").unlink()
    assert validate(root)


@pytest.mark.acceptance("E68")
@pytest.mark.parametrize("mutation", ["wrong_digest", "unlisted_asset", "pending_asset", "deleted_asset"])
def test_shipped_inventory_hash_coverage_and_pending_assets_fail_closed(tmp_path: Path, mutation: str) -> None:
    root = _copy_tree(tmp_path / mutation)
    inventory_path = root / "licenses" / "shipped_inventory.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    if mutation == "wrong_digest":
        inventory["files"][0]["sha256"] = "0" * 64
    elif mutation == "unlisted_asset":
        new_file = root / "src" / "mudra_interact_core" / "unreviewed_asset.bin"
        new_file.write_bytes(b"synthetic pending asset")
    elif mutation == "pending_asset":
        inventory["files"][0]["status"] = "approved_in_principle_pending_distribution_review"
    else:
        victim = root.joinpath(*Path(inventory["files"][0]["path"]).parts)
        victim.unlink()
    inventory_path.write_text(json.dumps(inventory), encoding="utf-8")
    assert validate(root)
