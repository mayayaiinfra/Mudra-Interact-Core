"""MI-08 distribution, identity and compatibility acceptance cases."""

from __future__ import annotations

import hashlib
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
from tools.release_proof import ReleaseProofError
from tools.verify_gate import _validate_active_item_selection
from tools.verify_release import (
    PACKAGE_VERSION,
    REQUIRED_PYTHONS,
    REQUIRED_PLATFORMS,
    current_platform,
    source_tree_sha256 as release_source_tree_sha256,
    validate_release_identity,
    _windows_firewall_rule_matches,
    _windows_network_isolation_result,
    _windows_process_image_path,
)
from tools import verify_release as release_verifier
from tools.verification_report import (
    canonical_text_bytes,
    canonical_json_bytes,
    seal_report,
    safe_subprocess_environment,
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


@pytest.mark.acceptance("E84")
def test_source_identity_excludes_mutable_status_ledgers(tmp_path: Path) -> None:
    tree = tmp_path / "status-ledger"
    (tree / "docs").mkdir(parents=True)
    (tree / "src").mkdir()
    (tree / "README.md").write_text("Mudra source\n", encoding="utf-8")
    (tree / "IMPLEMENTATION_BACKLOG.json").write_text('{"state":"IN_PROGRESS"}\n', encoding="utf-8")
    language_ledger = tree / "docs" / "COMMUNICATION_LANGUAGE_BACKLOG.json"
    language_ledger.write_text('{"ML-01":"REVERIFY_REQUIRED"}\n', encoding="utf-8")
    (tree / "src" / "module.py").write_text("value = 1\n", encoding="utf-8")
    subprocess.run(["git", "init", "--quiet"], cwd=tree, check=True)
    subprocess.run(["git", "add", "--all"], cwd=tree, check=True)

    initial = independent_source_tree_sha256(tree)
    language_ledger.write_text('{"ML-01":"VERIFIED"}\n', encoding="utf-8")
    (tree / "IMPLEMENTATION_BACKLOG.json").write_text('{"state":"VERIFIED"}\n', encoding="utf-8")

    assert independent_source_tree_sha256(tree) == initial
    assert release_source_tree_sha256(tree) == initial
    (tree / "README.md").write_text("Changed product source\n", encoding="utf-8")
    assert independent_source_tree_sha256(tree) != initial
    assert release_source_tree_sha256(tree) == independent_source_tree_sha256(tree)


@pytest.mark.acceptance("E84")
def test_reproducible_build_environment_excludes_unrelated_secrets(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MUDRA_TEST_SECRET", "must-not-enter-build-subprocess")
    monkeypatch.setenv("USERNAME", "mudra-test-user")
    monkeypatch.setenv("PROCESSOR_ARCHITECTURE", "AMD64")
    monkeypatch.setenv("PROCESSOR_ARCHITEW6432", "AMD64")
    monkeypatch.setenv("MUDRA_WINDOWS_EGRESS_CONTROL", "VERIFIED")
    monkeypatch.setenv("MUDRA_FIREWALL_RULE_NAME", "mudra-test-firewall")
    env = release_verifier.reproducible_env()
    verifier_env = safe_subprocess_environment()

    assert "MUDRA_TEST_SECRET" not in env
    assert "MUDRA_TEST_SECRET" not in verifier_env
    assert env.get("USERNAME") == "mudra-test-user"
    assert verifier_env.get("USERNAME") == "mudra-test-user"
    assert env["PROCESSOR_ARCHITECTURE"] == "AMD64"
    assert env["PROCESSOR_ARCHITEW6432"] == "AMD64"
    assert verifier_env["PROCESSOR_ARCHITECTURE"] == "AMD64"
    assert verifier_env["PROCESSOR_ARCHITEW6432"] == "AMD64"
    assert env["MUDRA_WINDOWS_EGRESS_CONTROL"] == "VERIFIED"
    assert env["MUDRA_FIREWALL_RULE_NAME"] == "mudra-test-firewall"
    assert env["PIP_NO_INDEX"] == "1"
    assert env["PYTHONNOUSERSITE"] == "1"


@pytest.fixture(scope="module")
def release_report(tmp_path_factory: pytest.TempPathFactory) -> dict:
    # Release receipts are deliberately repository-relative.  `build/` is an
    # ignored scratch location and is excluded from source identity.
    report_relative = Path("build") / f"mi08-release-{os.getpid()}.json"
    artifact_relative = Path("build") / f"mi08-candidate-{os.getpid()}"
    report_path = ROOT / report_relative
    report_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            sys.executable, "tools/verify_release.py", "--offline",
            "--artifact-dir", artifact_relative.as_posix(),
            "--report", report_relative.as_posix(),
        ],
        cwd=ROOT,
        env=release_verifier.reproducible_env(),
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
    assert release_report["checks"]["wheel"]["metadata_name"] == "mudra-interact"
    assert release_report["checks"]["wheel"]["metadata_version"] == PACKAGE_VERSION
    expected_summary = release_verifier.PACKAGE_SUMMARY
    expected_description_sha256 = sha256_text_file(ROOT / "README.md")
    assert release_report["checks"]["wheel"]["metadata_summary"] == expected_summary
    assert release_report["checks"]["wheel"]["description_sha256"] == expected_description_sha256
    assert release_report["checks"]["sdist"]["summary"] == expected_summary
    assert release_report["checks"]["sdist"]["description_sha256"] == expected_description_sha256
    assert release_report["checks"]["wheel"]["requires_dist"] is None
    assert set(release_report["checks"]["wheel"]["package_modules"]) == {
        "mudra_interact_core/__init__.py",
        "mudra_interact_core/a2a.py",
    }
    assert set(release_report["checks"]["sdist"]["package_modules"]) == {
        "mudra_interact_core/__init__.py",
        "mudra_interact_core/a2a.py",
    }
    assert release_report["checks"]["wheel"]["metadata_validator"] == "stdlib_pep427_pep566_equivalent"
    assert set(release_report["checks"]["wheel"]["legal_payload"]) >= {f"mudra_interact-{PACKAGE_VERSION}.data/data/LICENSE", f"mudra_interact-{PACKAGE_VERSION}.data/data/NOTICE"}
    assert set(release_report["checks"]["wheel"]["package_data"]) == {
        "mudra_interact_core/catalog/mudra_catalog.json",
        "mudra_interact_core/schemas/v2/contract.schema.json",
        "mudra_interact_core/schemas/v2/version-map.json",
        "mudra_interact_core/schemas/language/v1/language.schema.json",
        "mudra_interact_core/schemas/language/v1/version-map.json",
        "mudra_interact_core/examples/language/human-human.json",
        "mudra_interact_core/examples/language/human-agent.json",
        "mudra_interact_core/examples/language/agent-agent.json",
        "mudra_interact_core/py.typed",
    }
    assert {item["kind"] for item in release_report["artifacts"]} >= {"wheel", "sdist", "wheel_from_sdist"}


@pytest.mark.acceptance("E73")
def test_actual_offline_frozen_candidate_has_expected_distribution_filenames(release_report: dict) -> None:
    frozen = release_report["frozen_candidate_artifacts"]
    assert {item["filename"] for item in frozen} == {
        f"mudra_interact-{PACKAGE_VERSION}-py3-none-any.whl",
        f"mudra_interact-{PACKAGE_VERSION}.tar.gz",
    }
    assert all(item["size_bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) for item in frozen)


@pytest.mark.acceptance("E73")
def test_real_candidate_inventory_accepts_backend_built_artifacts(release_report: dict) -> None:
    # The local Windows run cannot establish OS-level egress isolation. Mark
    # only that external prerequisite in a resealed fixture; the offline build,
    # source identity, filenames, sizes, and hashes remain actual outputs.
    fixture = json.loads(json.dumps(release_report))
    fixture["checks"]["offline"]["negative_egress"]["runner_network_isolation"] = "VERIFIED"
    report_path = ROOT / "build" / f"mi08-candidate-fixture-{os.getpid()}.json"
    report_path.write_bytes(canonical_json_bytes(seal_report(fixture)))

    inventory = release_verifier.frozen_candidate_inventory(
        f"build/mi08-candidate-{os.getpid()}", report_path.relative_to(ROOT).as_posix(),
    )

    assert {row["filename"] for row in inventory} == {
        f"mudra_interact-{PACKAGE_VERSION}-py3-none-any.whl",
        f"mudra_interact-{PACKAGE_VERSION}.tar.gz",
    }
    assert all(row["size_bytes"] > 0 and re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) for row in inventory)


@pytest.mark.acceptance("E74")
def test_wheel_from_sdist_is_offline_and_owned_by_fresh_environment(release_report: dict) -> None:
    install = release_report["checks"]["fresh_install"]
    assert install["install_exit"] == 0
    assert install["uninstall_exit"] == 0
    assert install["reinstall_exit"] == 0
    assert install["smoke_exit"] == 0
    assert install["language_examples_executed"] == 3
    assert install["outside_checkout"] is True
    assert install["module_owned_by_venv"] is True
    assert install["runtime_dependencies"] == "none"
    assert release_report["checks"]["sdist_rebuild"]["offline"] is True


@pytest.mark.acceptance("E75")
def test_all_eight_supported_cells_are_enumerated_without_fake_success(release_report: dict) -> None:
    matrix = release_report["platform_matrix"]
    assert len(matrix) == 8
    assert set(REQUIRED_PLATFORMS) == {("linux", "x86_64"), ("windows", "x86_64")}
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


@pytest.mark.acceptance("E84")
def test_windows_process_image_path_matches_native_image() -> None:
    image = _windows_process_image_path()
    if os.name != "nt":
        assert image is None
        return

    import ctypes

    native_buffer = ctypes.create_unicode_buffer(32768)
    native_length = ctypes.windll.kernel32.GetModuleFileNameW(None, native_buffer, len(native_buffer))
    assert 0 < native_length < len(native_buffer)
    assert image == Path(native_buffer.value)
    assert image is not None and image.is_file()


@pytest.mark.acceptance("E84")
def test_windows_firewall_rule_rejects_a_different_process_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "base-python.exe"
    configured_image = tmp_path / "venv" / "Scripts" / "python.exe"
    monkeypatch.setenv("MUDRA_FIREWALL_RULE_NAME", "synthetic-rule")
    monkeypatch.setenv("MUDRA_PYTHON_EXE", str(configured_image))
    monkeypatch.setattr("tools.verify_release.shutil.which", lambda _name: "powershell.exe")
    monkeypatch.setattr("tools.verify_release._windows_process_image_path", lambda: image)
    monkeypatch.setattr(
        "tools.verify_release.subprocess.run",
        lambda *_args, **_kwargs: pytest.fail("a mismatched process image must not inspect a rule"),
    )

    assert _windows_firewall_rule_matches() is False


@pytest.mark.acceptance("E84")
def test_windows_firewall_rule_reports_safe_lookup_reason(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "base-python.exe"
    image.write_bytes(b"synthetic executable marker")
    monkeypatch.setenv("MUDRA_FIREWALL_RULE_NAME", "synthetic-rule")
    monkeypatch.setenv("MUDRA_PYTHON_EXE", str(image))
    monkeypatch.setattr("tools.verify_release.shutil.which", lambda _name: "powershell.exe")
    monkeypatch.setattr("tools.verify_release._windows_process_image_path", lambda: image)
    monkeypatch.setattr(
        "tools.verify_release.subprocess.run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess([], 2),
    )

    assert release_verifier._windows_firewall_rule_status() == (False, "firewall_rule_not_found")


@pytest.mark.acceptance("E84")
def test_windows_firewall_rule_inspection_prefers_pwsh_module_host(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "base-python.exe"
    image.write_bytes(b"synthetic executable marker")
    monkeypatch.setenv("MUDRA_FIREWALL_RULE_NAME", "synthetic-rule")
    monkeypatch.setenv("MUDRA_PYTHON_EXE", str(image))
    monkeypatch.setattr(
        "tools.verify_release.shutil.which",
        lambda name: {"pwsh.exe": "pwsh.exe", "powershell.exe": "powershell.exe"}.get(name),
    )
    monkeypatch.setattr("tools.verify_release._windows_process_image_path", lambda: image)
    commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("tools.verify_release.subprocess.run", run)

    assert release_verifier._windows_firewall_rule_status() == (True, "firewall_rule_matches")
    assert commands[0][0] == "pwsh.exe"


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
    windows_tools_step = workflow.split(
        "- name: Install and validate locked verification tools\n        if: runner.os == 'Windows'\n        shell: pwsh\n        run: |",
        1,
    )[1].split("\n      - name:", 1)[0]
    assert "permissions:\n  contents: read" in workflow
    assert "workflow_dispatch:" in workflow
    assert "if: github.event_name != 'workflow_dispatch'" in workflow
    assert "if: github.event_name == 'workflow_dispatch'" in workflow
    assert "fetch-depth: 0" in workflow.split("  m3-gate:\n", 1)[1]
    assert "timeout-minutes: 20" in workflow
    assert 'python -m venv "$RUNNER_TEMP/mudra-verifier"' in workflow
    assert "Join-Path $env:RUNNER_TEMP 'mudra-verifier/Scripts/python.exe'" in workflow
    assert '"$RUNNER_TEMP/mudra-verifier/bin/python" -m pip check' in workflow
    assert '.mudra-verifier' not in workflow
    assert "--require-hashes --no-deps -r requirements-dev.lock" in workflow
    assert windows_tools_step.index("pip install --require-hashes") < windows_tools_step.index("$env:PIP_NO_INDEX = '1'")
    assert "pip install --no-deps --no-build-isolation ." in workflow
    assert "pip check" in workflow
    assert workflow.index("pip install --no-deps --no-build-isolation .") < workflow.index("Block outbound networking")
    assert re.search(r"actions/checkout@[0-9a-f]{40}", workflow)
    assert re.search(r"actions/setup-python@[0-9a-f]{40}", workflow)
    assert "secrets." not in workflow
    matrix_block = workflow.split("      matrix:\n", 1)[1].split("    steps:\n", 1)[0]
    assert len(re.findall(r"python-version: '[0-9]+\.[0-9]+'", matrix_block)) == 8
    assert "python-version: '3.14'" in workflow.split("  m3-gate:\n", 1)[1]
    assert "macos-" not in workflow
    assert "sudo unshare --net" in workflow
    assert 'runuser_path="$(command -v runuser)"' in workflow
    assert "New-NetFirewallRule" in workflow and "Remove-NetFirewallRule" in workflow
    assert '$env:GITHUB_JOB-py${{ matrix.python-version }}' in workflow
    assert "GetModuleFileNameW" in workflow
    assert "MUDRA_PYTHON_EXE=$target" in workflow
    assert "Path(sys.executable).resolve()" not in workflow
    assert "MUDRA_WINDOWS_EGRESS_CONTROL=VERIFIED" in workflow
    assert "connect_ex(('1.1.1.1',443))" in workflow
    assert workflow.index("connect_ex(('1.1.1.1',443))") < workflow.index("New-NetFirewallRule")
    assert "sandbox-exec" not in workflow
    assert "MUDRA_CI_RECEIPT_JSON" in workflow
    assert "MUDRA_CI_ARTIFACT_BASE64_JSON" in workflow
    assert "--acceptance-report=" in workflow
    assert 'candidate_version="$("$python_path" -c' in workflow
    assert 'platform_matrix="evidence/local/v${candidate_version}/M3-platform-matrix.json"' in workflow
    assert '--platform-matrix "$platform_matrix"' in workflow
    assert "MUDRA_M3_CI_REPORT_JSON" in workflow
    assert "MUDRA_M3_CI_ARTIFACT_BASE64_JSON" in workflow


@pytest.mark.acceptance("E79")
def test_verified_platform_item_can_be_rechecked_after_active_item_advances() -> None:
    backlog = {"active_item": "MI-10"}
    _validate_active_item_selection(backlog, "MI-08", {"state": "VERIFIED"})

    with pytest.raises(VerificationError, match="active_item_mismatch"):
        _validate_active_item_selection(backlog, "MI-09", {"state": "IN_PROGRESS"})

    _validate_active_item_selection(
        {"active_item": "MI-10"}, "MI-10", {"state": "IN_PROGRESS"}
    )


@pytest.mark.acceptance("E84")
def test_locked_verifier_environment_has_complete_dependencies() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        cwd=ROOT,
        env=release_verifier.reproducible_env(),
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
    assert metadata["metadata_name"] == "mudra-interact"


@pytest.mark.acceptance("E82")
def test_frozen_candidate_inventory_checks_offline_report_and_exact_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit = "a" * 40
    tree = "b" * 64
    artifact_root = tmp_path / "release-artifacts" / PACKAGE_VERSION
    artifact_root.mkdir(parents=True)
    contents = {
        f"mudra_interact-{PACKAGE_VERSION}-py3-none-any.whl": b"synthetic wheel bytes",
        f"mudra_interact-{PACKAGE_VERSION}.tar.gz": b"synthetic sdist bytes",
    }
    frozen = []
    for filename, data in contents.items():
        (artifact_root / filename).write_bytes(data)
        frozen.append({
            "kind": "wheel" if filename.endswith(".whl") else "sdist",
            "filename": filename,
            "path": f"release-artifacts/{PACKAGE_VERSION}/{filename}",
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        })
    report_path = tmp_path / "evidence" / "releases" / "offline-qualification.json"
    report_path.parent.mkdir(parents=True)
    offline_report = {
        "mode": "offline",
        "source_commit": commit,
        "source_tree_sha256": tree,
        "checks": {
            "repeat_build": {"wheel_identical": True, "sdist_identical": True},
            "offline": {"negative_egress": {"runner_network_isolation": "VERIFIED"}},
        },
        "frozen_candidate_artifacts": frozen,
    }
    report_path.write_bytes(canonical_json_bytes(seal_report(offline_report)))
    monkeypatch.setattr(release_verifier, "ROOT", tmp_path)
    monkeypatch.setattr(release_verifier, "git_value", lambda *_args: commit)
    monkeypatch.setattr(release_verifier, "source_tree_sha256", lambda _root: tree)

    inventory = release_verifier.frozen_candidate_inventory(
        f"release-artifacts/{PACKAGE_VERSION}", "evidence/releases/offline-qualification.json",
    )

    assert {row["filename"] for row in inventory} == set(contents)
    assert {row["size_bytes"] for row in inventory} == {len(value) for value in contents.values()}

    malformed = json.loads(json.dumps(offline_report))
    malformed["frozen_candidate_artifacts"][0]["sha256"] = "invalid"
    report_path.write_bytes(canonical_json_bytes(seal_report(malformed)))
    with pytest.raises(ReleaseProofError) as error:
        release_verifier.frozen_candidate_inventory(
            f"release-artifacts/{PACKAGE_VERSION}", "evidence/releases/offline-qualification.json",
        )
    assert error.value.code == "artifact_inventory_invalid"


@pytest.mark.acceptance("E82")
def test_real_deterministic_sdist_uses_frozen_candidate_filename(tmp_path: Path) -> None:
    archive = release_verifier.deterministic_sdist(
        release_verifier.make_staging(release_verifier.ROOT, tmp_path / "source"),
        tmp_path / "sdist", release_verifier.reproducible_env(),
    )

    assert archive.name == f"mudra_interact-{PACKAGE_VERSION}.tar.gz"
    assert release_verifier.inspect_sdist(archive) == {
        "name": "mudra-interact",
        "version": PACKAGE_VERSION,
        "summary": release_verifier.PACKAGE_SUMMARY,
        "description_sha256": sha256_text_file(ROOT / "README.md"),
        "metadata_version": "2.4",
        "package_modules": [
            "mudra_interact_core/__init__.py",
            "mudra_interact_core/a2a.py",
        ],
    }
    extracted = release_verifier.extract_sdist(archive, tmp_path / "extracted")
    assert extracted.name == f"mudra_interact-{PACKAGE_VERSION}"
    assert (extracted / "pyproject.toml").is_file()


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
    required_cell_count = len(REQUIRED_PLATFORMS) * len(REQUIRED_PYTHONS)
    if len([row for row in release_report["platform_matrix"] if row["state"] == "VERIFIED"]) < required_cell_count:
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
    required_cell_count = len(EXPECTED_CELLS)
    partial = aggregate_receipt_documents(synthetic_receipts[:-1], **aggregate_args)
    assert partial["state"] == "BLOCKED"
    assert partial["matrix"]["verified_cells"] == required_cell_count - 1
    assert partial["matrix"]["missing_cells"] == 1
    complete = aggregate_receipt_documents(synthetic_receipts, **aggregate_args)
    assert complete["state"] == "VERIFIED"
    assert complete["matrix"]["verified_cells"] == required_cell_count
    aggregate_path = Path("evidence/local") / f"matrix-fixture-{os.getpid()}.json"
    try:
        write_matrix_report(ROOT, aggregate_path.as_posix(), complete)
        validated = validate_aggregate_report(
            ROOT,
            aggregate_path.as_posix(),
            current_identity=identity,
            current_commit=candidate_commit,
        )
        assert validated["matrix"]["verified_cells"] == required_cell_count
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
