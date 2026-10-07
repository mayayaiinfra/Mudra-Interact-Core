"""Create sanitized release evidence from already verified workflow outputs."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release_proof import ReleaseProofError, create_candidate_document, create_published_document, _write_local_json  # noqa: E402


def _head() -> str:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", check=False, timeout=10,
    )
    if result.returncode != 0:
        raise ReleaseProofError("candidate_identity_mismatch")
    return result.stdout.strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--candidate", action="store_true")
    mode.add_argument("--published", action="store_true")
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--offline-report", default="evidence/releases/offline-qualification.json")
    parser.add_argument("--artifact-dir", default="release-artifacts/0.2.0")
    parser.add_argument("--candidate-path", default="evidence/releases/candidate.json")
    parser.add_argument("--testpypi-report", default="evidence/releases/testpypi-verification.json")
    parser.add_argument("--pypi-report", default="evidence/releases/pypi-verification.json")
    parser.add_argument("--output", default="evidence/releases/published.json")
    args = parser.parse_args(argv)
    try:
        head = _head()
        if args.candidate:
            document = create_candidate_document(
                ROOT, offline_report_path=args.offline_report,
                artifact_dir=args.artifact_dir,
                workflow_run_id=args.workflow_run_id,
                current_commit=head,
            )
            _write_local_json(ROOT, args.candidate_path, document)
            print(document["candidate"]["candidate_fingerprint"])
        else:
            document = create_published_document(
                ROOT, candidate_path=args.candidate_path,
                testpypi_report_path=args.testpypi_report,
                pypi_report_path=args.pypi_report,
                output_path=args.output,
                current_commit=head,
                workflow_run_id=args.workflow_run_id,
            )
            print(document["candidate"]["candidate_fingerprint"])
        return 0
    except ReleaseProofError as error:
        print(error.code, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
