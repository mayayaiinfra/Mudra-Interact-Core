"""MI-10 release safety and recovery acceptance tests.

All artifact bytes and remote responses in this module are synthetic.  They
exercise fail-closed logic only and can never satisfy live publication proof.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace
from typing import Any

import pytest

from tools import release_proof
from tools import verify_release
from tools.verification_report import seal_report, sha256_text_file, source_tree_sha256


ROOT = Path(__file__).resolve().parents[1]
WHEEL_NAME = "mudra_interact-0.2.0-py3-none-any.whl"
SDIST_NAME = "mudra_interact-0.2.0.tar.gz"


def artifact_bytes() -> dict[str, bytes]:
    return {
        WHEEL_NAME: b"synthetic-wheel-MUDRA",
        SDIST_NAME: b"synthetic-sdist-MUDRA",
    }


def artifact_inventory(data: dict[str, bytes] | None = None) -> list[dict[str, Any]]:
    contents = data or artifact_bytes()
    return [
        {"filename": name, "sha256": hashlib.sha256(body).hexdigest(), "size_bytes": len(body)}
        for name, body in sorted(contents.items())
    ]


def valid_manifest_parts(tmp_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    tree = source_tree_sha256(ROOT)
    hashes = {
        "source_tree_sha256": tree,
        "spec_sha256": sha256_text_file(ROOT / "MUDRA_INTERACT_CORE_SPEC.md"),
        "acceptance_sha256": sha256_text_file(ROOT / "docs" / "ACCEPTANCE.md"),
        "tool_lock_sha256": sha256_text_file(ROOT / "requirements-dev.lock"),
    }
    candidate: dict[str, Any] = {
        "package": release_proof.PACKAGE,
        "version": release_proof.VERSION,
        "repository": release_proof.REPOSITORY,
        "workflow_path": release_proof.WORKFLOW,
        "source_commit": "a" * 40,
        **hashes,
        "tag": "v0.2.0",
        "workflow_run_id": 12345,
        "workflow_run_attempt": 1,
        "artifacts": artifact_inventory(),
    }
    candidate["candidate_fingerprint"] = release_proof.fingerprint(candidate)
    offline_path = tmp_path / "offline.json"
    offline_document = seal_report({
        "source_commit": candidate["source_commit"],
        "source_tree_sha256": tree,
        "mode": "offline",
        "checks": {
            "repeat_build": {"wheel_identical": True, "sdist_identical": True},
            "fresh_install": {"install_exit": 0, "smoke_exit": 0},
            "offline": {"negative_egress": {"runner_network_isolation": "VERIFIED"}},
        },
        "frozen_candidate_artifacts": [
            {"kind": "wheel", "filename": row["filename"], "path": row["filename"],
             "sha256": row["sha256"], "size_bytes": row["size_bytes"]}
            for row in artifact_inventory() if row["filename"].endswith(".whl")
        ] + [
            {"kind": "sdist", "filename": row["filename"], "path": row["filename"],
             "sha256": row["sha256"], "size_bytes": row["size_bytes"]}
            for row in artifact_inventory() if row["filename"].endswith(".tar.gz")
        ],
    })
    offline_path.write_text(json.dumps(offline_document), encoding="utf-8")
    index_refs = {}
    for index in ("testpypi", "pypi"):
        index_path = tmp_path / f"{index}.json"
        index_checks = {
            "index": index,
            "downloaded_and_hashed": True,
            "fresh_installed_wheel_smoke": True,
        }
        if index == "pypi":
            index_checks.update({
                "trusted_publisher_attestations": 2,
                "attestation_source_commit": candidate["source_commit"],
                "attestation_workflow_run_id": candidate["workflow_run_id"],
                "attestation_workflow_run_attempt": candidate["workflow_run_attempt"],
                "publisher_environment_assertion": "pypi-production",
                "candidate_workflow_environment_binding": True,
            })
        index_document = seal_report({
            "state": "VERIFIED", "mode": f"verify_{index}",
            "source_commit": candidate["source_commit"], "source_tree_sha256": tree,
            "checks": index_checks,
            "artifacts": artifact_inventory(),
        })
        index_path.write_text(json.dumps(index_document), encoding="utf-8")
        index_refs[index] = {"path": f"evidence/releases/{index}.json", "sha256": "0" * 64}
    manifest = {
        "schema_version": 1,
        "state": "PUBLISHED",
        "verification_kind": "luna_self_verified",
        "candidate": candidate,
        "authorization": {
            "kind": "github_protected_environment",
            "environment": "pypi-production",
            "workflow_run_id": 12345,
            "workflow_run_attempt": 1,
            "candidate_fingerprint": candidate["candidate_fingerprint"],
        },
        "gate_evidence": [{"gate": gate, "path": f"evidence/local/{gate}.json", "sha256": "0" * 64}
                          for gate in ("M0", "M1", "M2", "M3")],
        "offline_report": {"path": "evidence/releases/offline.json", "sha256": "0" * 64},
        "index_evidence": index_refs,
        "release_url": f"https://github.com/{release_proof.REPOSITORY}/releases/tag/v0.2.0",
    }
    return manifest, hashes


@pytest.mark.acceptance("E90")
def test_manifest_requires_repository_identity_and_candidate_specific_authorization(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest, hashes = valid_manifest_parts(tmp_path)
    monkeypatch.setattr(release_proof, "_validate_gate_receipts", lambda *_args, **_kwargs: None)
    def lookup(_root: Path, reference: dict[str, str], **_kwargs: Any) -> Path:
        return tmp_path / ("offline.json" if reference["path"].endswith("offline.json") else Path(reference["path"]).name)

    monkeypatch.setattr(release_proof, "_file_reference", lookup)
    release_proof.validate_manifest(
        tmp_path, manifest, current_commit="a" * 40, current_tree=hashes["source_tree_sha256"],
        spec_sha256=hashes["spec_sha256"], acceptance_sha256=hashes["acceptance_sha256"],
        tool_lock_sha256=hashes["tool_lock_sha256"],
    )
    missing_auth = {**manifest, "authorization": {}}
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.validate_manifest(
            tmp_path, missing_auth, current_commit="a" * 40, current_tree=hashes["source_tree_sha256"],
            spec_sha256=hashes["spec_sha256"], acceptance_sha256=hashes["acceptance_sha256"],
            tool_lock_sha256=hashes["tool_lock_sha256"],
        )
    assert error.value.code == "release_authorization_missing"
    wrong_repo = json.loads(json.dumps(manifest))
    wrong_repo["candidate"]["repository"] = "attacker/other"
    unsigned = {key: value for key, value in wrong_repo["candidate"].items() if key != "candidate_fingerprint"}
    wrong_repo["candidate"]["candidate_fingerprint"] = release_proof.fingerprint(unsigned)
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.validate_manifest(
            tmp_path, wrong_repo, current_commit="a" * 40, current_tree=hashes["source_tree_sha256"],
            spec_sha256=hashes["spec_sha256"], acceptance_sha256=hashes["acceptance_sha256"],
            tool_lock_sha256=hashes["tool_lock_sha256"],
        )
    assert error.value.code == "candidate_identity_mismatch"


@pytest.mark.acceptance("E91")
def test_frozen_candidate_rejects_stale_source_and_artifact_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, hashes = valid_manifest_parts(tmp_path)
    monkeypatch.setattr(release_proof, "_validate_gate_receipts", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        release_proof, "_file_reference",
        lambda _root, reference, **_kwargs: tmp_path / ("offline.json" if reference["path"].endswith("offline.json") else Path(reference["path"]).name),
    )
    rows = artifact_inventory()
    assert len(release_proof._validate_artifact_inventory(rows)) == 2
    rows[0]["sha256"] = "0" * 64
    tampered = json.loads(json.dumps(manifest))
    tampered["candidate"]["artifacts"] = rows
    unsigned = {key: value for key, value in tampered["candidate"].items() if key != "candidate_fingerprint"}
    tampered["candidate"]["candidate_fingerprint"] = release_proof.fingerprint(unsigned)
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.validate_manifest(
            tmp_path, tampered, current_commit="a" * 40, current_tree=hashes["source_tree_sha256"],
            spec_sha256=hashes["spec_sha256"], acceptance_sha256=hashes["acceptance_sha256"],
            tool_lock_sha256=hashes["tool_lock_sha256"],
        )
    assert error.value.code == "release_authorization_missing"
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.validate_manifest(
            tmp_path, manifest, current_commit="0" * 40, current_tree=hashes["source_tree_sha256"],
            spec_sha256=hashes["spec_sha256"], acceptance_sha256=hashes["acceptance_sha256"],
            tool_lock_sha256=hashes["tool_lock_sha256"],
        )
    assert error.value.code == "candidate_identity_mismatch"


def fake_index_fetch(index: str, contents: dict[str, bytes], download_contents: dict[str, bytes] | None = None):
    base = "https://test.pypi.org" if index == "testpypi" else "https://pypi.org"
    files_host = "test-files.pythonhosted.org" if index == "testpypi" else "files.pythonhosted.org"
    urls = [
        {
            "filename": name,
            "digests": {"sha256": hashlib.sha256(body).hexdigest()},
            "size": len(body),
            "yanked": False,
            "url": f"https://{files_host}/files/{name}",
        }
        for name, body in sorted(contents.items())
    ]
    response = {"info": {"name": "mudra-interact", "version": "0.2.0"}, "urls": urls}
    responses = {f"{base}/pypi/mudra-interact/0.2.0/json": json.dumps(response).encode()}
    downloaded = download_contents or contents
    responses.update({item["url"]: downloaded[item["filename"]] for item in urls})

    def fetch(url: str, *, max_bytes: int):
        body = responses[url]
        return 200, url, body

    return fetch


@pytest.mark.acceptance("E92")
def test_testpypi_exact_download_and_fresh_install_smoke_without_fallback() -> None:
    contents = artifact_bytes()
    calls: list[str] = []
    fetch = fake_index_fetch("testpypi", contents)

    def record(url: str, *, max_bytes: int):
        calls.append(url)
        return fetch(url, max_bytes=max_bytes)

    receipt = release_proof.verify_index(
        "testpypi", artifact_inventory(contents), fetch=record,
        install=lambda wheel, *, package_version: wheel.name == WHEEL_NAME and package_version == "0.2.0",
    )
    assert receipt["state"] == "VERIFIED"
    assert receipt["downloaded_and_hashed"] is True
    assert receipt["fresh_installed_wheel_smoke"] is True
    assert len(calls) == 3
    bad = dict(contents)
    bad[SDIST_NAME] = b"different bytes"
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.verify_index(
            "testpypi", artifact_inventory(contents), fetch=fake_index_fetch("testpypi", contents, bad),
            install=lambda _wheel, *, package_version: True,
        )
    assert error.value.code == "artifact_hash_mismatch"

    def redirected_download(url: str, *, max_bytes: int):
        response = fetch(url, max_bytes=max_bytes)
        if url.startswith("https://test-files.pythonhosted.org/"):
            return response[0], response[1].replace("test-files.pythonhosted.org", "test.pypi.org"), response[2]
        return response

    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.verify_index(
            "testpypi", artifact_inventory(contents), fetch=redirected_download,
            install=lambda _wheel, *, package_version: True,
        )
    assert error.value.code == "artifact_download_failed"


@pytest.mark.acceptance("E92")
def test_testpypi_default_install_callback_uses_fresh_venv_and_keyword_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[list[str]] = []

    class FakeBuilder:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def create(self, path: Path) -> None:
            path.mkdir(parents=True)

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(release_proof.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(release_proof.subprocess, "run", fake_run)

    receipt = release_proof.verify_index(
        "testpypi", artifact_inventory(), fetch=fake_index_fetch("testpypi", artifact_bytes()),
    )

    assert receipt["fresh_installed_wheel_smoke"] is True
    assert len(commands) == 2
    assert commands[0][-1].endswith(WHEEL_NAME)
    assert "0.2.0" in commands[1][-1]
    assert "import importlib.metadata" in commands[1][-1]


@pytest.mark.acceptance("E92")
def test_verify_release_cli_wires_candidate_download_to_default_install(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    contents = artifact_bytes()
    source_commit = "a" * 40
    source_tree = "b" * 64
    artifact_root = tmp_path / "release-artifacts" / "0.2.0"
    artifact_root.mkdir(parents=True)
    frozen = []
    for filename, body in contents.items():
        (artifact_root / filename).write_bytes(body)
        frozen.append({
            "kind": "wheel" if filename.endswith(".whl") else "sdist",
            "filename": filename,
            "path": f"release-artifacts/0.2.0/{filename}",
            "sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
        })
    offline = seal_report({
        "mode": "offline", "source_commit": source_commit,
        "source_tree_sha256": source_tree,
        "checks": {
            "repeat_build": {"wheel_identical": True, "sdist_identical": True},
            "offline": {"negative_egress": {"runner_network_isolation": "VERIFIED"}},
        },
        "frozen_candidate_artifacts": frozen,
    })
    offline_path = tmp_path / "evidence" / "releases" / "offline-qualification.json"
    offline_path.parent.mkdir(parents=True)
    offline_path.write_bytes(release_proof.canonical_json_bytes(offline))

    monkeypatch.setattr(verify_release, "ROOT", tmp_path)
    monkeypatch.setattr(verify_release, "git_value", lambda *_args: source_commit)
    monkeypatch.setattr(verify_release, "source_tree_sha256", lambda _root: source_tree)
    monkeypatch.setattr(verify_release, "sha256_text_file", lambda _path: "c" * 64)
    monkeypatch.setattr(verify_release, "current_platform", lambda: {
        "os": "linux", "architecture": "x86_64", "python": "3.14.8",
    })
    fetch = fake_index_fetch("testpypi", contents)

    class FakeResponse:
        status = 200

        def __init__(self, url: str, body: bytes) -> None:
            self.url = url
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *_args: Any) -> None:
            return None

        def geturl(self) -> str:
            return self.url

        def read(self, size: int = -1) -> bytes:
            return self.body if size < 0 else self.body[:size]

    class FakeOpener:
        def open(self, request: Any, *, timeout: int):
            del timeout
            status, url, body = fetch(request.full_url, max_bytes=release_proof.MAX_ARTIFACT_BYTES)
            assert status == 200
            return FakeResponse(url, body)

    class FakeBuilder:
        def __init__(self, **_kwargs: Any) -> None:
            pass

        def create(self, path: Path) -> None:
            path.mkdir(parents=True)

    def fake_run(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(release_proof.urllib.request, "build_opener", lambda *_args: FakeOpener())
    monkeypatch.setattr(release_proof.venv, "EnvBuilder", FakeBuilder)
    monkeypatch.setattr(release_proof.subprocess, "run", fake_run)

    result = verify_release.main([
        "--verify-index", "testpypi",
        "--artifact-dir", "release-artifacts/0.2.0",
        "--candidate-report", "evidence/releases/offline-qualification.json",
        "--report", "evidence/releases/testpypi-verification.json",
    ])

    assert result == 0
    receipt = json.loads((tmp_path / "evidence/releases/testpypi-verification.json").read_text(encoding="utf-8"))
    assert receipt["state"] == "VERIFIED"
    assert receipt["mode"] == "verify_testpypi"
    assert receipt["checks"]["fresh_installed_wheel_smoke"] is True


@pytest.mark.acceptance("E93")
def test_production_download_verifies_same_hashes_and_attestation(monkeypatch: pytest.MonkeyPatch) -> None:
    contents = artifact_bytes()
    attested: list[tuple[str, dict[str, Any]]] = []

    monkeypatch.setattr(
        release_proof, "_verify_candidate_publish_workflow",
        lambda _root, source_commit: {"candidate_commit": source_commit},
    )

    def verify_attestation(name: str, **kwargs: Any) -> bool:
        path = kwargs["artifact_path"]
        assert path.is_file()
        assert path.read_bytes() == contents[name]
        attested.append((name, kwargs))
        return True

    monkeypatch.setattr(
        release_proof,
        "_verify_pypi_attestation",
        verify_attestation,
    )
    receipt = release_proof.verify_index(
        "pypi", artifact_inventory(contents), fetch=fake_index_fetch("pypi", contents),
        source_commit="a" * 40, workflow_run_id=12345, workflow_run_attempt=1,
        install=lambda wheel, *, package_version: wheel.name == WHEEL_NAME and package_version == "0.2.0",
    )
    assert receipt["trusted_publisher_attestations"] == 2
    assert {name for name, _kwargs in attested} == {WHEEL_NAME, SDIST_NAME}
    assert all(kwargs["source_commit"] == "a" * 40 for _, kwargs in attested)
    assert all(kwargs["workflow_run_id"] == 12345 for _, kwargs in attested)
    assert all(kwargs["workflow_run_attempt"] == 1 for _, kwargs in attested)
    assert all(not kwargs["artifact_path"].exists() for _, kwargs in attested)
    assert receipt["attestation_source_commit"] == "a" * 40
    assert receipt["downloaded_and_hashed"] and receipt["fresh_installed_wheel_smoke"]


@pytest.mark.acceptance("E94")
def test_release_workflow_is_pinned_separated_and_documents_exact_downloads() -> None:
    workflow = (ROOT / ".github/workflows/publish.yml").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/RELEASE_RUNBOOK.md").read_text(encoding="utf-8")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "pypi-production" in workflow and "testpypi" in workflow
    assert "id-token: write" in workflow and "secrets.PYPI_API_TOKEN" not in workflow
    assert "gh release create" in workflow and "--target" in workflow
    assert "pypa/gh-action-pypi-publish@dc37677b2e1c63e2034f94d8a5b11f265b73ba33" in workflow
    assert "actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9" in workflow
    assert "actions/download-artifact@9000827ccba6bdab643e8b6fd33ac0654aef8333" in workflow
    action_refs = [line.strip().split()[1] for line in workflow.splitlines() if line.strip().startswith("uses:")]
    assert action_refs
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}", ref) for ref in action_refs)
    assert "path: evidence/releases/testpypi-verification.json" in workflow
    assert "path: evidence/releases/pypi-verification.json" in workflow
    assert "python-version: '3.12'" in workflow
    normalized_runbook = " ".join(runbook.lower().split())
    assert "same frozen files" in normalized_runbook and "no rebuild" in normalized_runbook
    assert "https://pypi.org/project/mudra-interact/0.2.0/" in readme
    assert "--no-deps" in runbook and "TestPyPI" in runbook
    assert "may approve their own run" in normalized_runbook
    assert "administrator bypass is disabled" in normalized_runbook
    assert "not an independent review" in normalized_runbook
    lock = (ROOT / "requirements-release.lock").read_text(encoding="utf-8")
    requirements = {
        line.split("==", 1)[0].casefold().replace("_", "-")
        for line in (ROOT / "requirements-release.in").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    entries = [line for line in lock.splitlines() if "==" in line]
    assert len(entries) == len(requirements)
    assert {line.split("==", 1)[0].casefold().replace("_", "-") for line in entries} == requirements
    hashes = re.findall(r"--hash=sha256:([0-9a-f]+)", lock)
    assert len(hashes) == len(entries)
    assert all(len(digest) == 64 for digest in hashes)


@pytest.mark.acceptance("E94")
def test_production_environment_requires_solo_owner_manual_approval_main_only_and_no_bypass() -> None:
    environment_url = (
        f"https://api.github.com/repos/{release_proof.REPOSITORY}"
        f"/environments/{release_proof.PRODUCTION_ENVIRONMENT}"
    )
    environment = {
        "name": release_proof.PRODUCTION_ENVIRONMENT,
        "can_admins_bypass": False,
        "protection_rules": [{
            "type": "required_reviewers",
            "reviewers": [{"type": "User", "id": 123}],
            "prevent_self_review": False,
        }],
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
    }
    branch_policies = {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}

    def check(
        candidate_environment: dict[str, Any],
        candidate_policies: dict[str, Any] = branch_policies,
    ) -> dict[str, Any]:
        def fetch(url: str, *, max_bytes: int) -> tuple[int, str, bytes]:
            del max_bytes
            body = candidate_environment if url == environment_url else candidate_policies
            return 200, url, json.dumps(body).encode("utf-8")

        return release_proof._verify_environment_configuration(release_proof.REPOSITORY, fetch)

    assert check(environment) == {
        "environment": "pypi-production",
        "required_reviewers": 1,
        "self_approval_allowed": True,
        "independent_review": False,
        "administrator_bypass": False,
        "deployment_branches": ["main"],
    }

    invalid_environments: list[dict[str, Any]] = []
    no_reviewers = json.loads(json.dumps(environment))
    no_reviewers["protection_rules"][0]["reviewers"] = []
    invalid_environments.append(no_reviewers)
    self_review_prevented = json.loads(json.dumps(environment))
    self_review_prevented["protection_rules"][0]["prevent_self_review"] = True
    invalid_environments.append(self_review_prevented)
    bypass_allowed = json.loads(json.dumps(environment))
    bypass_allowed["can_admins_bypass"] = True
    invalid_environments.append(bypass_allowed)
    no_branch_scope = json.loads(json.dumps(environment))
    no_branch_scope["deployment_branch_policy"] = {"protected_branches": True, "custom_branch_policies": False}
    invalid_environments.append(no_branch_scope)

    for invalid in invalid_environments:
        with pytest.raises(release_proof.ReleaseProofError) as error:
            check(invalid)
        assert error.value.code == "protected_environment_unconfigured"

    wrong_branch = {"total_count": 1, "branch_policies": [{"name": "release/*", "type": "branch"}]}
    with pytest.raises(release_proof.ReleaseProofError) as error:
        check(environment, wrong_branch)
    assert error.value.code == "protected_environment_unconfigured"


@pytest.mark.acceptance("E95")
def test_ambiguous_upload_retry_needs_exact_hashes_or_confirmed_absence() -> None:
    expected = artifact_inventory()
    assert release_proof.ambiguous_upload_decision(expected, None, exact_version_exists=None) == "inspect_again"
    assert release_proof.ambiguous_upload_decision(expected, expected, exact_version_exists=True) == "resume_matching_version"
    mismatch = json.loads(json.dumps(expected))
    mismatch[0]["sha256"] = "1" * 64
    assert release_proof.ambiguous_upload_decision(expected, mismatch, exact_version_exists=True) == "stop_hash_mismatch"
    assert release_proof.ambiguous_upload_decision(expected, [], exact_version_exists=True) == "stop_version_collision"
    assert release_proof.ambiguous_upload_decision(expected, None, exact_version_exists=False) == "inspect_again"
    assert release_proof.ambiguous_upload_decision(expected, None, exact_version_exists=False, absence_confirmed=True) == "retry_same_frozen_files"


@pytest.mark.acceptance("E96")
def test_rollback_requires_authorization_and_never_deletes_public_history() -> None:
    assert release_proof.rollback_decision(version="0.2.0", authorization_recorded=False) == "block_unapproved_yank_or_patch"
    assert release_proof.rollback_decision(version="0.2.0", authorization_recorded=True) == "authorized_yank_or_patch_only"
    assert release_proof.rollback_decision(version="0.2.0", authorization_recorded=True, delete_history=True) == "stop_invalid_rollback"
    assert release_proof.rollback_decision(version="0.1.0", authorization_recorded=True) == "stop_invalid_rollback"


@pytest.mark.acceptance("E97")
def test_public_download_and_release_links_are_exact_version_links() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/RELEASE_RUNBOOK.md").read_text(encoding="utf-8")
    assert "https://pypi.org/project/mudra-interact/0.2.0/" in readme
    assert "https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.2.0" in readme
    assert "index_version_missing" in runbook or "package page" in runbook.lower()
    assert "--index-url https://test.pypi.org/simple" in readme


@pytest.mark.acceptance("E98")
def test_foreign_publisher_expired_or_secret_bearing_claims_are_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest, hashes = valid_manifest_parts(tmp_path)
    manifest["authorization"]["pypi_token"] = "pypi-SYNTHETIC-NEVER-REAL"
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.validate_manifest(
            tmp_path, manifest, current_commit="a" * 40, current_tree=hashes["source_tree_sha256"],
            spec_sha256=hashes["spec_sha256"], acceptance_sha256=hashes["acceptance_sha256"],
            tool_lock_sha256=hashes["tool_lock_sha256"],
        )
    assert error.value.code == "release_authorization_missing"
    expired = json.loads(json.dumps(manifest))
    expired["authorization"].pop("pypi_token")
    expired["authorization"]["workflow_run_id"] = 54321
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.validate_manifest(
            tmp_path, expired, current_commit="a" * 40, current_tree=hashes["source_tree_sha256"],
            spec_sha256=hashes["spec_sha256"], acceptance_sha256=hashes["acceptance_sha256"],
            tool_lock_sha256=hashes["tool_lock_sha256"],
        )
    assert error.value.code == "release_authorization_missing"
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof._index_hosts("untrusted-index")
    assert error.value.code == "index_invalid"
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof._json_get(
            "https://pypi.org/integrity/synthetic",
            lambda *_args, **_kwargs: (200, "https://test.pypi.org/integrity/synthetic", b"{}"),
        )
    assert error.value.code == "remote_redirect_host_invalid"


@pytest.mark.acceptance("E93")
def test_verified_attestation_policy_binds_signed_commit_run_and_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Synthetic policy tests reject claim drift; they are not PyPI proof."""
    source_commit = "a" * 40
    workflow_run_id = 12345
    workflow_run_attempt = 2
    expected_claims = {
        "issuer": "https://token.actions.githubusercontent.com",
        "repository_uri": f"https://github.com/{release_proof.REPOSITORY}",
        "source_repository_digest": source_commit,
        "build_config_uri": (
            f"https://github.com/{release_proof.REPOSITORY}/"
            f"{release_proof.WORKFLOW}@refs/heads/main"
        ),
        "build_trigger": "workflow_dispatch",
        "run_invocation_uri": (
            f"https://github.com/{release_proof.REPOSITORY}/actions/runs/"
            f"{workflow_run_id}/attempts/{workflow_run_attempt}"
        ),
    }
    claim_for_policy = {
        "OIDCIssuerV2": "issuer",
        "OIDCSourceRepositoryURI": "repository_uri",
        "OIDCSourceRepositoryDigest": "source_repository_digest",
        "OIDCBuildConfigURI": "build_config_uri",
        "OIDCBuildTrigger": "build_trigger",
        "OIDCRunInvocationURI": "run_invocation_uri",
    }

    class ClaimPolicy:
        def __init__(self, name: str, value: str) -> None:
            self.name = name
            self.value = value

        def verify(self, claims: dict[str, str]) -> None:
            key = claim_for_policy[self.name]
            if claims.get(key) != self.value:
                raise ValueError("signed claim mismatch")

    class AllOf:
        def __init__(self, children: list[ClaimPolicy]) -> None:
            if not children:
                raise ValueError("empty policy")
            self.children = children

        def verify(self, claims: dict[str, str]) -> None:
            for child in self.children:
                child.verify(claims)

    def synthetic_policy(*, source_commit: str, workflow_run_id: int, workflow_run_attempt: int) -> AllOf:
        if (
            not release_proof.COMMIT_RE.fullmatch(source_commit)
            or type(workflow_run_id) is not int or workflow_run_id < 1
            or type(workflow_run_attempt) is not int or workflow_run_attempt < 1
        ):
            raise release_proof.ReleaseProofError("attestation_candidate_invalid")
        values = dict(expected_claims)
        values["source_repository_digest"] = source_commit
        values["run_invocation_uri"] = (
            f"https://github.com/{release_proof.REPOSITORY}/actions/runs/"
            f"{workflow_run_id}/attempts/{workflow_run_attempt}"
        )
        return AllOf([
            ClaimPolicy(name, values[key]) for name, key in claim_for_policy.items()
        ])

    monkeypatch.setattr(release_proof, "_pypi_attestation_policy", synthetic_policy)

    artifact_path = tmp_path / WHEEL_NAME
    artifact_path.write_bytes(b"synthetic-wheel-MUDRA")
    expected_digest = hashlib.sha256(artifact_path.read_bytes()).hexdigest()

    class SyntheticDistribution:
        @classmethod
        def from_file(cls, path: Path):
            return SimpleNamespace(path=path, name=path.name)

    class SyntheticAttestationType:
        PYPI_PUBLISH_V1 = SimpleNamespace(value="https://docs.pypi.org/attestations/publish/v1")

    class SyntheticAttestation:
        def __init__(self, claims: dict[str, str], digest: str) -> None:
            self.claims = claims
            self.digest = digest

        def verify(self, *, identity: AllOf, dist: SimpleNamespace):
            identity.verify(self.claims)
            if hashlib.sha256(dist.path.read_bytes()).hexdigest() != self.digest:
                raise ValueError("distribution digest mismatch")
            return SyntheticAttestationType.PYPI_PUBLISH_V1.value, {}

    class SyntheticProvenance:
        document: dict[str, Any]

        @classmethod
        def model_validate(cls, document: dict[str, Any]):
            return cls.document

    pypi_module = ModuleType("pypi_attestations")
    pypi_module.AttestationType = SyntheticAttestationType
    pypi_module.Distribution = SyntheticDistribution
    pypi_module.Provenance = SyntheticProvenance
    monkeypatch.setitem(sys.modules, "pypi_attestations", pypi_module)

    def verify_claims(
        claims: dict[str, str], *, digest: str = expected_digest,
        publisher_environment: str = "pypi-production",
    ) -> bool:
        attestation = SyntheticAttestation(claims, digest)
        SyntheticProvenance.document = SimpleNamespace(attestation_bundles=[SimpleNamespace(
            publisher=SimpleNamespace(
                kind="GitHub", repository=release_proof.REPOSITORY,
                workflow="publish.yml", environment=publisher_environment,
            ),
            attestations=[attestation],
        )])

        def provenance_fetch(_url: str, *, max_bytes: int):
            del max_bytes
            return 200, "https://pypi.org/integrity/synthetic", b"{}"

        return release_proof._verify_pypi_attestation(
            WHEEL_NAME,
            artifact_path=artifact_path,
            source_commit=source_commit,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
            fetch=provenance_fetch,
        )

    assert verify_claims(expected_claims) is True
    with pytest.raises(release_proof.ReleaseProofError) as error:
        verify_claims(expected_claims, publisher_environment="other-environment")
    assert error.value.code == "publisher_identity_mismatch"
    for key in expected_claims:
        wrong = dict(expected_claims)
        wrong[key] = "wrong-signed-claim"
        with pytest.raises(release_proof.ReleaseProofError) as error:
            verify_claims(wrong)
        assert error.value.code == "publisher_attestation_invalid"

        missing = dict(expected_claims)
        missing.pop(key)
        with pytest.raises(release_proof.ReleaseProofError) as error:
            verify_claims(missing)
        assert error.value.code == "publisher_attestation_invalid"

    with pytest.raises(release_proof.ReleaseProofError) as error:
        verify_claims(expected_claims, digest="0" * 64)
    assert error.value.code == "publisher_attestation_invalid"

    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof._pypi_attestation_policy(
            source_commit=source_commit,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=True,
        )
    assert error.value.code == "attestation_candidate_invalid"


