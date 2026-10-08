from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from tools.verification_report import VerificationError, read_json
from tools.verify_language_gate import (
    SCHEMA_PATH,
    validate_language_fixture_manifest,
    validate_local_schema_references,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "language" / "v1"
EXPECTED_DIRECTIONS = {
    ("human", "human"): "human_to_human",
    ("human", "agent"): "human_to_agent",
    ("agent", "human"): "agent_to_human",
    ("agent", "agent"): "agent_to_agent",
}
EXPECTED_ACTS = {
    "request", "proposal", "clarification", "accept", "decline",
    "acknowledge", "status", "result", "error",
}


def _schema() -> dict:
    schema = read_json(ROOT / SCHEMA_PATH)
    validate_local_schema_references(schema)
    Draft202012Validator.check_schema(schema)
    return schema


@pytest.mark.acceptance("L01")
def test_static_fixtures_cover_every_act_and_role_direction() -> None:
    validator = Draft202012Validator(_schema())
    fixtures = validate_language_fixture_manifest(ROOT)
    language_fixtures = [fixture for fixture in fixtures if fixture["case_id"] == "L01"]
    matrix: dict[tuple[str, str], set[str]] = {}

    for fixture in language_fixtures:
        message = fixture["value"]
        sender_kind = message["sender"]["kind"]
        recipient_kind = message["recipient"]["kind"]
        direction = EXPECTED_DIRECTIONS[(sender_kind, recipient_kind)]
        assert direction == fixture["direction"]
        assert message["act"] == fixture["act"]
        is_valid = validator.is_valid(message)
        assert is_valid is (fixture["expected_outcome"] == "valid"), fixture["fixture_id"]
        matrix.setdefault((direction, fixture["act"]), set()).add(fixture["expected_outcome"])

    assert len(language_fixtures) == 72
    assert set(matrix) == {(direction, act) for direction in EXPECTED_DIRECTIONS.values() for act in EXPECTED_ACTS}
    assert all(outcomes == {"valid", "invalid"} for outcomes in matrix.values())


@pytest.mark.acceptance("L02")
def test_unsupported_versions_namespace_and_act_reject() -> None:
    validator = Draft202012Validator(_schema())
    fixtures = validate_language_fixture_manifest(ROOT)
    negative = [fixture for fixture in fixtures if fixture["case_id"] == "L02"]
    assert {fixture["act"] for fixture in negative} == {
        "unsupported_protocol_version",
        "unsupported_intent_name",
        "unsupported_intent_version",
        "unsupported_act",
        "unknown_message_field",
    }
    assert all(not validator.is_valid(fixture["value"]) for fixture in negative)


@pytest.mark.acceptance("L02")
def test_schema_accepts_only_local_references() -> None:
    schema = _schema()
    assert schema["$id"] == "urn:allyk:mudra-interact:language:1.0.0"

    injected_remote_reference = copy.deepcopy(schema)
    injected_remote_reference["properties"] = {
        "remote_extension": {"$ref": "https://schemas.example.invalid/intent.json"}
    }
    with pytest.raises(VerificationError, match="language_remote_schema_reference"):
        validate_local_schema_references(injected_remote_reference)


@pytest.mark.acceptance("L02")
def test_tampered_fixture_bytes_and_manifest_hash_reject(tmp_path: Path) -> None:
    temp_root = tmp_path
    docs = temp_root / "docs"
    docs.mkdir()
    (docs / "COMMUNICATION_LANGUAGE_ACCEPTANCE.md").write_bytes(
        (ROOT / "docs" / "COMMUNICATION_LANGUAGE_ACCEPTANCE.md").read_bytes()
    )
    copied_fixture_root = temp_root / "tests" / "fixtures" / "language" / "v1"
    shutil.copytree(FIXTURE_ROOT, copied_fixture_root)
    manifest_path = copied_fixture_root / "manifest.json"

    target = copied_fixture_root / "human_to_human.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(VerificationError, match="language_fixture_hash_mismatch"):
        validate_language_fixture_manifest(temp_root, manifest_path)

    shutil.copy2(FIXTURE_ROOT / "human_to_human.json", target)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["fixtures"][0]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(VerificationError, match="language_fixture_hash_mismatch"):
        validate_language_fixture_manifest(temp_root, manifest_path)


@pytest.mark.acceptance("L01")
def test_manifest_rejects_path_escape_duplicate_id_and_unknown_case(tmp_path: Path) -> None:
    temp_root = tmp_path
    docs = temp_root / "docs"
    docs.mkdir()
    (docs / "COMMUNICATION_LANGUAGE_ACCEPTANCE.md").write_bytes(
        (ROOT / "docs" / "COMMUNICATION_LANGUAGE_ACCEPTANCE.md").read_bytes()
    )
    copied_fixture_root = temp_root / "tests" / "fixtures" / "language" / "v1"
    shutil.copytree(FIXTURE_ROOT, copied_fixture_root)
    manifest_path = copied_fixture_root / "manifest.json"
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    mutated = copy.deepcopy(original)
    mutated["fixtures"][1]["fixture_id"] = mutated["fixtures"][0]["fixture_id"]
    manifest_path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(VerificationError, match="language_fixture_id_invalid"):
        validate_language_fixture_manifest(temp_root, manifest_path)

    mutated = copy.deepcopy(original)
    mutated["fixtures"][0]["case_id"] = "L99"
    manifest_path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(VerificationError, match="language_fixture_case_unknown"):
        validate_language_fixture_manifest(temp_root, manifest_path)

    mutated = copy.deepcopy(original)
    mutated["fixtures"][0]["path"] = "../../outside.json"
    manifest_path.write_text(json.dumps(mutated), encoding="utf-8")
    with pytest.raises(VerificationError, match="language_path_invalid"):
        validate_language_fixture_manifest(temp_root, manifest_path)
