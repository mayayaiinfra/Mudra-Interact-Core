"""Fail-closed checks for frozen, published Mudra distributions.

The verifier is read-only: it never uploads, overwrites, deletes, or yanks a
release.  Publishing is performed by the protected GitHub Actions workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import venv
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from tools.verification_report import (
    canonical_json_bytes,
    read_json,
    sha256_file,
    sha256_text_file,
    source_tree_sha256,
    validate_receipt_file,
)


PACKAGE = "mudra-interact"
VERSION = "0.2.0"
REPOSITORY = "mayayaiinfra/Mudra-Interact-Core"
WORKFLOW = ".github/workflows/publish.yml"
PRODUCTION_ENVIRONMENT = "pypi-production"
MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ALLOWED_ROOT_HOSTS = {
    "pypi.org", "test.pypi.org", "api.github.com", "github.com",
}


class ReleaseProofError(Exception):
    """An input-independent error code safe to include in public evidence."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _pypi_attestation_policy(
    *, source_commit: str, workflow_run_id: int, workflow_run_attempt: int,
) -> Any:
    """Build the required Sigstore identity policy for one frozen release run."""
    if (
        not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit)
        or type(workflow_run_id) is not int or workflow_run_id < 1
        or type(workflow_run_attempt) is not int or workflow_run_attempt < 1
    ):
        raise ReleaseProofError("attestation_candidate_invalid")
    try:
        from sigstore.verify import policy
    except ImportError:
        raise ReleaseProofError("attestation_verifier_unavailable") from None
    run_uri = (
        f"https://github.com/{REPOSITORY}/actions/runs/"
        f"{workflow_run_id}/attempts/{workflow_run_attempt}"
    )
    try:
        return policy.AllOf([
            policy.OIDCIssuerV2("https://token.actions.githubusercontent.com"),
            policy.OIDCSourceRepositoryURI(f"https://github.com/{REPOSITORY}"),
            policy.OIDCSourceRepositoryDigest(source_commit),
            policy.OIDCBuildConfigURI(
                f"https://github.com/{REPOSITORY}/{WORKFLOW}@refs/heads/main"
            ),
            policy.OIDCBuildTrigger("workflow_dispatch"),
            policy.OIDCRunInvocationURI(run_uri),
        ])
    except (AttributeError, TypeError):
        raise ReleaseProofError("attestation_verifier_unavailable") from None


def _verify_candidate_publish_workflow(root: Path, source_commit: str) -> dict[str, str]:
    """Bind the PyPI upload assertion to the immutable candidate workflow.

    PyPI's publisher environment is an index assertion, not a Fulcio OIDC
    extension.  The signed source digest and workflow identity are joined to
    the workflow file in that exact checked-out candidate commit here.
    """
    if not isinstance(source_commit, str) or not COMMIT_RE.fullmatch(source_commit):
        raise ReleaseProofError("publisher_workflow_mismatch")
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "show", f"{source_commit}:{WORKFLOW}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        raise ReleaseProofError("publisher_workflow_unavailable") from None
    if result.returncode != 0:
        raise ReleaseProofError("publisher_workflow_unavailable")
    try:
        import yaml

        class UniqueLoader(yaml.SafeLoader):
            pass

        def construct_mapping(loader: Any, node: Any, deep: bool = False) -> dict[Any, Any]:
            loader.flatten_mapping(node)
            mapping: dict[Any, Any] = {}
            for key_node, value_node in node.value:
                key = loader.construct_object(key_node, deep=deep)
                if key in mapping:
                    raise ValueError("duplicate YAML key")
                mapping[key] = loader.construct_object(value_node, deep=deep)
            return mapping

        UniqueLoader.add_constructor(
            yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, construct_mapping,
        )
        workflow = yaml.load(result.stdout, Loader=UniqueLoader)
    except Exception:
        raise ReleaseProofError("publisher_workflow_mismatch") from None
    try:
        job = workflow["jobs"]["publish-pypi"]
        environment = job["environment"]
        steps = job["steps"]
        download, publish = steps
        download_use = download["uses"]
        publish_use = publish["uses"]
        correct = (
            job["needs"] == ["verify-testpypi", "qualify-candidate"]
            and isinstance(environment, dict)
            and environment.get("name") == PRODUCTION_ENVIRONMENT
            and job["permissions"] == {"contents": "read", "id-token": "write"}
            and download["name"] == "Download the same frozen candidate"
            and isinstance(download_use, str)
            and re.fullmatch(r"actions/download-artifact@[0-9a-f]{40}", download_use)
            and download["with"] == {
                "name": "mudra-candidate-${{ inputs.version }}",
                "path": "candidate",
            }
            and publish["name"] == "Publish the same files to PyPI"
            and isinstance(publish_use, str)
            and re.fullmatch(r"pypa/gh-action-pypi-publish@[0-9a-f]{40}", publish_use)
            and publish["with"] == {"packages-dir": "candidate/release-artifacts/0.2.0/"}
        )
    except (KeyError, TypeError, ValueError):
        correct = False
    if not correct:
        raise ReleaseProofError("publisher_workflow_mismatch")
    return {
        "environment": PRODUCTION_ENVIRONMENT,
        "workflow_path": WORKFLOW,
        "candidate_commit": source_commit,
        "proof_kind": "signed_candidate_source_workflow",
    }
def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseProofError("manifest_duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ReleaseProofError("manifest_nonfinite_number")


def strict_json(data: bytes) -> Any:
    if len(data) > 1024 * 1024 or data.startswith(b"\xef\xbb\xbf"):
        raise ReleaseProofError("manifest_invalid")
    try:
        return json.loads(
            data.decode("utf-8", errors="strict"),
            object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_reject_constant,
        )
    except ReleaseProofError:
        raise
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError):
        raise ReleaseProofError("manifest_invalid") from None


def fingerprint(candidate: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(candidate)).hexdigest()


