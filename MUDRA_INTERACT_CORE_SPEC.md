# Mudra Interact Core: Implementation and Release Specification

Specification **0.3**, owner-approved platform scope update **2026-10-07**;
core contract review: Astra **2026-10-06**. Owner: MAYAYAI.
Implementation baseline: `eae92b7`, package `0.1.0`.
Target: package `0.2.0`, protocol/schema `2.0.0`, catalogue `2.0.0`.
Status: normative implementation contract; progress is tracked in the JSON ledger.

Read [acceptance cases](docs/ACCEPTANCE.md), [Luna handoff](docs/LUNA_HANDOFF.md)
and [dependency/status ledger](IMPLEMENTATION_BACKLOG.json). This document owns
behaviour; acceptance owns expected outcomes; the JSON ledger owns progress.
Resolve disagreements before coding. All MUST/required statements are gates.

## 1. Deliverable and limits

Deliver a public Apache-2.0 offline Python library/CLI, four geometric contact
rules, strict inputs, temporal stability, explicitly confirmed semantic events,
schemas, conformance fixtures, installed wheel/sdist, CI, release evidence and
verified package publication. Include a separately gated camera-adapter DESIGN.
Keep the existing geometric capabilities; do not substitute fewer rules/tests
to obtain a passing gate.

This is a reference implementation, with no evidence of SOTA performance,
calibrated probabilities, research novelty or adoption as a standard. Synthetic
tests cannot establish recognition accuracy, cultural meaning, accessibility,
clinical efficacy or host privacy. Five legacy tests prove only their cases.

ALLYK camera UI, authentication, storage, billing, model assets and action
execution remain private downstream concerns. A public release must not silently
upgrade a private ALLYK copy or consumer. Record compatibility before upgrades.
The core has no camera, network, telemetry, persistence, model or shell runtime.

Luna implements and self-verifies engineering gates through executable evidence.
This is not independent human review. It must not invent reviewer decisions,
credentials, package ownership or publication authority. This request enhances
the plan; it does not itself implement or publish package 0.2.0.

## 2. Baseline defects requiring regression evidence

| Finding at eae92b7 | Evidence | Required correction |
| --- | --- | --- |
| Consent defaults true; string `false` is accepted | Direct reproduction | Explicit exact booleans; no event on denial. |
| Three rejected results become stable | Direct reproduction | Rejected input resets; never promotes. |
| Same observation can be counted three times | Direct reproduction | Distinct frame identity and monotonic timing. |
| Numeric strings, booleans and NaN accepted as points | Direct reproduction | Reject coercion/non-finite numbers at every boundary. |
| Metadata contains raw-data strings | Direct reproduction | Closed structural fields; no arbitrary text bag. |
| NaN confidence silently becomes zero | Direct reproduction | Reject invalid scores/configuration, never clamp. |
| CLI --stabilize processes only one frame | Source inspection | Real bounded frame batch, one session. |
| Image-normalized axes have unequal units | Source and MediaPipe contract | Declared coordinate space and aspect conversion. |
| Catalogue asserts reviewed without records | Source inspection | Explicit unreviewed aliases; neutral display until evidence. |
| Licence check only tests a licence string/NOTICE existence | Source inspection | Inventory, notice coverage, hashes, pending-asset exclusion. |
| Frozen objects expose mutable metadata; strings truncated | Source inspection | Copy/freeze values; reject collisions and wrong types. |
| README path and one-point sample are unsuitable | Source inspection | Valid 21-point examples tested from installed package. |

The legacy tests and licence script passed during this review despite the
defects. Their passing result is not acceptance of the corrected release.

## 3. Version, schema, validation and resource contract

### 3.1 Breaking revision

Use protocol `2.0.0` and pre-1.0 package `0.2.0` for the corrected contract;
document breaking API/CLI changes explicitly. No silent v1 -> v2 import, unsafe
compatibility flag, or conversion of old stored consent into fresh authority.
Provide historical v1 inspection/migration examples. Old events need new
observations, consent and confirmation for new sharing.

