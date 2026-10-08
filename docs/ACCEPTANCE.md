# Mudra Core acceptance contract

Revision 0.3.1, Astra technical model review 2026-10-08; owner-approved platform
scope update 2026-10-07. This is a
required test design, not a passing report.
Authority: [specification](../MUDRA_INTERACT_CORE_SPEC.md).
Progress: [ledger](../IMPLEMENTATION_BACKLOG.json).

## 1. Independent oracles and fixtures

Implement test cases with the IDs below, reporting every parametrized execution
and mapping it to its acceptance ID. An ID in a comment is not coverage: the
runner must verify that collected/executed test nodes actually cover it. Required
parametrizations cannot be skipped. Mark tests with `@pytest.mark.acceptance("E10")`
and have a pytest report plugin record node IDs, parameters and outcomes. Tests
and fixture expected results must be independent of production rule functions,
schema builders and serialization defaults. Expected failures during regression
development are evidence of a defect, not acceptance passes or permanent xfails.

Create `tests/fixtures/v2/manifest.json` with fixture ID, relative path, SHA-256,
case ID, expected success/error/fields and origin `synthetic`. No customer images,
real identifiers, capture recordings or private source. Tests consume committed
fixtures; tests cannot regenerate their own expected outputs at runtime.
Contract changes require corresponding reviewed fixture changes with a reason.

Use Cartesian fixtures with wrist=(0,0,0), middle MCP=(0,1,0), thumb tip=(0,0.5,0).
Set index/middle/ring tips independently to contact distance 0.1 or non-contact
distance 1.0 from thumb; fill all remaining points with finite deterministic
coordinates. These intentionally synthetic points test geometry, not anatomy.
Hand-calculate all eight expected contact-bit outcomes from spec section 4.
For threshold equality, test ContactFeatures predicate directly; use values
away from roundoff for full landmark-to-rule fixtures.

Temporal fixture A: same-stream IDs 1,2,3, times 0,50,100 ms, one supported pose.
Expect candidate,candidate,stable. Fixture B: IDs 1,2,3,4, times 0,1,2,100;
third must remain candidate and fourth may become stable (bounded window must
not lose streak start). Freeze UUID/time only through supported injection points.

Use synthetic sentinel text such as SYNTHETIC_PRIVATE_MARKER in invalid raw
fields, paths and errors. Check it never appears in stdout/stderr/public receipts.
This is evidence for tested channels, not universal proof of information secrecy.

## 2. Required case matrix

Each row owns all variants in its outcome column. A subcase added after a defect
keeps the same parent ID plus a named parametrization. Required module names are
targets; files not present at baseline must be implemented before verification.

