# Release runbook

This runbook publishes only the declared package `mudra-interact==0.4.0`
from one frozen commit. The public core is a Python library, so its production
release is a package distribution, not a server deployment. The workflow never
stores a PyPI API token and does not rebuild after candidate qualification.
The currently published release is 0.3.0; this runbook qualifies its successor.

## Owner setup required once

Before starting a release, an owner with repository and index administration
access must complete and verify all of the following:

1. Confirm that `mayayaiinfra/Mudra-Interact-Core` is the intended public
   repository and verify publishing authority separately on PyPI and TestPyPI.
   For an existing `mudra-interact` project, verify owner control and the exact
   Trusted Publisher. For its first release, use the authenticated owner's
   account to configure an owner-authorized **pending** GitHub publisher:
   project `mudra-interact`, owner `mayayaiinfra`, repository
   `Mudra-Interact-Core`, workflow filename `publish.yml`, and the index's
   environment from step 2. The account UI uses the filename, not the full
   `.github/workflows/` path. Record a sanitized setup receipt without secrets.
   A pending publisher does not reserve the name or prove project ownership;
   first successful use creates the project. A `404` alone is insufficient.
2. Configure PyPI Trusted Publishers for this repository and
   `.github/workflows/publish.yml`, with the `pypi-production` environment.
   Configure the corresponding TestPyPI publisher with the `pypi-test`
   environment. Use each service's separate account and trusted-publisher
   configuration. Do not add a long-lived upload token.
3. Create the GitHub environments `pypi-test` and `pypi-production`, and
   restrict both to `main`. `pypi-production` must have a required reviewer,
   administrator bypass disabled, and a deliberate manual approval for each
   release run. This repository currently has one maintainer, so the owner is
   the configured reviewer and may approve their own run. This is single-owner
   authorization, not an independent review; never claim separation of duties.
   The owner must check the exact version, full source commit, and candidate
   artifact fingerprint for that run before approving. Keep the TestPyPI and
   production stages and their environment identities separate. If another
   maintainer is added later, enable self-review prevention and require their
   production approval where practical.
4. Confirm that the production publisher is scoped to the exact workflow and
   environment; the published PyPI attestations must verify against this
   repository. The exact workflow and source commit are recorded in the
   release candidate and checked after publication.
5. Enable GitHub private vulnerability reporting or provide a private
   reporting channel.

Missing access, package-name collision, absent trusted publishers, or missing
environment protection blocks the release. Do not guess ownership from an
unavailable index page. The solo-owner exception removes independent reviewer
separation only; it does not waive manual approval, branch restrictions,
candidate identity, TestPyPI qualification, provenance, or downloaded-install
proof.

