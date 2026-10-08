from __future__ import annotations

import json
import shutil
import tempfile
import socket
from importlib.resources import files
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.verify_gate import acceptance_owners
from tools.verification_report import (
    VerificationError,
    read_json,
    validate_fixture_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "v2"
CONTRACT_PATH = ROOT / "src" / "mudra_interact_core" / "schemas" / "v2" / "contract.schema.json"
SCHEMA_NAMES = ("Frame", "Recognition", "Event", "Catalogue", "Batch", "LocalReport")


def _contract() -> dict:
    return read_json(CONTRACT_PATH)


def _validator(name: str) -> Draft202012Validator:
    contract = _contract()
    schema = {
        "$schema": contract["$schema"],
        "$id": f"{contract['$id']}/{name}",
        "$defs": contract["$defs"],
        "$ref": f"#/$defs/{name}",
    }
    return Draft202012Validator(schema)


def _recursive_refs(value):
    if isinstance(value, dict):
        for key, child in value.items():
            if key == "$ref":
                yield child
            yield from _recursive_refs(child)
    elif isinstance(value, list):
        for child in value:
            yield from _recursive_refs(child)


def _fixture_record(fixture_id: str) -> dict:
    manifest = read_json(FIXTURE_DIR / "manifest.json")
    return next(record for record in manifest["fixtures"] if record["fixture_id"] == fixture_id)


@pytest.mark.acceptance("E01")
def test_v2_contract_schemas_and_synthetic_examples_validate_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny_network(*_args, **_kwargs):
        raise AssertionError("schema validation attempted network access")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    contract = _contract()
    packaged = files("mudra_interact_core.schemas.v2")
    assert packaged.joinpath("contract.schema.json").read_bytes() == CONTRACT_PATH.read_bytes()
    assert packaged.joinpath("version-map.json").read_bytes() == (CONTRACT_PATH.parent / "version-map.json").read_bytes()
    Draft202012Validator.check_schema(contract)
    assert set(contract["$defs"]) == {
        "Landmark", "Frame", "Recognition", "Event", "CatalogueEntry",
        "Catalogue", "Batch", "LocalReport",
    }
    assert all(reference.startswith("#/") for reference in _recursive_refs(contract))
    for name in SCHEMA_NAMES:
        schema = {"$schema": contract["$schema"], "$defs": contract["$defs"], "$ref": f"#/$defs/{name}"}
        Draft202012Validator.check_schema(schema)
        assert contract["$defs"][name]["type"] == "object"
        assert contract["$defs"][name]["additionalProperties"] is False

    records = validate_fixture_manifest(ROOT, known_case_ids=acceptance_owners(ROOT))
    valid_records = [record for record in records if record["expected"]["outcome"] == "valid"]
    assert {record["expected"]["schema"] for record in valid_records} == set(SCHEMA_NAMES)
    for record in valid_records:
        document = read_json(record["resolved_path"])
        assert set(document) == set(record["expected"]["expected_fields"])
        assert _validator(record["expected"]["schema"]).is_valid(document)


@pytest.mark.acceptance("E02")
def test_fixture_manifest_rejects_missing_tampered_duplicate_and_unknown_records() -> None:
    known_case_ids = acceptance_owners(ROOT)
    assert len(validate_fixture_manifest(ROOT, known_case_ids=known_case_ids)) == 8
    with tempfile.TemporaryDirectory(prefix="mudra-fixture-proof-") as scratch:
        scratch_root = Path(scratch)
        copied_fixture_dir = scratch_root / "tests" / "fixtures" / "v2"
        copied_fixture_dir.parent.mkdir(parents=True)
        shutil.copytree(FIXTURE_DIR, copied_fixture_dir)
        manifest_path = copied_fixture_dir / "manifest.json"

        edited = copied_fixture_dir / "frame-v2.json"
        edited.write_bytes(edited.read_bytes() + b" ")
        with pytest.raises(VerificationError, match="fixture_hash_mismatch"):
            validate_fixture_manifest(scratch_root, manifest_path, known_case_ids=known_case_ids)
        edited.write_bytes((FIXTURE_DIR / "frame-v2.json").read_bytes())

        missing = copied_fixture_dir / "recognition-v2.json"
        missing.unlink()
        with pytest.raises(VerificationError, match="fixture_missing_or_outside_root"):
            validate_fixture_manifest(scratch_root, manifest_path, known_case_ids=known_case_ids)
        shutil.copy2(FIXTURE_DIR / "recognition-v2.json", missing)

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["fixtures"][1]["case_id"] = "E00"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(VerificationError, match="fixture_case_unknown"):
            validate_fixture_manifest(scratch_root, manifest_path, known_case_ids=known_case_ids)

        manifest = json.loads((FIXTURE_DIR / "manifest.json").read_text(encoding="utf-8"))
        manifest["fixtures"][1]["fixture_id"] = manifest["fixtures"][0]["fixture_id"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(VerificationError, match="fixture_id_duplicate_or_invalid"):
            validate_fixture_manifest(scratch_root, manifest_path, known_case_ids=known_case_ids)

        manifest["fixtures"][1]["fixture_id"] = "unique-fixture"
        manifest["fixtures"][1]["path"] = manifest["fixtures"][0]["path"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with pytest.raises(VerificationError, match="fixture_path_duplicate_or_invalid"):
            validate_fixture_manifest(scratch_root, manifest_path, known_case_ids=known_case_ids)


@pytest.mark.acceptance("E03")
def test_v1_is_inspection_only_v2_is_supported_and_unknown_versions_fail() -> None:
    version_map = read_json(CONTRACT_PATH.parent / "version-map.json")
    assert version_map == {
        "package_version": "0.3.0",
        "protocol_version": "2.0.0",
        "catalog_version": "2.0.0",
        "event_schema_versions": {
            "1.0": {"v2_import": False, "handling": "inspection_and_manual_migration_only"},
            "2.0.0": {"v2_import": True, "handling": "supported"},
        },
        "unsupported_version_policy": "reject_without_coercion_or_authority_migration",
    }
    event_validator = _validator("Event")
    v1 = read_json(FIXTURE_DIR / "event-v1-inspection.json")
    v2 = read_json(FIXTURE_DIR / "event-v2.json")
    unknown = read_json(FIXTURE_DIR / "event-unknown-version.json")
    assert v1["schema_version"] == "1.0"
    assert v2["schema_version"] == "2.0.0"
    assert event_validator.is_valid(v2)
    assert not event_validator.is_valid(v1)
    assert not event_validator.is_valid(unknown)
    assert "manual migration" in (ROOT / "docs" / "MIGRATION.md").read_text(encoding="utf-8")