| ID | Owner/module | Required outcome / edge variants |
| --- | --- | --- |
| E01 | MI-01 / test_contract_spec.py | Four closed schemas (Frame, Recognition, Event, Catalogue) plus batch/local-report envelopes and fixtures validate offline; no remote refs. |
| E02 | MI-01 / test_contract_spec.py | Manifest hashes/unique fixture IDs/case references validated; a missing or edited fixture fails. |
| E03 | MI-01 / test_contract_spec.py | Explicit 1.0/2.0.0 fixtures and version mapping; unknown/newer version not silently accepted by contract. |
| E04 | MI-01 / test_verification_tools.py | Runner fails for absent command, nonzero exit, timeout, zero tests, omitted ID and unavailable result parser. |
| E05 | MI-01 / test_verification_tools.py | Required skip/xfail/xpass, truncated results, stale source digest and stale spec digest cannot yield VERIFIED. |
| E06 | MI-01 / test_verification_tools.py | Tampered report hashes, dependency cycles/unknown IDs, premature gate closure and hand-edited VERIFIED flag rejected. |
| E10 | MI-02 / test_validation.py | 0/20/22/huge point counts rejected; exactly 21 accepted; generators/string/mapping/custom iterable rejected without iteration hooks. |
| E11 | MI-02 / test_validation.py | Missing x/y/z, extra fields, null, bool, numeric string and custom numeric conversion rejected at constructors AND parser. |
| E12 | MI-02 / test_validation.py | NaN/+Inf/-Inf/overflow/abs>16 rejected; +/-16 and signed zero behave per contract; huge integer cannot overflow conversion. |
| E13 | MI-02 / test_validation.py | Zero/sub-minimum palm scale rejected; equality at 0.0001 allowed; no previous stable result returned on failure. |
| E14 | MI-02 / test_validation.py | Invalid config types, NaN, too-small/large integers/scores rejected without clamp; exact min/max allowed. |
| E15 | MI-02 / test_json_boundary.py | Duplicate keys at top/nested levels, extra docs, invalid UTF-8, BOM, lone surrogate and non-finite literals fail safely. |
| E16 | MI-02 / test_json_boundary.py | Byte limit-1/limit/limit+1, depth16/17, oversized strings and huge batch fail before unbounded read/recursion. Escaped quotes/brackets don't spoof depth. |
| E17 | MI-02 / test_validation.py | No post-construction mutation through originals/returned payloads; copied records and independent objects isolated. |
| E18 | MI-02 / test_validation.py | IDs, dates, enums, unknown versions/fields, incompatible state/score and direction mismatches rejected consistently. |
| E19 | MI-02 / test_validation.py | Exceptions contain only fixed code, never sentinel payload/credentials/path/arbitrary repr, for direct API and parse paths. |
| E20 | MI-03 / test_recognition.py | All eight I/M/R combinations match table; dual M/R recognized, every I conflict uncertain. |
| E21 | MI-03 / test_recognition.py | Contact predicate nextafter below/equal/above for all contacts and threshold min/max; <= remains normative. |
| E22 | MI-03 / test_coordinates.py | Translation/positive scale/reflection/Cartesian rotation preserve eligible fixtures; invalid transformed bounds reject. |
| E23 | MI-03 / test_coordinates.py | Equivalent portrait/landscape image-normalized fixtures match Cartesian oracle after aspect conversion, with nonzero z. |
| E24 | MI-03 / test_coordinates.py | Missing/zero/negative/bool/huge dimensions, mixed/world/image spaces and post-conversion overflow reject; no coordinate guessing. |
| E25 | MI-03 / test_recognition.py | Scores/method/version/neutral IDs exactly match table; score documented as heuristic, Gyan/Chin never split. |
| E26 | MI-03 / test_recognition.py | Fixed code enums only; no distances/caller text in Recognition; unsupported pattern remains uncertain with zero confidence. |
| E30 | MI-04 / test_session.py | Fixture A promotes only at third distinct frame and 100 ms; N=2/12 boundaries tested. |
| E31 | MI-04 / test_session.py | Fixture B high frame rate cannot bypass hold; sliding window retains streak start and bounded memory. |
| E32 | MI-04 / test_session.py | Rejected/uncertain/low score clears streak; three rejected results never stable; score==minimum qualifies and lower score returns unknown/0.0 low_confidence. |
| E33 | MI-04 / test_session.py | Duplicate frame, backward ID/time or equal timestamp invalidates grant/resets; distinct frames with equal points allowed. |
| E34 | MI-04 / test_session.py | Inter-frame gap 250 allowed, 251 restarts; threshold custom bounds tested with injected time, no sleeps. |
| E35 | MI-04 / test_session.py | Gesture conflict restarts count, conflict frame uncertain, next compatible frames build fresh streak; no mixed-method/catalogue promotion. |
| E36 | MI-04 / test_session.py | Scope/stream changes reject; reset doesn't rewind ordering; stop cannot restart implicitly; revoke needs new observations. |
| E37 | MI-04 / test_session.py | External stable recognition cannot be fed as proof; independent sessions isolate history; shared-thread limitation documented/tested at adapter. |
| E38 | MI-04 / test_consent.py | Missing/false/string/integer consent/confirmation denied; both true and current stable required for every sender type; denial after an earlier grant invalidates it and needs new observations. Malformed confirmation time (bool/string/float/negative/above safe-integer bound) also clears pending recognition/grants; correcting only the time cannot recover the old stable revision. Fresh valid observations can recover without rewinding sequence/operation watermarks. |
| E39 | MI-04 / test_consent.py | Confirmation tied to exact scope/stream/revision; later same-gesture OR malformed frame/reset/revoke invalidates it; no last-good result fallback. |
| E40 | MI-04 / test_consent.py | Exact expiry age5000 allowed, 5001 denied; now before frame or prior session clock denied; wall-clock jump doesn't affect hold/expiry. |
| E41 | MI-04 / test_consent.py | One emission per confirmed revision; second emit/reconfirm consumed revision denied; new stable frame+confirmation works. |
| E42 | MI-04 / test_consent.py | Validation/serialization failure consumes attempted emit grant; no successful partial event; retry requires fresh observation. |
| E43 | MI-04 / test_event.py | Four party directions compute correctly; generated/injected UUID/UTC formats valid; repeated serialization byte-identical for same event. |
| E44 | MI-04 / test_event.py | Event importing is validation only and cannot populate a session grant or execute downstream effects. |
| E45 | MI-05 / test_cli.py | Single frame -> local candidate report; real three-frame batch -> stable; single --stabilize frame cannot auto-promote. |
| E46 | MI-05 / test_cli.py | Final stable batch + all explicit flags -> one event; each absent consent/confirm flag denies, no JSON/env truthiness fallback. |
| E47 | MI-05 / test_cli.py | Bad last batch frame fails whole invocation with empty stdout; never earlier partial success; ambiguous/conflicting final result not emitted. |
| E48 | MI-05 / test_cli.py | validate-event returns bounded valid marker only; invalid versions/unknown fields/candidate event fail without echo. |
| E49 | MI-05 / test_cli.py | Missing file, denied access, URL, UNC, stdin, directory, symlink/reparse, FIFO/device rejected; regular opened-file/limit enforcement tested per OS. |
| E50 | MI-05 / test_cli.py | Exit0/2/3/4/130, invalid argparse, IO/parser/internal errors follow stdout/stderr limits; no stack/path/raw input. |
| E51 | MI-05 / test_cli.py | Broken pipe/interrupted IO never retries or emits traceback; injected partial-write failure nonzero. |
| E52 | MI-05 / test_cli.py | Module and entrypoint parity; --help/--version reflect installed version; shorthand has v2 validation. |
| E53 | MI-05 / test_cli.py | Preliminary wheel installed in fresh venv outside checkout with PYTHONPATH absent actually owns imports; passing editable install alone fails. |
| E54 | MI-05 / test_cli.py | Valid 21-point README examples run; existing v1 README example rejected with migration explanation. |
| E55 | MI-05 / test_cli.py | Event/report size bounds and exact closed fields; serializing uncertain report succeeds locally but cannot count as shared event. |
| E56 | MI-06 / test_catalog.py | Exactly four neutral base IDs map to all rules; each has provenance/licence/limits/version; no unsubstantiated reviewed status. |
| E57 | MI-06 / test_catalog.py | Malformed catalogue/duplicates/missing records/unknown version/unknown field fail, not empty/drop/overwrite. |
| E58 | MI-06 / test_catalog.py | Lookup returns detached/immutable data; modifying prior result cannot poison future sessions. |
| E59 | MI-06 / test_catalog.py | Named historical aliases documented, not enabled by default; evidence-free cultural-label activation rejected. |
| E60 | MI-06 / test_catalog.py | Label-pack review format includes reviewer/right/source/version/withdrawal; missing evidence remains blocked, not mock-approved. |
| E61 | MI-06 / test_catalog.py | English neutral copy has no medical/religious efficacy claim; actual human content review remains distinct from word filters. |
| E62 | MI-07 / test_privacy.py | Reject metadata/landmarks/raw image/path/URL/prose fields at every event nesting point; malicious extras not silently stripped as safe success. |
| E63 | MI-07 / test_privacy.py | Sentinel tests cover API/CLI/error/log/report channels; no old retained-data promise; imports do not infer identity/permission. |
| E64 | MI-07 / test_privacy.py | Runtime imports/startup/recognition/serialization produce no network, default files, telemetry or subprocesses; attempted-egress test must be caught. |
| E65 | MI-07 / test_fuzz.py | Three fixed seeds, >=10,000 bounded inputs each: parser/numeric/enum/length/state boundaries; fail/crash/timeouts retained as minimized synthetic regressions. |
| E66 | MI-07 / test_fuzz.py | Random valid sequences/property tests enforce stable prerequisites, confidence bounds, reset, no consent reuse and bounded memory; expected outcomes independent. |
| E67 | MI-07 / test_licensing.py | Empty/missing/malformed policy, missing core, unknown status/licence and absent NOTICE each fail. |
| E68 | MI-07 / test_licensing.py | Shipped file with absent inventory/wrong digest/missing licence coverage/pending asset fails; never auto-add permissive status. |
| E69 | MI-07 / test_mutations.py | All required semantic mutations in section3 cause named assertions to fail; import/syntax/setup failure cannot count as success. Each mutant run is capped at 90 seconds and the complete isolated mutation suite at 600 seconds. |
| E70 | MI-07 / test_privacy.py | 10,000-frame session run keeps <=N recent records, no retained point arrays; confirm/revoke/stop clears owned references (no zeroization claim). |
| E71 | MI-07 / test_verification_tools.py | Report output escapes synthetic diagnostics and removes private path fields; bounded output/timeouts kill owned child process tree and fail gate. |
| E72 | MI-07 / test_privacy.py | Threat-model checklist maps all public parse/API/import/output channels to actual negative tests; no global no-leak guarantee asserted. |
| E73 | MI-08 / test_distribution.py | Clean wheel/sdist builds, metadata checks, expected files only; exact licence, v2/language schemas, version maps, catalogue, typing data and three packaged language examples. |
| E74 | MI-08 / test_distribution.py | Wheel built from sdist offline imports outside repo, validates/renders all packaged language examples there, and has no editable/source-path fallback or runtime dependencies. |
| E75 | MI-08 / test_distribution.py | All 8 supported Linux/Windows x86_64 × Python 3.11–3.14 cells run required core tests/installed smoke without required skip/xfail; versions/digests retained. macOS is unsupported and outside this matrix. |
| E76 | MI-08 / test_distribution.py | OS/runner isolation is observed (Linux: no default route plus denied connect; Windows: a successful pre-rule connection control, an active canonical-interpreter-scoped outbound block, and a subsequent denied/timed-out connect), alongside the synthetic negative-egress probe; cold missing build dependency causes explicit setup failure. A Windows timeout qualifies only when both controls are present. Missing isolation is not a pass. |
| E77 | MI-08 / test_distribution.py | Two clean builds same environment produce same wheel/sdist hashes; any mismatch blocks, not normalize away unexplained content. |
| E78 | MI-08 / test_distribution.py | Actual artifact SBOM/inventory/notices and independent hashes agree; no unexpected bundled model/key/cache/raw corpus. |
| E79 | MI-08 / test_distribution.py | CI ignores no required failures, installs hash-pinned tools into a runner-temp environment outside the checkout, installs the package from local source without network/build isolation, verifies a clean dependency check, and has pinned actions/timeouts/permissions with no secrets for untrusted PR execution. |
| E80 | MI-08 / test_distribution.py | Stale source/tag/version/hash/evidence mismatch rejects release packet. |
| E81 | MI-08 / test_distribution.py | Windows path/encoding and POSIX regular-file checks tested on actual respective OS; simulated platform strings don't qualify. |
| E82 | MI-08 / test_distribution.py | Uninstall/reinstall exact wheel; version/schema/catalogue/language resources and module ownership stay consistent. |
| E83 | MI-08 / test_distribution.py | Dependent ALLYK consumer compatibility inventory records upgrade risk without exporting private sources or assuming automatic upgrade. |
| E84 | MI-08 / test_distribution.py | Gate report can be reproduced from frozen source/tool lock; the isolated verifier has a complete dependency closure; text identity is stable across LF/CRLF checkouts while binary identity remains byte-exact; mutable implementation and communication-language status ledgers do not stale product evidence; every release, acceptance and mutation subprocess receives only an allowlisted environment; absent required artifact/tool/platform blocks aggregation. |
| E85 | MI-09 / test_adapter_contract.py | DESIGN specifies asset pin/hash/licence and absence of core camera dependency; no implementation status fabricated. |
| E86 | MI-09 / test_adapter_contract.py | DESIGN state table covers start/deny/stop/revoke/late callback/device switch/hand loss/tab hide; queued result never silently accepted. |
| E87 | MI-09 / test_adapter_contract.py | DESIGN defines track identity/aspect/mirror/clock and no duplicate-frame hold bypass. |
| E88 | MI-09 / test_adapter_contract.py | DESIGN defines bounded latest-frame queue, model failure/offline/cold-cache handling, local-only telemetry and no BYOK probe. |
| E89 | MI-09 / test_adapter_contract.py | DESIGN lists real browser/quality/accessibility/cultural/asset proof still needed and alternative input path; never claims live evaluation. |
| E90 | MI-10 / test_release_recovery.py | Actual repository/publishing authority and protected, version-specific manual release authorization are required. Existing project: verify owner control and exact publisher. First publication: an authenticated owner-authorized pending Trusted Publisher must match project/repository/workflow/environment; 404 alone is insufficient, no name reservation is claimed, collision blocks, and successful creation/publisher identity must be checked after upload. The approved single-owner policy may use owner self-approval but is not independent review; missing/ambiguous authority blocks and no secret is stored in evidence. |
| E91 | MI-10 / test_release_recovery.py | Exact frozen candidate matches current source/spec/acceptance/tool-lock identity, all verified gates, offline qualification and exact artifact hashes before upload. |
| E92 | MI-10 / test_release_recovery.py | TestPyPI exact-version metadata and downloaded bytes match the frozen candidate; a fresh isolated install smoke passes; TestPyPI cannot stand in for production. |
| E93 | MI-10 / test_release_recovery.py | Production download and signed provenance match the tested artifact names/hashes, OIDC issuer, repository, exact candidate full source commit, workflow configuration/trigger and exact run/attempt. The PyPI Integrity API publisher assertion separately matches repository/workflow/production environment, and the candidate-commit workflow source binds that upload job to the declared environment and frozen files; environment is not claimed as a signed Fulcio extension. No rebuild/index fallback; fresh isolated install smoke passes. |
| E94 | MI-10 / test_release_recovery.py | Protected workflow uses pinned actions and separate environments; production requires a reviewer, permits the sole owner’s deliberate self-approval, disables administrator bypass, and allows only `main`; verifier rejects missing reviewers, self-review prevention, bypass, unrestricted/wrong branches; immutable release assets and documentation point to the exact candidate. |
| E95 | MI-10 / test_release_recovery.py | Synthetic ambiguous upload resumes only when existing hashes match; mismatch/version collision denies retry or overwrite. |
| E96 | MI-10 / test_release_recovery.py | Synthetic rollback/yank plan preserves published history and requires applicable authorization; never deletes user data. |
| E97 | MI-10 / test_release_recovery.py | Public quickstart/download links resolve to exact-version sources; observed live release/package state is recorded, no mock release acceptance. |
| E98 | MI-10 / test_release_recovery.py | Wrong publisher/repo/artifact/expired authorization or missing signing identity blocks; absent/malformed/wrong signed source-commit, workflow configuration/trigger or run/attempt claims block even when artifact digest and publisher assertion match. Wrong/missing publisher environment or candidate-workflow upload binding also blocks. A separate successful GitHub run is insufficient linkage. No long-lived secret fallback. |
| E99 | MI-10 / test_release_recovery.py | Gate aggregator rejects missing or stale external proof; final report separates published core, unimplemented adapter, and unverified accuracy/cultural claims. |