Before the first upload, a missing package page or version is expected only
when the authorized pending-publisher setup above is verified. A `404` is not
permission by itself. A name collision, rejected pending publisher or ambiguous
account authority stops publication; never switch names or use a token fallback.
After an upload, missing exact-version metadata (`index_version_missing`)
blocks promotion until the index result can be resolved. Check that the new
project is owner-controlled and that its pending publisher became active.
This setup follows [PyPI's first-project Trusted Publishing documentation](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).

## Candidate qualification

1. Require a clean `main` checkout at the candidate commit. Keep the source
   frozen through publication. The version, commit, source-tree hash, spec,
   acceptance table, tool lock and all M0–M3 receipts must match the ledger.
2. Run the full M3 gate and require the eight-cell Linux/Windows × CPython
   3.11–3.14 aggregate at `evidence/local/v0.4.0/M3-platform-matrix.json`.
   Both verification and publication workflows must pass this versioned path
   explicitly; the verifier's default matrix path is reserved for historical
   evidence. Do not substitute a local-only report.
   Before either index upload, the protected workflow also runs
   `tools/check_attestation_policy.py` under Ubuntu 24.04 / CPython 3.12 after
   installing only `requirements-release.lock` with hashes. This exercises the
   locked Sigstore policy against synthetic X.509 claim extensions; it is a
   deterministic verifier regression, not live publisher proof.
3. Dispatch **Publish Mudra Interact** with version `0.4.0` and the exact candidate
   commit. The workflow builds twice, compares wheel and sdist bytes, validates
   the source-built wheel, installs it in a clean isolated environment, and
   freezes one wheel plus one source distribution. The output is kept as a
   workflow artifact; do not rebuild it later.
4. The local offline receipt can say `BLOCKED` only because it ran on one
   platform cell. The publish job separately requires the complete M3 matrix,
   zero local verifier errors, a clean repeat build, successful isolated
   installation and verified runner network isolation.

## Promotion sequence

1. The `pypi-test` publisher receives only the frozen workflow artifact and
   uploads to TestPyPI. The workflow then queries the exact version, downloads
   every file from that one index, checks the filename/size/SHA-256 against the
   frozen candidate, and performs a fresh isolated install smoke from the
   downloaded wheel. It does not use an extra index or rebuild.
   The smoke installs only the downloaded wheel with `--no-index --no-deps
   --no-cache-dir` in a fresh environment; the package has no runtime
   dependencies. For manual inspection, install the candidate from TestPyPI
   with that index explicitly and no PyPI fallback:
   `python -m pip install --no-deps --index-url https://test.pypi.org/simple mudra-interact==0.4.0`.
2. Only after that check passes does the production job wait at the
   `pypi-production` protected environment. The owner must manually approve
   this run after checking its version, commit and candidate artifact
   fingerprint. The current solo-owner policy permits the owner to approve
   their own run; it is not an independent review. Administrator bypass is
   disabled. Once approved, the production publisher uploads the *same frozen
   files* using the configured Trusted Publisher. Long-lived tokens are not a
   fallback.
3. The workflow queries PyPI for the exact version, downloads and hashes each
   production file, verifies the PyPI Trusted Publisher attestations and runs a
   second fresh isolated install smoke. TestPyPI evidence cannot stand in for
   this production proof. Each cryptographically verified attestation must
   bind the downloaded artifact name and digest, OIDC issuer, repository, full
   candidate source commit, workflow configuration, trigger, and exact workflow
   run and attempt. Separately, the PyPI Integrity API's publisher assertion
   must name the exact repository, workflow and `pypi-production` environment.
   The environment value is a PyPI assertion, not a signed Fulcio certificate
   claim. The verifier also checks the `publish-pypi` job in the candidate
   commit's signed workflow source: it declares `pypi-production` and uploads
   the frozen candidate files. Protected-environment configuration and run
   evidence are checked independently. Unsigned publisher metadata plus an
   unrelated successful GitHub run does not meet this requirement.
4. After production verification, create the immutable `v0.4.0` tag/release
   against the candidate commit and attach the same wheel and sdist. Existing
   tags/releases are never overwritten. The workflow exports a sanitized
   publication manifest as an Actions artifact.
5. Download that manifest into `evidence/releases/published.json` and run:

   ```bash
   # Ubuntu 24.04, CPython 3.12; this is the hash-locked verifier platform.
   verifier_dir="$(mktemp -d "${TMPDIR:-/tmp}/mudra-release-verifier.XXXXXX")"
   python3.12 -m venv "$verifier_dir/venv"
   "$verifier_dir/venv/bin/python" -m pip install --require-hashes -r requirements-release.lock
   "$verifier_dir/venv/bin/python" tools/verify_release.py --published --report evidence/releases/published-verification.json
   ```

   Keep the verifier environment outside the checkout so it cannot alter the
   source-tree digest being checked.

   The read-only verifier checks live index metadata and artifact bytes on both
   indexes, exact GitHub run/tag/release identity, environment protection,
   signed publisher attestations and fresh downloaded installs. It does not
   upload, rebuild, overwrite or yank. Missing, stale, partial or mismatched
   proof returns `BLOCKED`.

No rebuild is allowed between qualification, TestPyPI, PyPI and GitHub release.

6. Commit the sanitized publication manifest and verification report, update
   the implementation ledger to M4 only when this verifier and every E90–E99
   acceptance case pass, then push the evidence commit. The source-tree digest
   deliberately excludes `evidence/` and the status ledger; any source,
   contract or tool-lock edit requires the relevant gates to be rerun.

## Ambiguous uploads and recovery

If an upload times out or its response is lost, do not blindly repeat it.
Query the exact package version on that same index. Retry with the same frozen
files only after the index confirms the version is absent. Resume only if the
complete filename set, sizes and SHA-256 values exactly match. A partial set,
different digest, different publisher or inconclusive response stops promotion
for investigation; never rebuild or overwrite a published version.

Rollback is a controlled consumer recovery. Halt promotion, identify the
affected version, restore a verified version in consumers, then use an
authorized package yank or a separately reviewed patch release. Preserve
public history; never delete or rewrite released artifacts. The decision helper
is tested but cannot perform a yank or publish a patch.

## Post-release and limits

Confirm the public [PyPI version page](https://pypi.org/project/mudra-interact/0.4.0/)
and [GitHub release](https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.4.0)
open, and that both expose the exact version and artifact hashes. Run the
documented consumer smoke from the downloaded wheel. Report the source commit,
candidate fingerprint, artifact digests, workflow run, protected environment,
index verification and tested platforms.

The public core does not implement a camera adapter and synthetic acceptance
tests do not establish field accuracy, cultural review, accessibility or
independent security assessment. Keep each claim separate in release notes and
the final report.
