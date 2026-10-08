# Astra technical review and Luna release handoff

Reviewed 2026-10-08 against `7c95adc` in the existing primary checkout.
Review kind: **Astra model technical review**, not independent human review,
cultural validation, accessibility qualification or an exhaustive security audit.
The review inspected the core specification, acceptance matrix, ledger,
proposal, runtime session boundary, licence inventory, release tooling and
workflows. The owner requested Astra review followed by Luna publication.

## Decision

Approve the layered language direction and the bounded
[follow-on design](COMMUNICATION_LANGUAGE_CONTRACT.md) for future engineering.
Publish `mudra-interact==0.2.0` as the existing offline gesture/event foundation
**only after the concrete findings below are fixed and the current candidate
passes all required gates**. The package need not wait for the future language
implementation. Do not call `0.2.0` a completed communication language, creative
AI host plugin, camera adapter, or MCP/A2A integration. No specific creative
host was requested; do not assume InvokeAI or another host.

The current release preserves four contact rules, neutral labels, strict v2
inputs, temporal stability and one-use confirmed events. It has no runtime
network/model/camera dependency. Communication between human/agent role pairs
is recorded; identity, intent interpretation and downstream authority are not
established by those labels.

## Release-blocking findings and exact repairs

| Finding | Evidence and effect | Required repair / acceptance |
| --- | --- | --- |
| AR-01: malformed confirmation time preserves stable recognition | On reviewed source, process `examples/v2/batch.json`; `confirm(True, True, True)` raises `invalid_sequence` but `current.state` remains `stable`; correcting only the time allows confirm and emit with no fresh observation. This violates spec 5.3. | In `RecognitionSession.confirm`, any malformed/denied confirmation must clear grants and pending recognition before returning an error, preserving accepted sequence/operation watermarks. Keep exact error codes and one-use rules. Add E38/E40 regressions for bool, string, float, negative, above safe-integer bound, both with/without prior grant. Assert immediate emit/reconfirmation cannot reuse the old result; fresh valid frames can recover. |
| AR-02: attestation not joined to exact candidate source/run | `_verify_pypi_attestation` checks publisher wrapper repo/workflow/environment and runs the repository-level CLI verifier. It does not explicitly enforce signed candidate commit/run claims. Separately checking a GitHub run's head does not bind each attestation to that run. | Enforce source commit and run identity inside cryptographic attestation verification, plus subject filename/hash, repository/workflow/environment. E93/E98 must reject mismatched/missing/malformed signed claims even when the unsigned wrapper and artifact match. Check both wheel and sdist. No unverified certificate parsing as proof. |
| AR-03: current source is not the qualified historical source | Reviewed tree digest was `2066d3350c5d8e74084887ba165e692fe65d0d4b008ae7b57394a6d990832a13`; old receipts claim source `981aec9c...`. The tracked proposal, then this review and repairs, change source identity. | Retain historical evidence honestly; restore current VERIFIED states only after frozen-source MI-01..MI-09/M0..M3 reruns, complete eight-cell matrix and aggregate M3. Do not exclude review docs or relax fingerprint checks to preserve old passes. |
| AR-04: initial-publication instructions were circular | Runbook required an existing project and stopped on any missing page, although PyPI supports owner-authorized pending publishers that create a project on first use. | Spec/acceptance 0.3.1 and runbook now distinguish existing-project control from authenticated pending-publisher authority. 404 alone remains insufficient; pending setup reserves no name; collisions/ambiguous authority block and post-upload identity is required. |
| AR-05: stale release setup claims | Earlier ledger prose contradicted the approved solo-owner policy and live environment state. Main verify run `37719516530` was reported failed across all eight cells after the proposal change. | Recheck live setup and inspect actual failed-job diagnostics. Root restored approved production reviewer/self-approval/no-bypass/main-only and created main-only `pypi-test` during this review. Record sanitized fresh setup evidence; do not infer index publishers from GitHub environments. |

AR-01 is a local deterministic reproduction, not an exploit/authentication claim:
the core already states hostile in-process Python is outside its trust boundary.
It nevertheless violates the promised accidental-stale-confirmation contract.
This review did not repair production code or execute the complete acceptance
matrix; a passing historical test count cannot close these new counterexamples.

## Concrete attestation implementation constraints