Parsers require the exact supported version and reject unknown fields/versions.
Future additive fields need explicit reader support. Ship draft-2020-12 JSON
Schemas with closed objects, limits and local bundled references only. Schema
validity alone cannot establish stability, consent or scope authorization.

### 3.2 Fixed target bounds

| Input | Requirement |
| --- | --- |
| Points | Exactly 21; x/y/z required; builtin finite int/float excluding bool |
| Coordinates | abs(value) <= 16 both before/after declared conversion |
| Image size | Positive int width/height <= 16,384, excluding bool |
| Palm scale | Wrist-to-middle-MCP Euclidean distance >= 0.0001 |
| JSON bytes | Frame <= 65,536; batch <= 1,048,576; event <= 4,096 UTF-8 bytes |
| JSON structure | Depth <= 16; string <= 1,024 Unicode scalars before tighter field limits |
| Batch | 1..256 frames; same stream; strictly increasing IDs/times |
| Identity/time | Canonical UUID stream_id; integer frame_id/monotonic_ms in [0,2^53-1] |
| Contact threshold | Default 0.34, finite [0.05,0.75] |
| Stability | required_frames default 3, integer [2,12]; minimum_confidence default 0.6, finite [0,1] |
| Timing | minimum_hold_ms default 100 in [0,2000]; maximum_gap_ms default 250 in [1,1000], integer |
| Confirmation | Maximum age 5,000 monotonic ms; exact result/scope/stream binding |

Do not silently clip, truncate, stringify, cast or default outside values.
Accept concrete bounded list/tuple sequences only, not generators or arbitrary
iterables. Do not run caller-defined numeric/string/iteration hooks. Bounds do
not establish anatomical validity. Float-valued configuration may accept builtin
int under the same finite/type rules; integer settings never accept float/bool.

Bound reads to limit+1 before parsing. Reject duplicate JSON keys at every
level, NaN/Infinity, exponent overflow, invalid UTF-8/BOM, excessive depth and
trailing documents. Before recursive decoding, scan nesting with string/escape
awareness; catch decoder errors. Reject lone Unicode surrogates. No remote
schema resolution, YAML/pickle loader, subprocess or dynamic import in runtime.

### 3.3 Errors

Add `MudraValidationError(code)` using only these safe codes: invalid_json,
input_too_large, invalid_shape, invalid_number, invalid_geometry,
unsupported_version, invalid_configuration, invalid_sequence, invalid_state,
consent_required, confirmation_required, stale_confirmation, scope_mismatch,
catalog_invalid, unsupported_platform, input_unavailable, internal_error.
Never interpolate input/path/exception details into a public error.

Malformed public API arguments raise a typed error. Valid unsupported geometry
returns uncertain. A session may expose a local rejected result with a fixed
code, but denial must not produce a shareable event. Error output is never a
successful event labelled rejected. Specify code precedence in acceptance
fixtures when input violates multiple constraints (parse/type before consent).

In-process hostile Python can fabricate booleans/objects/IDs; the library is
not an authentication service or sandbox. Hosts own capture integrity, identity,
consent UI, anti-replay storage and downstream action permission.

## 4. Frame geometry and complete recognition oracle

`Frame` fields: schema_version, stream_id, frame_id, monotonic_ms,
coordinate_space, landmarks; image_width/image_height only for the image space.
Each frame is one selected hand. Multiple hands require separate streams.

- `cartesian_relative_v1`: x/y/z already share one distance unit; dimensions
  forbidden. The core infers no handedness or real-world unit.
- `mediapipe_image_v1`: dimensions mandatory. Transform every point to
  `(x, y * image_height / image_width, z)` before geometry. Reject mixed space,
  missing dimensions and post-conversion bound violations. Do not clamp points
  simply because they lie outside [0,1].

