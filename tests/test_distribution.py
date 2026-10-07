"""MI-08 distribution, identity and compatibility acceptance cases."""

from __future__ import annotations

import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools.aggregate_platform_matrix import (
    EXPECTED_CELLS,
    REQUIRED_CASES,
    aggregate_receipt_documents,
    validate_aggregate_report,
    write_report as write_matrix_report,
)
from tools.verify_release import (
    PACKAGE_VERSION,
    REQUIRED_PYTHONS,
    REQUIRED_PLATFORMS,
    current_platform,
    source_tree_sha256 as release_source_tree_sha256,
    validate_release_identity,
    _windows_network_isolation_result,
)
from tools.verification_report import (
    canonical_text_bytes,
    canonical_json_bytes,
    seal_report,
    sha256_bytes,
    sha256_text_file,
    source_tree_sha256 as independent_source_tree_sha256,
    VerificationError,
)


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.acceptance("E84")
def test_source_identity_is_stable_across_windows_checkout_newlines(tmp_path: Path) -> None:
    text_hashes = []
    tree_hashes = []
    for name, contents in (("lf", b"Mudra source\nsecond line\n"), ("crlf", b"Mudra source\r\nsecond line\r\n")):
        tree = tmp_path / name
        tree.mkdir()
        (tree / "README.md").write_bytes(contents)
        subprocess.run(["git", "init", "--quiet"], cwd=tree, check=True)
        subprocess.run(["git", "add", "--", "README.md"], cwd=tree, check=True)
        expected = independent_source_tree_sha256(tree)
        assert release_source_tree_sha256(tree) == expected
        text_hashes.append(sha256_text_file(tree / "README.md"))
        tree_hashes.append(expected)
    assert text_hashes[0] == text_hashes[1]
    assert tree_hashes[0] == tree_hashes[1]
    assert canonical_text_bytes(b"binary\x00\r\n") == b"binary\x00\r\n"


@pytest.fixture(scope="module")
def release_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    # Release receipts are deliberately repository-relative.  `build/` is an
    # ignored scratch location and is excluded from source identity.
    report_relative = Path("build") / f"mi08-release-{os.getpid()}.json"
    report_path = ROOT / report_relative
    report_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "tools/verify_release.py", "--offline", "--report", report_relative.as_posix()],
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": "", "PIP_NO_INDEX": "1", "PYTHONNOUSERSITE": "1"},
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300,
    )
    assert completed.returncode in {0, 2}, completed.stderr[-2000:]
    return json.loads(report_path.read_text(encoding="utf-8"))


@pytest.mark.acceptance("E73")
def test_clean_artifacts_metadata_and_payload(release_report: dict) -> None:
    assert release_report["checks"]["wheel"]["metadata_name"] == "mudra-interact-core"
    assert release_report["checks"]["wheel"]["metadata_version"] == PACKAGE_VERSION
    assert release_report["checks"]["wheel"]["requires_dist"] is None
    assert release_report["checks"]["wheel"]["metadata_validator"] == "stdlib_pep427_pep566_equivalent"
    assert set(release_report["checks"]["wheel"]["legal_payload"]) >= {"mudra_interact_core-0.2.0.data/data/LICENSE", "mudra_interact_core-0.2.0.data/data/NOTICE"}
    assert set(release_report["checks"]["wheel"]["package_data"]) == {
        "mudra_interact_core/catalog/mudra_catalog.json",
        "mudra_interact_core/schemas/v2/contract.schema.json",
        "mudra_interact_core/schemas/v2/version-map.json",
        "mudra_interact_core/py.typed",
    }
    assert {item["kind"] for item in release_report["artifacts"]} >= {"wheel", "sdist", "wheel_from_sdist"}


@pytest.mark.acceptance("E74")
def test_wheel_from_sdist_is_offline_and_owned_by_fresh_environment(release_report: dict) -> None:
    install = release_report["checks"]["fresh_install"]
    assert install["install_exit"] == 0
    assert install["uninstall_exit"] == 0
    assert install["reinstall_exit"] == 0
    assert install["smoke_exit"] == 0
    assert install["outside_checkout"] is True
    assert install["module_owned_by_venv"] is True
    assert install["runtime_dependencies"] == "none"
    assert release_report["checks"]["sdist_rebuild"]["offline"] is True