Use the hash-locked `pypi-attestations==0.0.30` and its locked Sigstore dependency.
The [Python API](https://pypi.github.io/pypi-attestations/pypi_attestations.html)
supports verification against an identity policy and actual distribution.
`certificate_claims` alone is parsing, not verification. Prefer policy checks
within `Attestation.verify(identity=..., dist=...)`, retaining filename/digest
verification of the downloaded bytes. Check the installed locked API before
coding; do not add unpinned runtime/build dependencies.

The required authenticated claim tuple is GitHub OIDC issuer, repository URI,
source repository digest equal to the full candidate commit, workflow config
URI for this repository's `.github/workflows/publish.yml@refs/heads/main`,
`workflow_dispatch` trigger, and run invocation URI for the exact release run
ID and verified attempt number. Preserve the existing required environment
identity through its authenticated workflow/certificate identity and configured
publisher checks; an unsigned wrapper is insufficient by itself. Resolve
`run_attempt` from the matching live GitHub run, include it in the bound release
evidence and pass candidate identity explicitly through verifier callers. Use
Sigstore policies such as `AllOf`, `OIDCIssuerV2`, `OIDCSourceRepositoryURI`,
`OIDCSourceRepositoryDigest`, `OIDCBuildConfigURI`, `OIDCBuildTrigger`, and
`OIDCRunInvocationURI` if those names are present in the locked API. Do not
silently skip absent extensions or soften checks to get a first upload through.

Tests must exercise policy evaluation/failure propagation, not merely assert a
CLI string or replace the entire verification path with `True`. Cover each
wrong and absent signed claim while preserving an otherwise matching wrapper,
and corrupted signatures/digests. Synthetic cases test rejection logic only;
actual signed production artifacts remain required for M4. If real evidence
cannot supply an intended claim, stop with the precise blocked check for review.

## Luna execution order and ownership transfer

1. Take sole writer ownership of this existing checkout after this review's
   commit. Preserve source and historical receipts; no extra development clones
   or worktrees. Read current ledger and inspect the diff/failed CI diagnostics.
2. Add failing regression evidence for AR-01, implement its bounded fix, and
   make AR-02's signed-claim verification explicit with independent negative
   tests. Ordinary fixes within this reviewed contract need no new user approval.
3. Check pending-publisher setup separately for PyPI and TestPyPI. Use the
   already authorized owner account and exact tuple in the runbook. Root owns
   browser/account interaction. At review time no pending index publisher had
   yet been submitted; TestPyPI sign-in remained outstanding. No API tokens.
4. Stage only owned files and update the licence byte inventory after deliberate
   source changes. Commit a coherent fixed candidate. Freeze tracked product,
   test, contract, schema and tool-lock files before qualification.
5. Restore prerequisite receipts in dependency order: MI-01/M0; MI-02..04/M1;
   MI-06, MI-05, MI-07/M2; MI-09; MI-08 actual Linux/Windows x86_64 on Python
   3.11..3.14, 8/8. Invoke existing verifiers and record actual outcomes. The
   current FAILED/IMPLEMENTED states are not waiver or completion evidence.
6. Commit only evidence and ledger changes, aggregate the eight-cell matrix,
   dispatch the hosted full M3 gate, import its actual report and linked pytest
   artifacts, then mark VERIFIED only for matching source/spec/acceptance/locks.
   Evidence/status commits do not alter the qualified source digest. If repairs
   or documentation change afterward, requalify affected scopes.
7. Recheck both environments/publishers; dispatch the protected publish workflow
   on current `main` with exact full candidate commit and `0.2.0`. It must freeze
   one reproducible artifact pair, upload/verify TestPyPI, and present version,
   commit and fingerprint for the already required manual owner production
   approval. Keep deliberate self-approval permitted and administrator bypass
   disabled. Reuse valid existing authorization; no redundant review prompt.
8. Publish the same files, verify exact signed production provenance and fresh
   downloaded installation, create immutable tag/release, import sanitized
   manifest, run published verifier and MI-10/M4. Only actual complete evidence
   closes M4. Do not report publication based on dispatch, source push or mocks.

Production setup observed by root after correction: required reviewer
`mayayaiinfra`, self-approval permitted, no administrator bypass, zero wait
timer and only `main`. `pypi-test` now exists with no administrator bypass and
only `main`. These observations are not lasting guarantees; recheck before
promotion. The PyPI account's lack of active projects is consistent with first
publication, not proof of name ownership or availability.

## Future work and claims

The new design freezes a minimal message vocabulary, bounds, creative-plan
profile, conversation relationships, pure validation/rendering APIs and an
independent backlog. Every future item starts NOT_STARTED. It deliberately
keeps network/host/model integrations separate and does not choose a host by
assumption. Broader language work can proceed after the `0.2.0` release under
the user's direction, but must receive its own implementation/conformance and
release evidence. Representative human comprehension, cultural and
accessibility validation must come from real people and cannot be marked passed
by Astra or Luna.

The initial-publication clarification follows [PyPI's pending-publisher guide](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
This review authorizes no spending and introduces no weaker release gate.