## 3. Required semantic mutations

Implement a small, auditable mutation runner; general mutation tooling is optional.
Each mutation must have an expected target/context hash and named asserting test.
Mutation did not apply, invalid syntax, import failure or test collection error
means mutation infrastructure FAILED. A mutation is detected only when its
intended wrong behaviour runs and the mapped assertion fails. Run baseline green
before/after, record counts, and prove the real source tree is byte-unchanged.

| Mutation | Required detecting cases |
| --- | --- |
| Default missing consent to true or use truthiness | E38, E46 |
| Allow rejected recognition to advance streak | E32 |
| Ignore duplicate frame ID/time | E33 |
| Remove hold-time condition | E31 |
| Reuse stale/revoked/consumed confirmation | E39, E40, E41 |
| Accept bool or non-finite coordinate | E11, E12 |
| Change contact <= to < | E21 |
| Skip image aspect conversion | E23 |
| Allow arbitrary metadata/additional properties | E62 |
| Ignore byte/depth limits or JSON duplicates | E15, E16 |
| Pass empty licence policy/missing asset | E67, E68 |
| Count skip/empty suite/stale receipt as pass | E04, E05, E80 |

## 4. Gate scopes and external evidence

M0 exercises the harness with disposable miniature programs/tests and validates
contract fixtures independently. It does not require missing runtime behaviours
to pass. M1 and later execute all prerequisite gate cases plus their owned cases.
Gate closure requires every item/case in that scope; pending later cases remain
NOT_STARTED. No skipped placeholder tests in the required core suite.

MI-09 verifies completeness/consistency of a DESIGN artifact. Its assertions
cannot establish real camera behaviour. M4 simulated failure recovery tests are
additional to actual TestPyPI/PyPI proof, not replacements. Missing accounts,
publishing identity, real platform access or authorization must stay BLOCKED.
Luna can still finish independent ready work; it cannot silently shrink the matrix.

Use injected clocks and bounded subprocess deadlines, not sleeps for stability.
The long-run/resource suite uses explicit workload sizes, wall limits and actual
exit status. No test duration, count or code-coverage percentage alone qualifies
the release. New failures need minimized regression cases and impact reruns.
