"""Run release-lock Sigstore claim tests without adding a runtime dependency.

Execute with the Python 3.12 environment installed from
``requirements-release.lock``. This is a pre-upload check; the signed live
PyPI attestations are still verified after upload.
"""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
import subprocess
import tempfile
import sys

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release_proof import (
    ReleaseProofError,
    _pypi_attestation_policy,
    _verify_candidate_publish_workflow,
)
from sigstore.verify import policy as sigstore_policy


SOURCE_COMMIT = "a" * 40
RUN_ID = 12345
RUN_ATTEMPT = 2
CLAIMS = {
    "OIDCIssuerV2": "https://token.actions.githubusercontent.com",
    "OIDCSourceRepositoryURI": "https://github.com/mayayaiinfra/Mudra-Interact-Core",
    "OIDCSourceRepositoryDigest": SOURCE_COMMIT,
    "OIDCBuildConfigURI": (
        "https://github.com/mayayaiinfra/Mudra-Interact-Core/"
        ".github/workflows/publish.yml@refs/heads/main"
    ),
    "OIDCBuildTrigger": "workflow_dispatch",
    "OIDCRunInvocationURI": (
        "https://github.com/mayayaiinfra/Mudra-Interact-Core/actions/runs/"
        f"{RUN_ID}/attempts/{RUN_ATTEMPT}"
    ),
}


def _der_utf8(value: str) -> bytes:
    raw = value.encode("utf-8")
    if len(raw) >= 128:
        raise ValueError("test claim exceeds short-form DER length")
    return bytes((0x0C, len(raw))) + raw


def _certificate(claims: dict[str, bytes]) -> x509.Certificate:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "synthetic-oidc")])
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(minutes=1))
    )
    for policy_name, encoded in claims.items():
        policy_type = getattr(sigstore_policy, policy_name)
        builder = builder.add_extension(
            x509.UnrecognizedExtension(policy_type.oid, encoded), critical=False,
        )
    return builder.sign(key, hashes.SHA256())


class ReleaseAttestationPolicyTests(unittest.TestCase):
    def test_locked_sigstore_policies_check_x509_extensions(self) -> None:
        policies = _pypi_attestation_policy(
            source_commit=SOURCE_COMMIT,
            workflow_run_id=RUN_ID,
            workflow_run_attempt=RUN_ATTEMPT,
        )
        valid = {name: _der_utf8(value) for name, value in CLAIMS.items()}
        policies.verify(_certificate(valid))
        for name in CLAIMS:
            with self.subTest(name=name, mismatch="wrong"):
                wrong = dict(valid)
                wrong[name] = _der_utf8("wrong-claim")
                with self.assertRaises(Exception):
                    policies.verify(_certificate(wrong))
            with self.subTest(name=name, mismatch="missing"):
                missing = dict(valid)
                del missing[name]
                with self.assertRaises(Exception):
                    policies.verify(_certificate(missing))
            with self.subTest(name=name, mismatch="malformed"):
                malformed = dict(valid)
                malformed[name] = b"\x04\x01x"
                with self.assertRaises(Exception):
                    policies.verify(_certificate(malformed))

    def test_candidate_workflow_binds_environment_and_frozen_files(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source_commit = subprocess.check_output(
            ["git", "-C", str(root), "rev-parse", "HEAD"], text=True,
        ).strip()
        proof = _verify_candidate_publish_workflow(root, source_commit)
        self.assertEqual(proof["environment"], "pypi-production")
        self.assertEqual(proof["candidate_commit"], source_commit)
        workflow = root / ".github/workflows/publish.yml"
        source = workflow.read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory(prefix="mudra-workflow-proof-") as temp_name:
            fixture = Path(temp_name)
            subprocess.run(["git", "init", str(fixture)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(fixture), "config", "user.email", "release-test@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(fixture), "config", "user.name", "Release test"], check=True)
            workflow_path = fixture / ".github/workflows/publish.yml"
            workflow_path.parent.mkdir(parents=True)

            def commit_workflow(text: str) -> str:
                workflow_path.write_text(text, encoding="utf-8")
                subprocess.run(["git", "-C", str(fixture), "add", "."], check=True)
                subprocess.run(["git", "-C", str(fixture), "commit", "-m", "workflow"], check=True, capture_output=True)
                return subprocess.check_output(["git", "-C", str(fixture), "rev-parse", "HEAD"], text=True).strip()

            candidate = commit_workflow(source)
            self.assertEqual(
                _verify_candidate_publish_workflow(fixture, candidate)["candidate_commit"],
                candidate,
            )
            bad_environment = commit_workflow(source.replace(
                "name: pypi-production", "name: pypi-production-evil", 1,
            ))
            with self.assertRaises(ReleaseProofError):
                _verify_candidate_publish_workflow(fixture, bad_environment)
            duplicate_key = commit_workflow(source.replace(
                "      name: pypi-production", "      name: pypi-production\n      name: pypi-test", 1,
            ))
            with self.assertRaises(ReleaseProofError):
                _verify_candidate_publish_workflow(fixture, duplicate_key)

    def test_policy_rejects_invalid_candidate_run_attempt(self) -> None:
        with self.assertRaises(ReleaseProofError) as raised:
            _pypi_attestation_policy(
                source_commit=SOURCE_COMMIT,
                workflow_run_id=RUN_ID,
                workflow_run_attempt=True,
            )
        self.assertEqual(raised.exception.code, "attestation_candidate_invalid")


if __name__ == "__main__":
    unittest.main(verbosity=2)