This conversion follows MediaPipe's image axes and approximate z scale, not
calibrated physical depth. Callers with world points supply the documented
Cartesian representation explicitly. No unit guessing or pixel/world mixing.
Divide contact distances by palm scale. Translation, positive uniform scaling,
reflection and Cartesian rotation preserve results within valid bounds.
Nonuniform scaling/image distortion is not an invariant.

Contact bits I/M/R mean thumb-index/middle/ring. Distance <= threshold counts.
Test nextafter-below/equal/above on the predicate independently of geometry.

| I M R | gesture_id | state | heuristic confidence |
| --- | --- | --- | --- |
| 0 0 0 | unknown | uncertain | 0.0 |
| 1 0 0 | contact_thumb_index | candidate | 0.72 |
| 0 1 0 | contact_thumb_middle | candidate | 0.70 |
| 0 0 1 | contact_thumb_ring | candidate | 0.70 |
| 0 1 1 | contact_thumb_middle_ring | candidate | 0.78 |
| 1 1 0 | unknown | uncertain | 0.0 |
| 1 0 1 | unknown | uncertain | 0.0 |
| 1 1 1 | unknown | uncertain | 0.0 |

These preserve the four geometric rules under neutral IDs. Historical Mudra
names remain migration aliases, not inferred cultural truth; contact alone
never distinguishes Gyan/Chin. Fixed scores are rule strengths, not measured
probabilities. Score/calibration changes require a versioned method and evidence.

Recognition fields: gesture_id, confidence, state, method `contact_rules_v2`,
catalog_version `2.0.0`, observation_codes, uncertainty_codes. Use immutable
tuples of <=8 unique enum codes per list. Observations: thumb_index_contact,
thumb_middle_contact, thumb_ring_contact. Uncertainties: unsupported_pattern,
ambiguous_contacts, posture_unverified, low_confidence, insufficient_frames, hold_incomplete,
frame_gap, gesture_changed. Never serialize distances or caller prose.
Constructors and import use the same checks and rule/state/score consistency.
No arbitrary method/catalogue/score can enter the trusted recognition path.

Order observation codes I, M, R. Every supported pose includes posture_unverified
even when stable; temporal stability never proves full posture/cultural meaning.
Unknown/no-contact uses unsupported_pattern; conflicting contacts use
ambiguous_contacts. Session state may add exactly one temporal uncertainty from
the transition rules. Candidate rule scores match the table exactly; for stable
means accept only the mathematically expected score within 1e-12 absolute error.
No missing fields/default method at wire boundaries. Rejected is a local session
result with unknown/0.0 and a fixed error reason; it is not a valid event state.

## 5. Session, stability, confirmation and event lifecycle

### 5.1 Session state

Add `RecognitionSession` to coordinate recognizer, stabilizer and event factory.
One session owns one stream and optional UUID conversation/project scope,
immutable configuration and bounded memory. No globals/mutable defaults.
Low-level helpers remain available but cannot create a local sharing grant.

`observe(frame)` requires strictly increasing frame_id AND monotonic_ms. A
duplicate/backward value invalidates confirmation, clears the streak and raises
invalid_sequence. Different IDs/times with identical points are allowed.
On stream/scope mismatch invalidate confirmation and reject; start a new session
to change scope. IDs are supplied by trusted capture, not inferred from calls.

Invalidate any grant at the START of observe(), even when parsing that frame
subsequently fails. Accepted sequence watermarks advance only after full frame
validation. Track the largest valid session-operation time across observe,
confirm and emit; backwards operation time fails closed. A valid operation with
the same time is allowed for confirm/emit on the latest frame, but never for a
new frame. Validation failure clears recognition/confirmation, not the watermark.

`reset()` clears streak/confirmation but preserves the last accepted sequence;
`stop()` clears owned state and makes future operations invalid_state;
`revoke()` clears consent/confirmation/streak, retaining sequence history.
New observations and explicit confirmation are required after revoke.
Sessions are single-owner; shared-thread use requires caller serialization.
Independent sessions and copies must not share mutable storage.