def _safe_repo_file(root: Path, relative: Any, *, prefix: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ReleaseProofError("manifest_path_invalid")
    posix = PurePosixPath(relative)
    if (
        posix.is_absolute() or ".." in posix.parts or "." in posix.parts
        or not relative.startswith(prefix + "/") or posix.as_posix() != relative
    ):
        raise ReleaseProofError("manifest_path_invalid")
    target = root.joinpath(*posix.parts)
    try:
        resolved_root = root.resolve(strict=True)
        resolved_target = target.resolve(strict=False)
        resolved_target.relative_to(resolved_root)
    except (OSError, ValueError):
        raise ReleaseProofError("manifest_path_invalid") from None
    cursor = resolved_root
    for part in posix.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ReleaseProofError("manifest_path_invalid")
    if not resolved_target.exists():
        raise ReleaseProofError("manifest_file_missing")
    if not resolved_target.is_file():
        raise ReleaseProofError("manifest_path_invalid")
    return resolved_target


def _file_reference(root: Path, reference: Any, *, prefix: str) -> Path:
    if not isinstance(reference, dict) or set(reference) != {"path", "sha256"}:
        raise ReleaseProofError("manifest_reference_invalid")
    path = _safe_repo_file(root, reference["path"], prefix=prefix)
    if not isinstance(reference["sha256"], str) or not SHA256_RE.fullmatch(reference["sha256"]):
        raise ReleaseProofError("manifest_reference_invalid")
    if sha256_file(path) != reference["sha256"]:
        raise ReleaseProofError("manifest_reference_hash_mismatch")
    return path


def _validate_artifact_inventory(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != 2:
        raise ReleaseProofError("artifact_inventory_invalid")
    expected_names = {
        f"mudra_interact-{VERSION}-py3-none-any.whl",
        f"mudra_interact-{VERSION}.tar.gz",
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"filename", "sha256", "size_bytes"}:
            raise ReleaseProofError("artifact_inventory_invalid")
        name = item["filename"]
        digest = item["sha256"]
        size = item["size_bytes"]
        if (
            not isinstance(name, str) or name not in expected_names or name in seen
            or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest)
            or type(size) is not int or size < 1 or size > MAX_ARTIFACT_BYTES
        ):
            raise ReleaseProofError("artifact_inventory_invalid")
        seen.add(name)
        rows.append({"filename": name, "sha256": digest, "size_bytes": size})
    if seen != expected_names:
        raise ReleaseProofError("artifact_inventory_invalid")
    return sorted(rows, key=lambda row: row["filename"])


def _validate_gate_receipts(root: Path, evidence: Any, identity: dict[str, str]) -> None:
    if not isinstance(evidence, list) or len(evidence) != 4:
        raise ReleaseProofError("gate_evidence_invalid")
    try:
        from tools.verify_gate import _validate_receipt_record, acceptance_owners, validate_ledger

        ledger = read_json(root / "IMPLEMENTATION_BACKLOG.json", max_bytes=4 * 1024 * 1024)
        items, gates = validate_ledger(root, ledger, acceptance_owners(root))
    except Exception:
        raise ReleaseProofError("gate_evidence_invalid") from None
    by_gate: dict[str, dict[str, str]] = {}
    for record in evidence:
        if not isinstance(record, dict) or set(record) != {"gate", "path", "sha256"}:
            raise ReleaseProofError("gate_evidence_invalid")
        gate = record["gate"]
        if gate not in {"M0", "M1", "M2", "M3"} or gate in by_gate:
            raise ReleaseProofError("gate_evidence_invalid")
        ledger_gate = gates.get(gate)
        if not isinstance(ledger_gate, dict) or ledger_gate.get("state") != "VERIFIED":
            raise ReleaseProofError("gate_evidence_invalid")
        path = _safe_repo_file(root, record["path"], prefix="evidence/local")
        if not isinstance(record["sha256"], str) or not SHA256_RE.fullmatch(record["sha256"]):
            raise ReleaseProofError("gate_evidence_invalid")
        required_cases = [case for item_id in ledger_gate["items"] for case in items[item_id]["acceptance_ids"]]
        try:
            report = read_json(path, max_bytes=4 * 1024 * 1024)
            validate_receipt_file(
                root,
                record["path"],
                record["sha256"],
                current_identity=identity,
            )
            _validate_receipt_record(
                root, ledger_gate, target={"kind": "gate", "id": gate},
                required_cases=set(required_cases), current_identity=identity,
            )
        except Exception:
            raise ReleaseProofError("gate_evidence_invalid") from None
        if not any(entry == {"path": record["path"], "sha256": record["sha256"]} for entry in ledger_gate.get("evidence", [])):
            raise ReleaseProofError("gate_evidence_invalid")
        if (
            not isinstance(report, dict) or report.get("state") != "VERIFIED"
            or report.get("scope") != {"kind": "gate", "id": gate}
            or report.get("verification_kind") != "luna_self_verified"
        ):
            raise ReleaseProofError("gate_evidence_invalid")
        by_gate[gate] = {"path": record["path"], "sha256": record["sha256"]}
    if set(by_gate) != {"M0", "M1", "M2", "M3"}:
        raise ReleaseProofError("gate_evidence_invalid")


def validate_manifest(
    root: Path,
    manifest: Any,
    *,
    current_commit: str,
    current_tree: str,
    spec_sha256: str,
    acceptance_sha256: str,
    tool_lock_sha256: str,
) -> dict[str, Any]:
    required = {
        "schema_version", "state", "verification_kind", "candidate",
        "authorization", "gate_evidence", "offline_report", "index_evidence", "release_url",
    }
    if not isinstance(manifest, dict) or set(manifest) != required:
        raise ReleaseProofError("manifest_shape_invalid")
    candidate = manifest["candidate"]
    candidate_fields = {
        "package", "version", "repository", "workflow_path", "source_commit",
        "source_tree_sha256", "spec_sha256", "acceptance_sha256",
        "tool_lock_sha256", "tag", "workflow_run_id", "candidate_fingerprint",
        "workflow_run_attempt", "artifacts",
    }
    if not isinstance(candidate, dict) or set(candidate) != candidate_fields:
        raise ReleaseProofError("candidate_shape_invalid")
    string_fields = (
        "package", "version", "repository", "workflow_path", "source_commit",
        "source_tree_sha256", "spec_sha256", "acceptance_sha256", "tool_lock_sha256",
        "tag", "candidate_fingerprint",
    )
    if any(not isinstance(candidate.get(field), str) for field in string_fields):
        raise ReleaseProofError("candidate_shape_invalid")
    artifacts = _validate_artifact_inventory(candidate["artifacts"])
    candidate_unsigned = {key: value for key, value in candidate.items() if key != "candidate_fingerprint"}
    if (
        manifest["schema_version"] != 1 or manifest["state"] != "PUBLISHED"
        or manifest["verification_kind"] != "luna_self_verified"
        or candidate["package"] != PACKAGE or candidate["version"] != VERSION
        or candidate["repository"].casefold() != REPOSITORY.casefold()
        or candidate["workflow_path"] != WORKFLOW or candidate["tag"] != f"v{VERSION}"
        or not isinstance(candidate["source_commit"], str)
        or not COMMIT_RE.fullmatch(candidate["source_commit"])
        or candidate["source_commit"] != current_commit
        or candidate["source_tree_sha256"] != current_tree
        or candidate["spec_sha256"] != spec_sha256
        or candidate["acceptance_sha256"] != acceptance_sha256
        or candidate["tool_lock_sha256"] != tool_lock_sha256
        or type(candidate["workflow_run_id"]) is not int or candidate["workflow_run_id"] < 1
        or type(candidate["workflow_run_attempt"]) is not int or candidate["workflow_run_attempt"] < 1
        or candidate["candidate_fingerprint"] != fingerprint(candidate_unsigned)
    ):
        raise ReleaseProofError("candidate_identity_mismatch")
    authorization = manifest["authorization"]
    if (
        not isinstance(authorization, dict)
        or set(authorization) != {
            "kind", "environment", "workflow_run_id", "workflow_run_attempt", "candidate_fingerprint",
        }
        or authorization.get("kind") != "github_protected_environment"
        or authorization.get("environment") != PRODUCTION_ENVIRONMENT
        or authorization.get("workflow_run_id") != candidate["workflow_run_id"]
        or authorization.get("workflow_run_attempt") != candidate["workflow_run_attempt"]
        or authorization.get("candidate_fingerprint") != candidate["candidate_fingerprint"]
    ):
        raise ReleaseProofError("release_authorization_missing")
    _validate_gate_receipts(root, manifest["gate_evidence"], {
        "source_tree_sha256": current_tree,
        "spec_sha256": spec_sha256,
        "acceptance_sha256": acceptance_sha256,
        "tool_lock_sha256": tool_lock_sha256,
    })
    offline = _file_reference(root, manifest["offline_report"], prefix="evidence/releases")
    try:
        offline_report = read_json(offline, max_bytes=4 * 1024 * 1024)
    except Exception:
        raise ReleaseProofError("offline_report_invalid") from None
    if not isinstance(offline_report, dict) or not isinstance(offline_report.get("report_sha256"), str):
        raise ReleaseProofError("offline_report_invalid")
    index_evidence = manifest["index_evidence"]
    if not isinstance(index_evidence, dict) or set(index_evidence) != {"testpypi", "pypi"}:
        raise ReleaseProofError("index_evidence_invalid")
    for index in ("testpypi", "pypi"):
        report_path = _file_reference(root, index_evidence[index], prefix="evidence/releases")
        try:
            index_report = read_json(report_path, max_bytes=4 * 1024 * 1024)
        except Exception:
            raise ReleaseProofError("index_evidence_invalid") from None
        if not isinstance(index_report, dict) or not isinstance(index_report.get("report_sha256"), str):
            raise ReleaseProofError("index_evidence_invalid")
        index_body = dict(index_report)
        index_digest = index_body.pop("report_sha256")
        if hashlib.sha256(canonical_json_bytes(index_body)).hexdigest() != index_digest:
            raise ReleaseProofError("index_evidence_invalid")
        if (
            index_report.get("state") != "VERIFIED"
            or index_report.get("mode") != f"verify_{index}"
            or index_report.get("source_commit") != current_commit
            or index_report.get("source_tree_sha256") != current_tree
            or index_report.get("checks", {}).get("index") != index
            or index_report.get("checks", {}).get("downloaded_and_hashed") is not True
            or index_report.get("checks", {}).get("fresh_installed_wheel_smoke") is not True
            or _validate_artifact_inventory(index_report.get("artifacts")) != artifacts
        ):
            raise ReleaseProofError("index_evidence_invalid")
        if index == "pypi" and (
            index_report.get("checks", {}).get("trusted_publisher_attestations") != len(artifacts)
            or index_report.get("checks", {}).get("attestation_source_commit") != candidate["source_commit"]
            or index_report.get("checks", {}).get("attestation_workflow_run_id") != candidate["workflow_run_id"]
            or index_report.get("checks", {}).get("attestation_workflow_run_attempt") != candidate["workflow_run_attempt"]
            or index_report.get("checks", {}).get("publisher_environment_assertion") != PRODUCTION_ENVIRONMENT
            or index_report.get("checks", {}).get("candidate_workflow_environment_binding") is not True
        ):
            raise ReleaseProofError("index_evidence_invalid")
    offline_body = dict(offline_report)
    offline_digest = offline_body.pop("report_sha256")
    if hashlib.sha256(canonical_json_bytes(offline_body)).hexdigest() != offline_digest:
        raise ReleaseProofError("offline_report_invalid")
    frozen = offline_report.get("frozen_candidate_artifacts")
    frozen_inventory = []
    if isinstance(frozen, list):
        for item in frozen:
            if isinstance(item, dict) and {"filename", "sha256", "size_bytes"}.issubset(item):
                frozen_inventory.append({
                    "filename": item["filename"], "sha256": item["sha256"],
                    "size_bytes": item["size_bytes"],
                })
    if (
        not isinstance(offline_report, dict)
        or offline_report.get("source_commit") != current_commit
        or offline_report.get("source_tree_sha256") != current_tree
        or offline_report.get("mode") != "offline"
        or offline_report.get("checks", {}).get("repeat_build", {}).get("wheel_identical") is not True
        or offline_report.get("checks", {}).get("repeat_build", {}).get("sdist_identical") is not True
        or offline_report.get("checks", {}).get("fresh_install", {}).get("install_exit") != 0
        or offline_report.get("checks", {}).get("fresh_install", {}).get("smoke_exit") != 0
        or offline_report.get("checks", {}).get("offline", {}).get("negative_egress", {}).get("runner_network_isolation") != "VERIFIED"
        or sorted(frozen_inventory, key=lambda row: row["filename"]) != artifacts
    ):
        raise ReleaseProofError("offline_report_invalid")
    expected_release_url = f"https://github.com/{REPOSITORY}/releases/tag/v{VERSION}"
    if manifest["release_url"] != expected_release_url:
        raise ReleaseProofError("release_url_invalid")
    return {"candidate": candidate, "artifacts": artifacts}


class _BoundedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, permitted_hosts: set[str]) -> None:
        super().__init__()
        self.permitted_hosts = permitted_hosts

    def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
        parsed = urllib.parse.urlsplit(newurl)
        if parsed.scheme != "https" or (parsed.hostname or "").lower() not in self.permitted_hosts:
            raise urllib.error.URLError("redirect_host_not_allowed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def http_get(url: str, *, max_bytes: int = MAX_ARTIFACT_BYTES) -> tuple[int, str, bytes]:
    parsed = urllib.parse.urlsplit(url)
    allowed = set(ALLOWED_ROOT_HOSTS)
    allowed.update({"files.pythonhosted.org", "test-files.pythonhosted.org"})
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed or parsed.username or parsed.password:
        raise ReleaseProofError("remote_url_invalid")
    headers = {"Accept": "application/json", "User-Agent": "mudra-release-verifier/1"}
    if (parsed.hostname or "").lower() == "api.github.com":
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2022-11-28"
        headers["Accept"] = "application/vnd.github+json"
    request = urllib.request.Request(url, headers=headers, method="GET")
    opener = urllib.request.build_opener(_BoundedRedirect(allowed))
    try:
        with opener.open(request, timeout=20) as response:
            final_url = response.geturl()
            final_host = (urllib.parse.urlsplit(final_url).hostname or "").lower()
            if final_host not in allowed or urllib.parse.urlsplit(final_url).scheme != "https":
                raise ReleaseProofError("remote_url_invalid")
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise ReleaseProofError("remote_response_too_large")
            return response.status, final_url, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.geturl(), b""
    except ReleaseProofError:
        raise
    except (OSError, urllib.error.URLError, TimeoutError):
        raise ReleaseProofError("remote_request_failed") from None


def _json_get(url: str, fetch: Callable[..., tuple[int, str, bytes]] = http_get) -> tuple[int, str, Any]:
    status, final_url, body = fetch(url, max_bytes=4 * 1024 * 1024)
    if status != 200:
        return status, final_url, None
    original = urllib.parse.urlsplit(url)
    final = urllib.parse.urlsplit(final_url)
    if (
        final.scheme != "https"
        or (final.hostname or "").casefold() != (original.hostname or "").casefold()
    ):
        raise ReleaseProofError("remote_redirect_host_invalid")
    try:
        return status, final_url, strict_json(body)
    except ReleaseProofError:
        raise ReleaseProofError("remote_json_invalid") from None


def _index_hosts(index: str) -> tuple[str, set[str]]:
    if index == "testpypi":
        return "https://test.pypi.org", {"test.pypi.org", "test-files.pythonhosted.org"}
    if index == "pypi":
        return "https://pypi.org", {"pypi.org", "files.pythonhosted.org"}
    raise ReleaseProofError("index_invalid")


def _validate_index_document(
    document: Any,
    *,
    artifacts: list[dict[str, Any]],
) -> dict[str, str]:
    if not isinstance(document, dict) or not isinstance(document.get("info"), dict):
        raise ReleaseProofError("index_response_invalid")
    info = document["info"]
    name = info.get("name")
    if not isinstance(name, str) or name.casefold().replace("_", "-") != PACKAGE or info.get("version") != VERSION:
        raise ReleaseProofError("index_identity_mismatch")
    urls = document.get("urls")
    if not isinstance(urls, list) or len(urls) != len(artifacts):
        raise ReleaseProofError("index_artifacts_mismatch")
    expected = {item["filename"]: item for item in artifacts}
    observed: dict[str, str] = {}
    for item in urls:
        if not isinstance(item, dict):
            raise ReleaseProofError("index_artifacts_mismatch")
        filename = item.get("filename")
        record = expected.get(filename)
        digest = item.get("digests", {}).get("sha256") if isinstance(item.get("digests"), dict) else None
        size = item.get("size")
        artifact_url = item.get("url")
        if not isinstance(artifact_url, str):
            raise ReleaseProofError("index_artifacts_mismatch")
        parsed = urllib.parse.urlsplit(artifact_url)
        if (
            record is None or filename in observed
            or digest != record["sha256"] or size != record["size_bytes"]
            or not (item.get("yanked") is None or item.get("yanked") is False or item.get("yanked") == "")
            or parsed.scheme != "https" or not parsed.hostname
        ):
            raise ReleaseProofError("index_artifacts_mismatch")
        observed[filename] = artifact_url
    if set(observed) != set(expected):
        raise ReleaseProofError("index_artifacts_mismatch")
    return observed


def _download_exact(
    url: str,
    *,
    expected: dict[str, Any],
    allowed_hosts: set[str],
    fetch: Callable[..., tuple[int, str, bytes]],
    destination: Path,
) -> Path:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host not in allowed_hosts or urllib.parse.urlsplit(url).scheme != "https":
        raise ReleaseProofError("artifact_host_invalid")
    status, final_url, body = fetch(url, max_bytes=MAX_ARTIFACT_BYTES)
    final_host = (urllib.parse.urlsplit(final_url).hostname or "").lower()
    if (
        status != 200 or final_host != host or final_host not in allowed_hosts
        or urllib.parse.urlsplit(final_url).scheme != "https"
    ):
        raise ReleaseProofError("artifact_download_failed")
    if len(body) != expected["size_bytes"] or hashlib.sha256(body).hexdigest() != expected["sha256"]:
        raise ReleaseProofError("artifact_hash_mismatch")
    target = destination / expected["filename"]
    target.write_bytes(body)
    return target


def _fresh_install_smoke(wheel: Path, *, package_version: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="mudra-published-install-") as temp_name:
        temp = Path(temp_name)
        environment = temp / "venv"
        try:
            venv.EnvBuilder(with_pip=True, clear=True).create(environment)
        except (OSError, subprocess.SubprocessError):
            raise ReleaseProofError("fresh_venv_failed") from None
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = dict(os.environ)
        env.update({"PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1", "PYTHONPATH": ""})
        command = [str(python), "-m", "pip", "install", "--no-index", "--no-deps", "--no-cache-dir", str(wheel)]
        try:
            install = subprocess.run(command, cwd=temp, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     check=False, timeout=180)
            smoke = subprocess.run(
                [str(python), "-c", (
                    "import importlib.metadata as m, mudra_interact_core as p, pathlib, sys; "
                    f"assert m.version('{PACKAGE}') == '{package_version}'; "
                    "location=pathlib.Path(p.__file__).resolve(); "
                    "assert pathlib.Path(sys.prefix).resolve() in location.parents"
                )],
                cwd=temp, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, check=False, timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            raise ReleaseProofError("fresh_install_failed") from None
        if install.returncode != 0 or smoke.returncode != 0:
            raise ReleaseProofError("fresh_install_failed")
    return True


def _verify_pypi_attestation(
    filename: str,
    *,
    artifact_path: Path,
    source_commit: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    fetch: Callable[..., tuple[int, str, bytes]] = http_get,
) -> bool:
    if (
        not COMMIT_RE.fullmatch(source_commit)
        or type(workflow_run_id) is not int or workflow_run_id < 1
        or type(workflow_run_attempt) is not int or workflow_run_attempt < 1
        or artifact_path.name != filename or not artifact_path.is_file()
    ):
        raise ReleaseProofError("attestation_candidate_invalid")
    provenance_url = f"https://pypi.org/integrity/{PACKAGE}/{VERSION}/{filename}/provenance"
    status, _final_url, provenance = _json_get(provenance_url, fetch)
    if status != 200 or not isinstance(provenance, dict):
        raise ReleaseProofError("publisher_attestation_missing")
    try:
        from pypi_attestations import AttestationType, Distribution, Provenance

        parsed = Provenance.model_validate(provenance)
        if len(parsed.attestation_bundles) != 1:
            raise ReleaseProofError("publisher_attestation_invalid")
        bundle = parsed.attestation_bundles[0]
        publisher = bundle.publisher
        if (
            getattr(publisher, "kind", None) != "GitHub"
            or getattr(publisher, "repository", "").casefold() != REPOSITORY.casefold()
            or getattr(publisher, "workflow", None) != Path(WORKFLOW).name
            or getattr(publisher, "environment", None) != PRODUCTION_ENVIRONMENT
        ):
            raise ReleaseProofError("publisher_identity_mismatch")
        if len(bundle.attestations) != 1:
            raise ReleaseProofError("publisher_attestation_invalid")
        expected_identity = _pypi_attestation_policy(
            source_commit=source_commit,
            workflow_run_id=workflow_run_id,
            workflow_run_attempt=workflow_run_attempt,
        )
        distribution = Distribution.from_file(artifact_path)
        attestation = bundle.attestations[0]
        predicate_type, _predicate = attestation.verify(
            identity=expected_identity,
            dist=distribution,
        )
        if predicate_type != AttestationType.PYPI_PUBLISH_V1.value:
            raise ReleaseProofError("publisher_attestation_invalid")
    except ReleaseProofError:
        raise
    except Exception:
        # Parsing, missing claims, signature failures and verifier/API failures
        # all fail closed without copying remote values into public reports.
        raise ReleaseProofError("publisher_attestation_invalid") from None
    return True


def verify_index(
    index: str,
    artifacts: list[dict[str, Any]],
    *,
    source_commit: str | None = None,
    workflow_run_id: int | None = None,
    workflow_run_attempt: int | None = None,
    workflow_root: Path | None = None,
    fetch: Callable[..., tuple[int, str, bytes]] = http_get,
    install: Callable[..., bool] = _fresh_install_smoke,
) -> dict[str, Any]:
    base, allowed_hosts = _index_hosts(index)
    url = f"{base}/pypi/{PACKAGE}/{VERSION}/json"
    status, _final, document = _json_get(url, fetch)
    if status != 200:
        raise ReleaseProofError("index_version_missing" if status == 404 else "index_unavailable")
    files = _validate_index_document(document, artifacts=artifacts)
    installed = False
    with tempfile.TemporaryDirectory(prefix=f"mudra-{index}-") as temp_name:
        temp = Path(temp_name)
        downloaded: dict[str, Path] = {}
        for artifact in artifacts:
            downloaded[artifact["filename"]] = _download_exact(
                files[artifact["filename"]], expected=artifact,
                allowed_hosts=allowed_hosts, fetch=fetch, destination=temp,
            )
        wheel_name = next(name for name in downloaded if name.endswith(".whl"))
        installed = install(downloaded[wheel_name], package_version=VERSION)
        if installed is not True:
            raise ReleaseProofError("fresh_install_failed")
        attestations = 0
        if index == "pypi":
            if (
                not isinstance(source_commit, str)
                or type(workflow_run_id) is not int or workflow_run_id < 1
                or type(workflow_run_attempt) is not int or workflow_run_attempt < 1
            ):
                raise ReleaseProofError("attestation_candidate_invalid")
            _verify_candidate_publish_workflow(
                workflow_root if workflow_root is not None else Path(__file__).resolve().parents[1],
                source_commit,
            )
            for artifact in artifacts:
                _verify_pypi_attestation(
                    artifact["filename"],
                    artifact_path=downloaded[artifact["filename"]],
                    source_commit=source_commit,
                    workflow_run_id=workflow_run_id,
                    workflow_run_attempt=workflow_run_attempt,
                    fetch=fetch,
                )
                attestations += 1
    if installed is not True:
        raise ReleaseProofError("fresh_install_failed")
    return {
        "state": "VERIFIED",
        "index": index,
        "package": PACKAGE,
        "version": VERSION,
        "artifact_count": len(artifacts),
        "downloaded_and_hashed": True,
        "fresh_installed_wheel_smoke": True,
        "trusted_publisher_attestations": attestations,
        **({
            "attestation_source_commit": source_commit,
            "attestation_workflow_run_id": workflow_run_id,
            "attestation_workflow_run_attempt": workflow_run_attempt,
            "publisher_environment_assertion": PRODUCTION_ENVIRONMENT,
            "candidate_workflow_environment_binding": True,
        } if index == "pypi" else {}),
    }


def _verify_github_publication(candidate: dict[str, Any], fetch: Callable[..., tuple[int, str, bytes]]) -> dict[str, Any]:
    repo = candidate["repository"]
    run_id = candidate["workflow_run_id"]
    run_status, _url, run = _json_get(f"https://api.github.com/repos/{repo}/actions/runs/{run_id}", fetch)
    if run_status != 200 or not isinstance(run, dict):
        raise ReleaseProofError("workflow_run_unavailable")
    if (
        run.get("head_sha") != candidate["source_commit"]
        or run.get("run_attempt") != candidate["workflow_run_attempt"]
        or run.get("status") != "completed" or run.get("conclusion") != "success"
        or not isinstance(run.get("path"), str) or WORKFLOW not in run["path"]
        or run.get("event") != "workflow_dispatch"
    ):
        raise ReleaseProofError("workflow_run_mismatch")
    release_status, _url, release = _json_get(
        f"https://api.github.com/repos/{repo}/releases/tags/{candidate['tag']}", fetch,
    )
    if release_status != 200 or not isinstance(release, dict):
        raise ReleaseProofError("github_release_unavailable")
    if (
        release.get("draft") is not False or release.get("prerelease") is not False
        or release.get("tag_name") != candidate["tag"]
        or release.get("html_url") != f"https://github.com/{repo}/releases/tag/{candidate['tag']}"
    ):
        raise ReleaseProofError("github_release_mismatch")
    ref_status, _url, reference = _json_get(
        f"https://api.github.com/repos/{repo}/git/ref/tags/{candidate['tag']}", fetch,
    )
    if ref_status != 200 or not isinstance(reference, dict) or reference.get("ref") != f"refs/tags/{candidate['tag']}":
        raise ReleaseProofError("github_tag_unavailable")
    tag_object = reference.get("object")
    depth = 0
    while isinstance(tag_object, dict) and tag_object.get("type") == "tag" and depth < 3:
        tag_sha = tag_object.get("sha")
        if not isinstance(tag_sha, str) or not COMMIT_RE.fullmatch(tag_sha):
            raise ReleaseProofError("github_tag_mismatch")
        tag_status, _url, tag_body = _json_get(f"https://api.github.com/repos/{repo}/git/tags/{tag_sha}", fetch)
        if tag_status != 200 or not isinstance(tag_body, dict):
            raise ReleaseProofError("github_tag_mismatch")
        tag_object = tag_body.get("object")
        depth += 1
    if not isinstance(tag_object, dict) or tag_object.get("type") != "commit" or tag_object.get("sha") != candidate["source_commit"]:
        raise ReleaseProofError("github_tag_mismatch")
    expected = {item["filename"]: item for item in _validate_artifact_inventory(candidate["artifacts"])}
    assets = release.get("assets")
    if not isinstance(assets, list) or len(assets) != len(expected):
        raise ReleaseProofError("github_release_assets_mismatch")
    for asset in assets:
        if not isinstance(asset, dict) or asset.get("name") not in expected:
            raise ReleaseProofError("github_release_assets_mismatch")
        record = expected[asset["name"]]
        digest = asset.get("digest")
        if digest != f"sha256:{record['sha256']}" or asset.get("size") != record["size_bytes"]:
            raise ReleaseProofError("github_release_assets_mismatch")
    return {"workflow_run": "VERIFIED", "github_release": "VERIFIED", "tag_commit": candidate["source_commit"], "workflow_path": WORKFLOW}


def _verify_environment_configuration(repo: str, fetch: Callable[..., tuple[int, str, bytes]]) -> dict[str, Any]:
    status, _url, body = _json_get(
        f"https://api.github.com/repos/{repo}/environments/{PRODUCTION_ENVIRONMENT}", fetch,
    )
    if status != 200 or not isinstance(body, dict) or body.get("name") != PRODUCTION_ENVIRONMENT:
        raise ReleaseProofError("protected_environment_unavailable")
    rules = body.get("protection_rules")
    matching = [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers"] if isinstance(rules, list) else []
    reviewers = matching[0].get("reviewers") if matching else None
    prevent_self_review = matching[0].get("prevent_self_review") if matching else None
    branch_status, _branch_url, branch_body = _json_get(
        f"https://api.github.com/repos/{repo}/environments/{PRODUCTION_ENVIRONMENT}/deployment-branch-policies?per_page=100",
        fetch,
    )
    branch_policies = branch_body.get("branch_policies") if isinstance(branch_body, dict) else None
    main_only = (
        isinstance(branch_policies, list)
        and len(branch_policies) == 1
        and isinstance(branch_policies[0], dict)
        and branch_policies[0].get("name") == "main"
        and branch_policies[0].get("type") == "branch"
    )
    if (
        not isinstance(reviewers, list) or not reviewers
        or prevent_self_review is not False
        or body.get("can_admins_bypass") is not False
        or branch_status != 200 or not isinstance(branch_body, dict)
        or type(branch_body.get("total_count")) is not int or branch_body.get("total_count") != 1
        or not main_only
        or body.get("deployment_branch_policy") != {
            "protected_branches": False,
            "custom_branch_policies": True,
        }
    ):
        raise ReleaseProofError("protected_environment_unconfigured")
    return {
        "environment": PRODUCTION_ENVIRONMENT,
        "required_reviewers": len(reviewers),
        "self_approval_allowed": True,
        "independent_review": False,
        "administrator_bypass": False,
        "deployment_branches": ["main"],
    }


def verify_published(
    root: Path,
    manifest_path: str,
    *,
    current_commit: str,
    current_tree: str | None = None,
    spec_sha256: str,
    acceptance_sha256: str,
    tool_lock_sha256: str,
    fetch: Callable[..., tuple[int, str, bytes]] = http_get,
    index_verifier: Callable[..., dict[str, Any]] = verify_index,
    github_verifier: Callable[..., dict[str, Any]] = _verify_github_publication,
    environment_verifier: Callable[..., dict[str, Any]] = _verify_environment_configuration,
) -> dict[str, Any]:
    if current_tree is None:
        current_tree = source_tree_sha256(root)
    path = _safe_repo_file(root, manifest_path, prefix="evidence/releases")
    try:
        manifest = strict_json(path.read_bytes())
    except OSError:
        raise ReleaseProofError("published_manifest_unavailable") from None
    validated = validate_manifest(
        root, manifest, current_commit=current_commit, current_tree=current_tree,
        spec_sha256=spec_sha256, acceptance_sha256=acceptance_sha256,
        tool_lock_sha256=tool_lock_sha256,
    )
    candidate = validated["candidate"]
    environment = environment_verifier(candidate["repository"], fetch)
    github = github_verifier(candidate, fetch)
    testpypi = index_verifier("testpypi", validated["artifacts"], fetch=fetch)
    pypi = index_verifier(
        "pypi", validated["artifacts"],
        source_commit=candidate["source_commit"],
        workflow_run_id=candidate["workflow_run_id"],
        workflow_run_attempt=candidate["workflow_run_attempt"],
        workflow_root=root,
        fetch=fetch,
    )
    return {
        "state": "VERIFIED",
        "verification_kind": "luna_self_verified",
        "source_commit": candidate["source_commit"],
        "source_tree_sha256": current_tree,
        "candidate_fingerprint": candidate["candidate_fingerprint"],
        "package": PACKAGE,
        "version": VERSION,
        "authorization": environment,
        "github": github,
        "indexes": {"testpypi": testpypi, "pypi": pypi},
        "artifacts": validated["artifacts"],
        "adapter_status": "not_implemented_in_public_core",
        "recognition_quality": "not_established_by_synthetic_tests",
        "cultural_review": "not_established_by_public_core",
        "errors": [],
    }


def ambiguous_upload_decision(
    expected: list[dict[str, Any]],
    observed: list[dict[str, Any]] | None,
    *,
    exact_version_exists: bool | None,
    absence_confirmed: bool = False,
) -> str:
    """Return a safe next action after an upload response is ambiguous."""
    _validate_artifact_inventory(expected)
    if exact_version_exists is False:
        return "retry_same_frozen_files" if absence_confirmed else "inspect_again"
    if exact_version_exists is None or observed is None:
        return "inspect_again"
    try:
        actual = _validate_artifact_inventory(observed)
    except ReleaseProofError:
        return "stop_version_collision"
    return "resume_matching_version" if actual == _validate_artifact_inventory(expected) else "stop_hash_mismatch"


def rollback_decision(*, version: str, authorization_recorded: bool, delete_history: bool = False) -> str:
    if version != VERSION or delete_history:
        return "stop_invalid_rollback"
    if not authorization_recorded:
        return "block_unapproved_yank_or_patch"
    return "authorized_yank_or_patch_only"


def _write_local_json(root: Path, relative: str, value: Any) -> Path:
    path = _safe_repo_output(root, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2).encode("utf-8")
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    os.replace(temporary, path)
    return path


def _safe_repo_output(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or "\\" in relative:
        raise ReleaseProofError("manifest_path_invalid")
    posix = PurePosixPath(relative)
    if posix.is_absolute() or ".." in posix.parts or posix.as_posix() != relative:
        raise ReleaseProofError("manifest_path_invalid")
    path = root.joinpath(*posix.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        raise ReleaseProofError("manifest_path_invalid") from None
    if any((root / part).is_symlink() for part in (Path(*posix.parts[:i]) for i in range(1, len(posix.parts) + 1))):
        raise ReleaseProofError("manifest_path_invalid")
    return path


def _report_reference(root: Path, path: str) -> dict[str, str]:
    target = _safe_repo_file(root, path, prefix="evidence/releases")
    return {"path": path, "sha256": sha256_file(target)}


def create_candidate_document(
    root: Path,
    *,
    offline_report_path: str,
    artifact_dir: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
    current_commit: str,
) -> dict[str, Any]:
    from tools.verify_release import frozen_candidate_inventory, git_value

    if (
        current_commit != git_value("rev-parse", "HEAD")
        or type(workflow_run_id) is not int or workflow_run_id < 1
        or type(workflow_run_attempt) is not int or workflow_run_attempt < 1
    ):
        raise ReleaseProofError("candidate_identity_mismatch")
    tree = source_tree_sha256(root)
    offline_path = _safe_repo_file(root, offline_report_path, prefix="evidence/releases")
    try:
        offline = read_json(offline_path, max_bytes=4 * 1024 * 1024)
    except Exception:
        raise ReleaseProofError("offline_report_invalid") from None
    inventory = frozen_candidate_inventory(artifact_dir, offline_report_path)
    if (
        offline.get("source_commit") != current_commit
        or offline.get("source_tree_sha256") != tree
    ):
        raise ReleaseProofError("offline_report_invalid")
    artifact_rows = [
        {"filename": item["filename"], "sha256": item["sha256"], "size_bytes": item["size_bytes"]}
        for item in inventory
    ]
    gates = read_json(root / "IMPLEMENTATION_BACKLOG.json", max_bytes=4 * 1024 * 1024).get("gates")
    if not isinstance(gates, list):
        raise ReleaseProofError("gate_evidence_invalid")
    gate_evidence: list[dict[str, str]] = []
    for gate_id in ("M0", "M1", "M2", "M3"):
        rows = [gate for gate in gates if isinstance(gate, dict) and gate.get("id") == gate_id]
        if len(rows) != 1 or rows[0].get("state") != "VERIFIED":
            raise ReleaseProofError("gate_evidence_invalid")
        evidence = rows[0].get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ReleaseProofError("gate_evidence_invalid")
        selected = evidence[0]
        if not isinstance(selected, dict) or set(selected) != {"path", "sha256"}:
            raise ReleaseProofError("gate_evidence_invalid")
        gate_evidence.append({"gate": gate_id, "path": selected["path"], "sha256": selected["sha256"]})
    candidate: dict[str, Any] = {
        "package": PACKAGE,
        "version": VERSION,
        "repository": REPOSITORY,
        "workflow_path": WORKFLOW,
        "source_commit": current_commit,
        "source_tree_sha256": tree,
        "spec_sha256": sha256_text_file(root / "MUDRA_INTERACT_CORE_SPEC.md"),
        "acceptance_sha256": sha256_text_file(root / "docs" / "ACCEPTANCE.md"),
        "tool_lock_sha256": sha256_text_file(root / "requirements-dev.lock"),
        "tag": f"v{VERSION}",
        "workflow_run_id": workflow_run_id,
        "workflow_run_attempt": workflow_run_attempt,
        "artifacts": artifact_rows,
    }
    candidate["candidate_fingerprint"] = fingerprint(candidate)
    return {
        "schema_version": 1,
        "candidate": candidate,
        "gate_evidence": gate_evidence,
        "offline_report": _report_reference(root, offline_report_path),
    }


def create_published_document(
    root: Path,
    *,
    candidate_path: str,
    testpypi_report_path: str,
    pypi_report_path: str,
    output_path: str,
    current_commit: str,
    workflow_run_id: int,
    workflow_run_attempt: int,
) -> dict[str, Any]:
    candidate_file = _safe_repo_file(root, candidate_path, prefix="evidence/releases")
    try:
        candidate_doc = strict_json(candidate_file.read_bytes())
    except OSError:
        raise ReleaseProofError("candidate_manifest_unavailable") from None
    if not isinstance(candidate_doc, dict) or set(candidate_doc) != {"schema_version", "candidate", "gate_evidence", "offline_report"}:
        raise ReleaseProofError("candidate_shape_invalid")
    candidate = candidate_doc["candidate"]
    if (
        candidate_doc["schema_version"] != 1 or not isinstance(candidate, dict)
        or candidate.get("source_commit") != current_commit
        or candidate.get("workflow_run_id") != workflow_run_id
        or candidate.get("workflow_run_attempt") != workflow_run_attempt
        or candidate.get("candidate_fingerprint") != fingerprint({k: v for k, v in candidate.items() if k != "candidate_fingerprint"})
    ):
        raise ReleaseProofError("candidate_identity_mismatch")
    artifacts = _validate_artifact_inventory(candidate.get("artifacts"))
    refs: dict[str, dict[str, str]] = {}
    for index, path in (("testpypi", testpypi_report_path), ("pypi", pypi_report_path)):
        file_path = _safe_repo_file(root, path, prefix="evidence/releases")
        try:
            report = read_json(file_path, max_bytes=4 * 1024 * 1024)
        except Exception:
            raise ReleaseProofError("index_evidence_invalid") from None
        if (
            not isinstance(report, dict) or report.get("state") != "VERIFIED"
            or report.get("mode") != f"verify_{index}"
            or report.get("source_commit") != current_commit
            or report.get("source_tree_sha256") != candidate.get("source_tree_sha256")
            or report.get("checks", {}).get("index") != index
            or _validate_artifact_inventory(report.get("artifacts")) != artifacts
        ):
            raise ReleaseProofError("index_evidence_invalid")
        if index == "pypi" and (
            report.get("checks", {}).get("trusted_publisher_attestations") != len(artifacts)
            or report.get("checks", {}).get("attestation_source_commit") != candidate["source_commit"]
            or report.get("checks", {}).get("attestation_workflow_run_id") != candidate["workflow_run_id"]
            or report.get("checks", {}).get("attestation_workflow_run_attempt") != candidate["workflow_run_attempt"]
            or report.get("checks", {}).get("publisher_environment_assertion") != PRODUCTION_ENVIRONMENT
            or report.get("checks", {}).get("candidate_workflow_environment_binding") is not True
        ):
            raise ReleaseProofError("index_evidence_invalid")
        refs[index] = _report_reference(root, path)
    published = {
        "schema_version": 1,
        "state": "PUBLISHED",
        "verification_kind": "luna_self_verified",
        "candidate": candidate,
        "authorization": {
            "kind": "github_protected_environment",
            "environment": PRODUCTION_ENVIRONMENT,
            "workflow_run_id": workflow_run_id,
            "workflow_run_attempt": workflow_run_attempt,
            "candidate_fingerprint": candidate["candidate_fingerprint"],
        },
        "gate_evidence": candidate_doc["gate_evidence"],
        "offline_report": candidate_doc["offline_report"],
        "index_evidence": refs,
        "release_url": f"https://github.com/{REPOSITORY}/releases/tag/v{VERSION}",
    }
    _write_local_json(root, output_path, published)
    return published