@pytest.mark.acceptance("E98")
def test_attestation_signature_verifier_errors_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = tmp_path / WHEEL_NAME
    artifact.write_bytes(b"synthetic wheel")

    class Distribution:
        @classmethod
        def from_file(cls, path: Path):
            return SimpleNamespace(path=path)

    class Attestation:
        def verify(self, *, identity: object, dist: object):
            raise ValueError("synthetic signature verification failure")

    class Provenance:
        @classmethod
        def model_validate(cls, _document: dict[str, Any]):
            return SimpleNamespace(attestation_bundles=[SimpleNamespace(
                publisher=SimpleNamespace(
                    kind="GitHub", repository=release_proof.REPOSITORY,
                    workflow="publish.yml", environment="pypi-production",
                ),
                attestations=[Attestation()],
            )])

    class AttestationType:
        PYPI_PUBLISH_V1 = SimpleNamespace(value="https://docs.pypi.org/attestations/publish/v1")

    module = ModuleType("pypi_attestations")
    module.AttestationType = AttestationType
    module.Distribution = Distribution
    module.Provenance = Provenance
    monkeypatch.setitem(sys.modules, "pypi_attestations", module)
    monkeypatch.setattr(release_proof, "_pypi_attestation_policy", lambda **_kwargs: object())

    def fetch(_url: str, *, max_bytes: int):
        del max_bytes
        return 200, "https://pypi.org/integrity/synthetic", b"{}"

    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof._verify_pypi_attestation(
            WHEEL_NAME, artifact_path=artifact, source_commit="a" * 40,
            workflow_run_id=12345, workflow_run_attempt=2, fetch=fetch,
        )
    assert error.value.code == "publisher_attestation_invalid"