### 5.2 Transition rules

Only recognizer candidates advance a streak. External stable inputs are rejected.
Rejected/uncertain/low-score input clears it; rejected can never promote.
Low-score means score < minimum_confidence (equality qualifies); return a local
unknown/0.0 uncertain result with low_confidence and no retained candidate.
Changed gesture restarts at one, invalidates confirmation and
returns uncertain for that conflicting frame. Initial supported frame remains
candidate with insufficient_frames. Later compatible frames continue the new
streak. Invalid input must not present an old stable result as current.
The conflict report is unknown/0.0 with gesture_changed; the new validated
candidate remains internally as frame one of the new streak. A method/catalogue
mismatch is invalid_state, clears the streak and cannot hot-swap versions.

Keep at most required_frames candidate records plus uninterrupted streak
start/count. Stable requires that many distinct valid frames AND streak duration
>= minimum_hold_ms. Retain start time even when the bounded window slides.
A gap > maximum_gap_ms restarts at one; equality is allowed. High frame rates
cannot bypass hold time. Stable confidence is the mean of the last N scores.
Use monotonic times only, never wall clocks/sleeps. No timer/background worker.

### 5.3 Confirmation and emission

`confirm(consent_confirmed, participant_confirmed, now_ms)` requires both exactly
True, current stable result, and frame_time <= now_ms <= frame_time+5,000.
Missing/false/string/integer values cannot grant consent. The host calls this
only following a real UI confirmation; agent sender does not bypass it.
Each confirm attempt first clears any existing grant. Denied or malformed
confirmation revokes the session's pending recognition; fresh observations are
required rather than allowing an older grant to survive denial.
Bind confirmation to stream, last frame ID, result revision, scope, method and
catalogue. Every later observation (even same gesture), reset, revoke, stop or
expiry invalidates it. Time arguments use strict integer bounds from section 3.

`emit_event(sender, recipient, now_ms, event_id=None, occurred_at=None)` checks
that binding and freshness, consumes it once, and returns an immutable event.
Absent consent maps to consent_required; absent confirmation or nonstable
recognition maps to confirmation_required; an expired/bound-to-old revision
maps to stale_confirmation. Never recover an old grant after an attempted emit
fails, including invalid sender/ID/time arguments. Defaults for CLI sender and
recipient are human and agent; both values must remain explicit in event bytes.
A new observation followed by confirmation is required for another emission;
confirming the same consumed revision again fails. Serialization failure consumes
the attempted grant too; never automatically replay an ambiguous send. Repeated
serialization of an existing event is pure and allowed.

This prevents accidental stale local sharing, not malicious Python in the same
process. Imported events cannot become session grants. Receivers deduplicate IDs
under authenticated scope; stable/consent flags never authorize an action.

## 6. V2 event fields and privacy semantics

Event fields are exactly:

- schema_version `2.0.0`, event_id canonical UUID, occurred_at valid UTC
  `YYYY-MM-DDTHH:MM:SS.ffffffZ`;
- sender and recipient (`human`/`agent`), direction computed from them;
- privacy_mode `event_only`, consent_confirmed true, participant_confirmed true;
- conversation_id/project_id, each null or canonical UUID;
- validated stable recognition;
- raw_media_included false, raw_landmarks_included false.

No metadata bag, URL, path, label prose, contact distance, frame/stream ID,
camera identifier or image dimensions. Drop old `raw_*_retained` assertions:
the core cannot know what a host/recipient retains. Document consumer migration.
All four party directions describe a record, not identity or action authority.

Default event ID/time are generated at emission; allow explicit valid values
for fixtures. Wall occurrence time is descriptive and never drives expiry.
On import, enforce exact types, limits and direction/state/version invariants.
Serialize sorted keys, compact separators, UTF-8, no NaN/Infinity; CLI adds one
newline. Do not claim RFC8785 canonicalization or signing compatibility.
Copy/freeze inputs; payload() returns fresh detached structures every time.