@pytest.mark.acceptance("E75")
def test_all_twelve_cells_are_enumerated_without_fake_success(release_report: dict) -> None:
    matrix = release_report["platform_matrix"]
    assert len(matrix) == 12
    assert {(row["os"], row["architecture"]) for row in matrix} == set(REQUIRED_PLATFORMS)
    assert {row["python"] for row in matrix} == set(REQUIRED_PYTHONS)
    actual = current_platform()
    matching = [
        row for row in matrix
        if (row["os"], row["architecture"], row["python"])
        == (actual["os"], actual["architecture"], f"{sys.version_info.major}.{sys.version_info.minor}")
    ]
    assert len(matching) == 1
    assert matching[0]["evidence"] == "actual_local_run"
    assert all(row["state"] in {"VERIFIED", "BLOCKED"} for row in matrix)


@pytest.mark.acceptance("E76")
def test_offline_negative_egress_and_cold_setup_failure_are_explicit(release_report: dict) -> None:
    offline = release_report["checks"]["offline"]
    assert offline["pip_no_index"] is True
    assert offline["negative_egress"]["synthetic_probe"] == "VERIFIED"
    assert offline["cold_dependency"]["explicit_setup_failure"] == "VERIFIED"
    assert offline["negative_egress"]["runner_network_isolation"] == "VERIFIED"
    expected_control = "VERIFIED" if current_platform()["os"] == "windows" else "NOT_REQUIRED"
    assert offline["negative_egress"]["control_connection_before_block"] == expected_control
    expected_methods = {
        "linux": "linux_network_namespace",
        "windows": "windows_firewall_program_rule",
        "macos": "macos_sandbox_exec",
    }
    assert offline["negative_egress"]["method"] == expected_methods[current_platform()["os"]]
    assert offline["negative_egress"]["isolation_result"] == "egress_denied"


@pytest.mark.acceptance("E84")
def test_windows_firewall_timeout_needs_control_and_matching_rule() -> None:
    assert _windows_network_isolation_result(
        control_connection_verified=True,
        rule_matches=True,
        connect_code=10060,
    ) == ("VERIFIED", "windows_firewall_program_rule", "egress_denied")
    assert _windows_network_isolation_result(
        control_connection_verified=False,
        rule_matches=True,
        connect_code=10060,
    ) == ("UNAVAILABLE", "windows_firewall_program_rule", "control_connection_unavailable")
    assert _windows_network_isolation_result(
        control_connection_verified=True,
        rule_matches=False,
        connect_code=10060,
    ) == ("UNAVAILABLE", "windows_firewall_program_rule", "matching_rule_unavailable")
    assert _windows_network_isolation_result(
        control_connection_verified=True,
        rule_matches=True,
        connect_code=0,
    ) == ("FAILED", "windows_firewall_program_rule", "egress_connected")


@pytest.mark.acceptance("E77")
def test_repeat_build_hashes_are_identical(release_report: dict) -> None:
    repeat = release_report["checks"]["repeat_build"]
    assert repeat["wheel_identical"] is True
    assert repeat["sdist_identical"] is True
    for key in ("wheel_a_sha256", "wheel_b_sha256", "sdist_a_sha256", "sdist_b_sha256"):
        assert re.fullmatch(r"[0-9a-f]{64}", repeat[key])


@pytest.mark.acceptance("E78")
def test_artifact_inventory_contains_hashes_not_unexpected_payload(release_report: dict) -> None:
    inventory = release_report["checks"]["inventory"]
    assert inventory["no_credentials_or_model_payload"] is True
    assert inventory["legal_files"] == ["LICENSE", "NOTICE"]
    assert all(re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in release_report["artifacts"])
    assert all("\\" not in item["path"] and not item["path"].startswith(("C:", "/")) for item in release_report["artifacts"])