@pytest.mark.acceptance("E99")
def test_published_aggregator_blocks_absent_live_proof_and_separates_unverified_claims(tmp_path: Path) -> None:
    with pytest.raises(release_proof.ReleaseProofError) as error:
        release_proof.verify_published(
            tmp_path, "evidence/releases/published.json", current_commit="a" * 40,
            current_tree="b" * 64, spec_sha256="c" * 64,
            acceptance_sha256="d" * 64, tool_lock_sha256="e" * 64,
        )
    assert error.value.code == "manifest_file_missing"
    implementation = (ROOT / "tools/release_proof.py").read_text(encoding="utf-8")
    assert '"adapter_status": "not_implemented_in_public_core"' in implementation
    assert '"recognition_quality": "not_established_by_synthetic_tests"' in implementation
    assert '"cultural_review": "not_established_by_public_core"' in implementation
    report = ROOT / "build" / "test-m10-published-blocked.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable, "tools/verify_release.py", "--published",
            "--published-manifest", "evidence/releases/synthetic-missing-published.json",
            "--report", report.relative_to(ROOT).as_posix(),
        ],
        cwd=ROOT, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
    )
    document = json.loads(report.read_text(encoding="utf-8"))
    assert result.returncode == 2
    assert document["state"] == "BLOCKED"
    assert "publication proof" in " ".join(document["limitations"]).lower()
    assert document["checks"]["adapter_status"] == "not_implemented_in_public_core"
    assert document["checks"]["recognition_quality"] == "not_established_by_synthetic_tests"
    assert document["checks"]["cultural_review"] == "not_established_by_public_core"