Closed fields prevent structural raw-data embedding, not covert data in UUIDs
or downstream image retention. No promise of Python memory zeroization, host
crash-dump erasure or mathematical absence of personal information. Do not retain
points after observe() returns. API/docs must state these practical limits.

## 7. CLI contract

Commands: `mudra-interact recognize --input <path> [--stabilize]`,
`mudra-interact validate-event --input <path>`, `--version`, `--help`.
Retain `mudra-interact --input <path>` as recognize shorthand with the v2
requirements; legacy missing-version inputs fail, never imply consent.

Recognize takes one Frame without --stabilize, or a closed object
`{schema_version:"2.0.0",frames:[...]}` with it. Process a real batch through
one session; emit only the final LOCAL report (schema_version, recognition,
reason_code/null). One frame cannot become stable. All frames must validate;
malformed late input fails the batch without partial success. A local report
is not a MudraEvent and requires no sharing grant.

The local reason_code is null for stable, unsupported_pattern or
ambiguous_contacts for geometry uncertainty, and insufficient_frames,
hold_incomplete, low_confidence, frame_gap or gesture_changed for temporal outcomes. Apply
precedence: invalid input -> command error; unsupported geometry -> its uncertainty;
low score -> low_confidence; gesture conflict -> gesture_changed;
gap reset -> frame_gap; too few frames -> insufficient_frames; hold not met ->
hold_incomplete; otherwise stable/null. A standalone supported frame reports
insufficient_frames. Complete all parsing/schema/config checks before consent
checks; check consent before confirmation, then stability/freshness, then emit.

`--emit-event --consent --confirm` additionally requests sharing, together and
only with --stabilize. Confirm the final stable revision at its final monotonic
time; output one event instead of a report. Flags attest confirmation of this
selected batch, not live-camera consent. Never accept permission from JSON,
environment, sender type or truthy strings. Missing consent/confirmation denies.
Optional --sender/--recipient/--conversation-id/--project-id apply only to event
output with the same type checks. No interactive stdin loop.

validate-event outputs only `{"schema_version":"2.0.0","valid":true}` on
success. It never echoes, reauthorizes or replays the submitted event.

Read only selected local regular files; reject URL, stdin `-`, pipe, device,
UNC/network share and symlink/reparse-point input. Verify opened file handles
and bound read length, not just a prior stat check. Document/test POSIX/Windows
differences. Path selection is caller authority, not a sandbox against hostile
parent-directory replacement. No automatic file discovery or writes.
Do not claim to detect every remotely backed mount or Windows mapped drive.
Reject explicit remote/UNC/device forms; the caller owns the local mount policy.
If a required platform cannot safely open the declared file type, fail with
unsupported_platform and leave that platform proof BLOCKED. Never open a FIFO
with a blocking operation before checking its type; exercise race/error paths.

Exit 0 valid result; 2 usage/input; 3 consent/confirmation denial; 4 IO/platform/
internal failure; 130 interrupt. Errors leave stdout empty and emit one <=512-byte
stderr JSON line `{"error":{"code":"fixed_code"}}`. No path, input echo,
exception text, stack or raw argparse argument. Help alone prints normal help.
Broken pipe exits nonzero quietly. Build full bytes before one output write;
partial write failure is possible and never grants success/retry. User-directed
output redirection is caller retention. Test outside the source checkout.

## 8. Catalogue and adapter design

Base catalogue entries use the four neutral IDs/display names, version, contact
definition, limitations, provenance reference and content licence. Reject duplicate
IDs, wrong versions, missing rule mappings/fields and unknown fields; never
silently drop/overwrite entries. Return immutable or detached lookup values.