@pytest.mark.acceptance("E79")
def test_ci_is_pinned_read_only_and_bounded() -> None:
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in workflow
    assert "timeout-minutes: 20" in workflow
    assert 'python -m venv "$RUNNER_TEMP/mudra-verifier"' in workflow
    assert "Join-Path $env:RUNNER_TEMP 'mudra-verifier/Scripts/python.exe'" in workflow
    assert '"$RUNNER_TEMP/mudra-verifier/bin/python" -m pip check' in workflow
    assert '.mudra-verifier' not in workflow
    assert "--require-hashes --no-deps -r requirements-dev.lock" in workflow
    assert "pip install --no-deps --no-build-isolation ." in workflow
    assert "pip check" in workflow
    assert workflow.index("pip install --no-deps --no-build-isolation .") < workflow.index("Block outbound networking")
    assert re.search(r"actions/checkout@[0-9a-f]{40}", workflow)
    assert re.search(r"actions/setup-python@[0-9a-f]{40}", workflow)
    assert "secrets." not in workflow
    assert len(re.findall(r"python-version: '[0-9]+\.[0-9]+'", workflow)) == 12
    assert "sudo unshare --net" in workflow
    assert 'runuser_path="$(command -v runuser)"' in workflow
    assert "New-NetFirewallRule" in workflow and "Remove-NetFirewallRule" in workflow
    assert "Path(sys.executable).resolve()" in workflow
    assert "MUDRA_WINDOWS_EGRESS_CONTROL=VERIFIED" in workflow
    assert "connect_ex(('1.1.1.1',443))" in workflow
    assert workflow.index("connect_ex(('1.1.1.1',443))") < workflow.index("New-NetFirewallRule")
    assert "sandbox-exec" in workflow
    assert "MUDRA_CI_RECEIPT_JSON" in workflow
    assert "MUDRA_CI_ARTIFACT_BASE64_JSON" in workflow
    assert "--acceptance-report=" in workflow


@pytest.mark.acceptance("E84")
def test_locked_verifier_environment_has_complete_dependencies() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=ROOT,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stdout


@pytest.mark.acceptance("E80")
def test_stale_release_identity_is_rejected(release_report: dict) -> None:
    with pytest.raises(Exception) as error:
        validate_release_identity(
            source_commit_value=release_report["source_commit"],
            source_tree_value=release_report["source_tree_sha256"],
            package_version=PACKAGE_VERSION,
            expected_commit="0" * 40,
            expected_source_tree=release_report["source_tree_sha256"],
        )
    assert getattr(error.value, "code", None) == "stale_source_commit"
    with pytest.raises(Exception) as error:
        validate_release_identity(
            source_commit_value=release_report["source_commit"],
            source_tree_value="0" * 64,
            package_version=PACKAGE_VERSION,
            expected_commit=release_report["source_commit"],
            expected_source_tree=release_report["source_tree_sha256"],
        )
    assert getattr(error.value, "code", None) == "stale_source_tree"


@pytest.mark.acceptance("E81")
def test_platform_identity_is_observed_from_running_host(release_report: dict) -> None:
    actual = current_platform()
    assert release_report["platform"]["os"] == actual["os"]
    assert release_report["platform"]["architecture"] == actual["architecture"]
    assert release_report["platform"]["python"] == platform.python_version()
    assert all("simulated" not in str(row).lower() for row in release_report["platform_matrix"])


@pytest.mark.acceptance("E82")
def test_exact_wheel_install_smoke_and_version_consistency(release_report: dict) -> None:
    install = release_report["checks"]["fresh_install"]
    metadata = release_report["checks"]["sdist_rebuild"]["metadata"]
    assert install["install_exit"] == 0 and install["smoke_exit"] == 0
    assert install["uninstall_exit"] == 0 and install["reinstall_exit"] == 0
    assert metadata["metadata_version"] == PACKAGE_VERSION
    assert metadata["metadata_name"] == "mudra-interact-core"


@pytest.mark.acceptance("E83")
def test_allyk_compatibility_inventory_keeps_private_boundary() -> None:
    document = (ROOT / "docs" / "COMPATIBILITY.md").read_text(encoding="utf-8")
    assert "ALLYK" in document
    assert "private downstream consumer" in document
    assert "no ALLYK source" in document
    assert "automatic upgrade" in document
    assert "schema" in document.lower() and "licensing" in document.lower()


