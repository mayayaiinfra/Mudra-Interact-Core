# Distribution and compatibility

Mudra Interact is a standard-library runtime package.  The supported
public package is `mudra-interact` version `0.2.0`, with the v2 contract,
catalogue and schema versions set to `2.0.0`.  The wheel carries its schemas,
neutral catalogue, `py.typed`, `LICENSE`, and `NOTICE`; it has no
`Requires-Dist` runtime dependencies.

## Required qualification matrix

The release contract requires an installed smoke and the core acceptance
suite on every cell below.  A row is evidence only when that exact runner,
interpreter and architecture executed the checks.  A local result must never
be copied to another row.

| Operating system | Architecture | Python | Required evidence |
| --- | --- | --- | --- |
| Linux | x86_64 | 3.11, 3.12, 3.13, 3.14 | Required qualification |
| Windows | x86_64 | 3.11, 3.12, 3.13, 3.14 | Required qualification |

macOS is not currently supported or qualified. Its Darwin-based runtime and
platform sandbox behavior are not represented by Linux results.

The checked-in workflow enumerates these eight cells. The local release
verifier records the current cell from `platform.system()`,
`platform.machine()` and the running interpreter.  It reports every absent
cell as `BLOCKED`; it does not emulate a platform with a string or an
environment variable.  Each workflow runner emits its sanitized MI-08 receipt
and the receipt's acceptance artifact in the job log.  Restore those exact files
under `evidence/local/mi08-platform-receipts/` and their declared artifact paths,
then run `python tools/aggregate_platform_matrix.py --receipt-dir
evidence/local/mi08-platform-receipts --report
evidence/local/M3-platform-matrix.json`.  The aggregator checks the receipt
hashes, all E73-E84 outcomes, shared source/tool identities (with text
checkout line endings normalized and binary bytes preserved), exact cell set,
unique cells and candidate commit ancestry.  `python tools/verify_gate.py
--gate M3 --report evidence/local/M3.json` refuses to verify M3 unless that
aggregate is fresh and complete. M3 cannot close until all eight supported
cells have fresh receipts.

## Offline and reproducibility contract

Build and test tools are installed from `requirements-dev.lock` with
`--require-hashes` during an explicit setup phase.  The verifier then sets a
fixed source date, locale and timezone, disables user-site packages and runs
pip with `--no-index`.  It builds two clean wheel/sdist pairs, compares their
bytes, extracts the deterministic sdist and builds a wheel from that source.
It installs only that wheel into a fresh virtual environment outside the
checkout, with `--no-index --no-deps`, and confirms that the imported module is
owned by the environment.  A synthetic socket-denial probe and a separate real
egress probe run under OS-level network isolation.  Linux uses a network
namespace with no default route, and Windows uses an active outbound firewall
block scoped to the test interpreter. The verifier records isolation as `VERIFIED` only
when the platform boundary is present and a real egress attempt is denied;
missing isolation blocks E76.

The release report records the source commit, source-tree digest, specification
and acceptance digests, lock digest, exact artifact hashes, metadata/data
inventory and all eight supported cell states. Reports contain synthetic-safe labels
and never contain host paths, credentials, customer data or raw command
diagnostics.

## ALLYK consumer boundary

ALLYK is a private downstream consumer of the public interoperability contract.
This repository contains no ALLYK source, credentials, private catalogue,
adapter implementation or private policy.  A consumer upgrade is accepted
only after its private compatibility inventory confirms the following:

| Contract surface | Current public value | Consumer check | Upgrade risk |
| --- | --- | --- | --- |
| Package | `mudra-interact==0.2.0` (import `mudra_interact_core`) | Install exact wheel with `--no-deps`; verify module ownership | A rebuilt or transitive dependency can change the artifact |
| Schemas | v2 / `2.0.0` | Validate representative synthetic frame, report, batch and event fixtures | A schema change can reject or reinterpret stored work |
| Catalogue | Neutral catalogue `2.0.0` | Check IDs, version and rule mappings before activation | Label packs and cultural claims are not supplied by core |
| CLI | `mudra-interact` with explicit consent/confirmation | Run the private integration smoke against the installed wheel | Flags and error codes are a compatibility surface |
| Privacy | Local-only, no telemetry and no implicit BYOK probe | Inspect private deployment policy and run egress-negative checks | A downstream adapter can introduce retention or network behaviour |
| Licensing | Apache-2.0 core with shipped notices | Re-run the private asset/licence inventory | Optional camera/model assets need separate review |

The inventory is a handoff contract, not an automatic upgrade or a claim that
the private ALLYK integration is implemented here.  A missing private check
blocks the downstream release without changing this public package.

## Known limits

The public core does not include camera capture, model downloads, browser UI,
remote inference, cultural review, or a hosted service.  Recognition quality,
accessibility and any private ALLYK adapter remain separate release evidence.
The release command can therefore prove local packaging and correctly report a
blocked candidate while required external platform or publication evidence is
still unavailable.