Historical cultural labels are unverified until real evidence exists. An optional
label pack requires reviewer/evidence references, rights, language/tradition
scope, prohibited claims and withdrawal/version records. Luna cannot fabricate
cultural review. Geometric core acceptance remains separate from label-pack
acceptance; missing review cannot be disguised as an approved cultural release.

MI-09 produces ADAPTER_SPEC.md: pinned/licensed/hashed assets; explicit start
and visible capture; one selected hand; aspect conversion; monotonic identity;
hand loss, device/track switch and tab-hide resets; cancellation of late callbacks;
revocation drops queued results; bounded queues/latest-frame backpressure;
neutral rearm; mirroring; model-loading failure; permission denial; cold-cache/
offline behaviour; non-camera accessibility alternative; editable confirmation.
No images in telemetry or implicit BYOK capability probes.

Model/camera implementation, OS/browser quality, licensing and human cultural/
accessibility review are separate release gates. Fake frames and a design doc
cannot verify a real adapter. Do not add model downloads/private UI/native
frameworks to satisfy the public core. Runtime remains standard-library only.

## 9. Packaging, CI and publication

Target support: CPython 3.11/3.12/3.13/3.14 on Linux x86_64 and Windows x86_64:
8 required cells. macOS is outside the supported and qualified platform scope;
no compatibility claim is made for it. No untested interpreters/architectures
are implied. Pin runner families and record actual OS/interpreter builds. A
missing cell blocks M3; changing this platform scope requires explicit owner
approval, not an agent exception.

MI-08 pins development/build/test dependencies and hashes; no runtime dependency
is added. Fetch approved tools during explicit setup, then build/test offline.
Offline evidence requires OS/runner network blocking and an attempted-egress
negative probe; PIP_NO_INDEX alone is insufficient. Missing build tooling is a
setup failure, not successful packaging. Tests use synthetic data/no credentials.

Build a wheel/sdist from a clean tracked snapshot. Rebuild a wheel from sdist
offline with pinned tools. Install only wheel into fresh venv with --no-index
--no-deps, unset PYTHONPATH, leave checkout, assert imported module is in the
venv, run API/CLI smokes. Include schemas/catalogue/notices/licence/typing files;
exclude caches/venvs/raw test corpora/credentials/absolute local paths.

Repeat builds with SOURCE_DATE_EPOCH and fixed locale/timezone/toolchain.
Require identical wheel/sdist bytes in the same declared build environment;
unexplained mismatch blocks M3. Cross-platform evidence logs need not match and
cross-platform binary reproducibility is not claimed without proof. Generate
SBOM/component inventory from actual shipped artifacts with separate build-tool
provenance. A hash identifies content; it does not establish authenticity.

Licence checker rejects empty/malformed/deleted policy, missing core component,
unknown status/licence, absent notice coverage, missing/mismatched bytes and
unlisted shipped assets. Pending adapters cannot be reclassified as included
without evidence. Do not auto-expand Apache-2.0/MIT allowlist. The checker is
engineering evidence, not legal compliance certification.

Ordinary CI uses read-only permissions, pinned action revisions, timeouts,
bounded artifact retention and no credentials on untrusted PRs. Publishing is
a separate protected least-privilege job with configured publishing identity,
verified source/artifact provenance and no checked-in long-lived token.

M4 sequence: verify candidate -> freeze source/artifact/evidence hashes ->
record release authorization (reuse valid existing authorization) -> TestPyPI
upload/download/exact-version install -> production upload of SAME artifacts
-> download/hash/installed verification -> GitHub release/tag/artifact links.
Verify repository/package-name/publisher ownership first. Separate indexes and
accounts; single-index downloads with --no-deps, no extra-index fallback.
No rebuild after acceptance, overwritten tag or reused published version.
Ambiguous upload: inspect exact remote version/hashes before retry; matching
files may resume, different bytes stop release. Missing access remains BLOCKED.