@pytest.mark.acceptance("E84")
def test_release_report_is_reproducible_and_blocks_missing_cells(release_report: dict) -> None:
    for key in ("source_commit", "source_tree_sha256", "spec_sha256", "acceptance_sha256", "tool_lock_sha256"):
        assert release_report[key]
    assert release_report["report_sha256"]
    assert release_report["source_tree_sha256"] == independent_source_tree_sha256(ROOT)
    assert release_report["state"] in {"VERIFIED", "BLOCKED"}
    if len([row for row in release_report["platform_matrix"] if row["state"] == "VERIFIED"]) < 12:
        assert release_report["state"] == "BLOCKED"
        assert any("cells" in item for item in release_report["limitations"])

    identity = {
        key: release_report[key]
        for key in ("source_tree_sha256", "spec_sha256", "acceptance_sha256", "tool_lock_sha256")
    }
    candidate_commit = release_report["source_commit"]
    synthetic_receipts = []
    for os_name, architecture, python_version in EXPECTED_CELLS:
        report = seal_report({
            "report_schema_version": 1,
            "scope": {"kind": "item", "id": "MI-08"},
            "state": "VERIFIED",
            "verification_kind": "luna_self_verified",
            "source_commit": candidate_commit,
            **identity,
            "platform": {
                "os": os_name,
                "architecture": architecture,
                "python": f"{python_version}.17",
                "implementation": "CPython",
                "release": "synthetic_test_fixture",
            },
            "started_at": "2026-01-01T00:00:00Z",
            "finished_at": "2026-01-01T00:00:01Z",
            "commands": [],
            "test_counts": {
                "collected": len(REQUIRED_CASES) + 1,
                "passed": len(REQUIRED_CASES) + 1,
                "failed": 0,
                "skipped": 0,
                "xfailed": 0,
                "xpassed": 0,
            },
            "acceptance_cases": [
                {"acceptance_id": case_id, "outcome": "passed"}
                for case_id in REQUIRED_CASES
            ] + [{"acceptance_id": "E84", "outcome": "passed"}],
            "mutation_results": [],
            "artifacts": [],
            "prerequisites": [{"id": "MI-07", "state": "VERIFIED"}],
            "limitations": [],
            "errors": [],
            "items": ["MI-08"],
        })
        receipt_path = f"evidence/local/mi08-platform-receipts/test-{os_name}-py{python_version}.json"
        receipt_digest = sha256_bytes(canonical_json_bytes(report))
        synthetic_receipts.append((receipt_path, receipt_digest, report))

    aggregate_args = {
        "current_identity": identity,
        "candidate_is_ancestor": True,
        "collector_platform": current_platform(),
        "collector_commit": candidate_commit,
    }
    partial = aggregate_receipt_documents(synthetic_receipts[:-1], **aggregate_args)
    assert partial["state"] == "BLOCKED"
    assert partial["matrix"]["verified_cells"] == 11
    assert partial["matrix"]["missing_cells"] == 1
    complete = aggregate_receipt_documents(synthetic_receipts, **aggregate_args)
    assert complete["state"] == "VERIFIED"
    assert complete["matrix"]["verified_cells"] == 12
    aggregate_path = Path("evidence/local") / f"matrix-fixture-{os.getpid()}.json"
    try:
        write_matrix_report(ROOT, aggregate_path.as_posix(), complete)
        validated = validate_aggregate_report(
            ROOT,
            aggregate_path.as_posix(),
            current_identity=identity,
            current_commit=candidate_commit,
        )
        assert validated["matrix"]["verified_cells"] == 12
        incomplete = dict(complete)
        incomplete["matrix"] = {**complete["matrix"], "cells": complete["matrix"]["cells"][:-1], "verified_cells": 11, "missing_cells": 1}
        write_matrix_report(ROOT, aggregate_path.as_posix(), seal_report(incomplete))
        with pytest.raises(VerificationError):
            validate_aggregate_report(
                ROOT,
                aggregate_path.as_posix(),
                current_identity=identity,
                current_commit=candidate_commit,
            )
    finally:
        (ROOT / aggregate_path).unlink(missing_ok=True)
    duplicate = aggregate_receipt_documents(synthetic_receipts + synthetic_receipts[:1], **aggregate_args)
    assert duplicate["state"] == "FAILED"
    assert any(item["code"] == "duplicate_platform_cell" for item in duplicate["errors"])