Ship migration notes, changelog, SECURITY.md, support matrix and known limits.
Verify public links after release. Recovery means halt promotion, identify the
affected version, restore a verified version in consumers and use an authorized
yank or patch release. Never rewrite public history/delete user data. The core
has no server deployment. Source push alone is not package-publication success.

## 10. Gates, evidence and completion

| Gate | Items | Proof required |
| --- | --- | --- |
| M0 | MI-01 | Schemas, independent fixtures, executable verification harness |
| M1 | MI-02, MI-03, MI-04 | Strict validation, all rules, sequence/stability/consent lifecycle |
| M2 | MI-05, MI-06, MI-07 | CLI, catalogue, adversarial/privacy/licence checks |
| M3 | MI-08, MI-09 | Full matrix, offline build/install proof, adapter DESIGN |
| M4 | MI-10 | Authorized exact-artifact publication and downloaded installation |

Dependencies and per-item outputs are in the ledger. State transitions:
NOT_STARTED -> IN_PROGRESS -> IMPLEMENTED -> VERIFIED. FAILED records its case;
BLOCKED records prior state, missing condition and unblock requirement. Fixes
return through verification. Prerequisites must be VERIFIED; one active item.
Code presence/test counts/model confidence never substitute for required proof.
CLI may use a preliminary wheel in M2; only M3 proves full packaging/matrix.

Use one existing development checkout per repository with one writing task at a
time; do not create linked Git worktrees or additional development clones. Keep
the public core and private ALLYK repositories separate. Coordinate checkout
ownership before editing, preserve unrelated changes and freeze source edits
during verification. Disposable owned test copies/virtual environments and CI
verification checkouts remain required where applicable; they are not alternate
development locations. Follow the single-worktree protocol in LUNA_HANDOFF.md.

Luna must run separate adversarial self-review against the fixed acceptance
oracle. Required skip/xfail/xpass, zero collection, missing IDs/tools/platforms,
nonzero exit, timeout, stale results or absent artifacts prevent verification.
Optional camera-runtime tests live outside the required core suite.
Do not edit limits/oracles/matrix simply to make a candidate pass.

Receipts identify item/gate, exact source commit, clean tracked-source digest
(excluding mutable ledger/evidence), specification/acceptance digests, OS/arch/
Python/tool-lock, command argv, exit/duration, collected/pass/fail/skip/xfail
counts, actual case IDs, mutations, artifacts/hashes and limitations. Evidence
commits reference the qualified candidate commit, avoiding self-hash recursion.
Local logs are bounded; public receipts contain synthetic-safe diagnostics only,
no host paths, customer data, tokens or account details.

Implement `tools/verify_gate.py` and `tools/verify_release.py` as specified in
LUNA_HANDOFF.md. They must execute checks and parse results, not trust progress
flags. They do not exist at this baseline; documentation is not implementation.
Mutation checks weaken selected guards in isolated owned copies; named assertions
must fail. Setup/import/syntax failure is not a caught semantic mutation. No
weakened code is staged. A changed consent/privacy/version/release contract needs
Astra review; evidence thresholds cannot be self-waived.

After each completed gate update ledger/docs/evidence, commit coherent changes,
push under existing project authorization, report and continue. Stop only for
unresolvable access/dependency, required owner decision, contract-review switch,
or completed verified release. No permission request per routine component.

## 11. Primary references and evidence limits

Reviewed 2026-10-06:

- [MediaPipe output](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python): image normalization and approximate depth units inform conversion; do not validate our rules.
- [Python JSON](https://docs.python.org/3/library/json.html): add resource/duplicate-key/non-finite controls to defaults.
- [TestPyPI](https://packaging.python.org/en/latest/guides/using-testpypi/): test and production are separate services/accounts.
- [PyPI trusted publishing](https://docs.pypi.org/trusted-publishers/): configure publisher identity before release.

No edge list proves absence of unknown defects. Add newly found counterexamples
as acceptance IDs and rerun affected gates; do not claim exhaustive correctness.
