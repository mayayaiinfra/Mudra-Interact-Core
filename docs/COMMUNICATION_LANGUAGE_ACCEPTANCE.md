# Mudra Interaction Language acceptance contract

Revision 0.1. Evidence for these cases is separate from the v2 gesture/event
acceptance IDs. Language reports use only `Lxx` identifiers and must never be
counted as M0–M4 or E90–E99 evidence.

| ID | Owner | Required outcome |
| --- | --- | --- |
| L01 | ML-01 / `tests/test_language_contract.py` | The committed synthetic manifest has one independently authored valid and invalid message for every one of the nine acts in each of the four sender-to-recipient role directions. All valid messages pass the closed v1 schema; all paired invalid messages fail it. Missing, duplicate, extra, path-escaping, symlinked, stale or hash-mismatched fixtures fail closed. |
| L02 | ML-01 / `tests/test_language_contract.py` | Unknown protocol versions, intent names/versions, acts and fields reject; schema references are local-only and a remote `$ref` is rejected; a mutated fixture cannot pass against its old manifest digest. |
| L03 | ML-01 / `tests/test_language_verification.py` | The language reporter rejects missing/unknown IDs, empty or incomplete collections, nonzero exit, skipped/xfail/xpass cases, duplicate nodes, stale source/spec/acceptance/lock/schema/fixture identity, missing/tampered pytest or command-log artifacts, unsafe evidence paths and a forged VERIFIED receipt. |
| L10 | ML-02 / `tests/test_language_runtime.py` | Every static valid act/direction fixture agrees across constructor, dict parser, byte parser, detached payload and deterministic serialization; immutable values reject mutation. |
| L11 | ML-02 / `tests/test_language_runtime.py` | Exact byte/depth/string/step-count boundaries, duplicate keys, BOM/UTF-8/trailing documents, bool/overflow numbers, Unicode scalars, controls and LF allowlist follow the contract. |
| L12 | ML-02 / `tests/test_language_runtime.py` | All positive and negative static fixtures use the runtime parser; payload, intent/version, participant identity, provenance mode and adapter-version constraints fail closed. |
| L13 | ML-02 / `tests/test_language_runtime.py` | Expiry equality, past expiry, 30/31-second future skew and import purity pass; core import has no network, process or authorization surface. |
| L20 | ML-03 / `tests/test_language_transcript.py` | The three checked-in creative-planning examples validate; complete transcript scope, unique IDs, reply graph, role consistency, reverse participants, intent, ordering, expiry, and whole-transcript failure are enforced. |
| L21 | ML-03 / `tests/test_language_transcript.py` | Each proposal accepts at most one accept-or-decline; revised proposals have independent IDs/dispositions; acknowledgements cannot loop, repeat, or extend expiry; status/result/error terminal relationships follow the contract. |
| L22 | ML-03 / `tests/test_language_transcript.py` | All acts render deterministically as literal plain text with explicit IDs, roles, provenance assertions, non-authorization language, visible bidi controls, and strict locale rejection. |
| L23 | ML-03 / `tests/test_language_transcript.py` | Malicious prose and spoofed claims remain data; validation/rendering trigger no network, subprocess or action; an invalid late item returns no partial transcript. |
| L30 | ML-04 / core M0-M3 evidence | All prior gesture/event regressions pass on a fresh eight-cell Linux/Windows x86_64 × CPython 3.11–3.14 matrix. The language release does not replace or weaken core cases; require current M0–M3 receipts and exact platform-matrix aggregate (core E73–E89). |
| L31 | ML-04 / `tests/test_distribution.py` | The 0.4.0 candidate wheel and sdist contain the exact closed language schema, version map, byte-identical three synthetic transcripts, and A2A adapter modules. A fresh wheel installed outside the checkout validates and renders every transcript and imports the adapter. Require zero runtime dependencies and OS-verified egress isolation (E73–E78, E82). |
| L32 | ML-04 / M4 and `tests/test_release_recovery.py` | The exact 0.4.0 candidate is qualified, published to TestPyPI and PyPI, downloaded and hash-checked, freshly installed and smoke-tested, with signed provenance, protected production authorization and immutable GitHub release verified by E90–E99. A CI pass or upload alone is insufficient. No completed creative host plugin or live model integration is claimed. |
| L40 | ML-05 / consented human study | Actual volunteers complete fixed comprehension, correction, clarification, refusal and alternative-input tasks across human-human, human-agent, agent-human and agent-agent examples. Record task-level denominators and critical misunderstandings; synthetic fixtures and model review do not count. |
| L41 | ML-05 / scoped reviewer report | Document tested locale, participant/reviewer scope, access supports, recruitment method, disagreements, deviations, remediation and retest results. Do not generalize beyond the tested population or call a small exploratory sample statistically representative. |
| L42 | ML-05 / claim review | Broad comprehension, suitability across communities and accessibility claims remain blocked unless scoped independent evidence supports each claim. Critical misunderstanding of identity, `accept`, action authority, or artifact completion blocks a positive claim until remediation and retest. |
| L50 | ML-06 / pinned adapter contract | Pin the A2A specification documentation snapshot `/v1.0.1` (which identifies protocol release 1.0.0), wire `A2A-Version: 1.0`, JSON-RPC-over-HTTP(S) binding, and the implementation choice. This adapter uses the standard library directly and has no SDK or runtime dependency; define message, context/task, identity, remote-interface tenant, host tenant, expiry, replay, cancellation, credentials and fixed-error mappings before implementation. Unknown versions, fields, extensions, and unauthenticated claims fail closed. |
| L51 | ML-06 / live integration evidence | Run the exact adapter over a real loopback HTTP socket against an independently implemented A2A JSON-RPC peer. Report path coverage for human-human, human-agent, agent-human and agent-agent; human-human must remain explicitly schema-only. Exercise identity, tenant scope, replay, stale messages, refusal, continuation, task cancellation, remote errors and deterministic injected provider failure. Unit mocks alone do not establish interoperability; paid provider use is neither required nor permitted for this gate. |
| L52 | ML-06 / authority boundary | Prove structural validity and import do not send network traffic; `accept` is never mapped to execution, provider invocation, account grant, payment, tool use or publication; `decline` does not invoke cancellation. Cancellation requires a separate explicit host call and is scoped to the returned task. |
| L53 | ML-06 / packaging and claims | The adapter is included in the candidate wheel and sdist, core install/import stays dependency-free, and unsupported bindings/extensions reject. Document the authenticated-host, durable-replay-store, TLS, clock, tenant, human-comprehension and third-party-agent limits; do not claim public A2A conformance or production-host qualification from the local peer. |

## Independent-fixture rules

Fixtures are checked-in synthetic inputs. The test suite may read the manifest
and validate its expected outcomes; it must not generate or repair expected
fixtures at runtime. Each manifest record names its case, role direction, act,
bundle file, JSON pointer, expected schema outcome, origin and SHA-256. The
expected outcome is authored independently of the schema validator and runtime
implementation. A failure discovered while implementing a validator is not a
fixture expected result unless the contract explicitly requires rejection.

The `L01` matrix is the Cartesian product of:

- Acts: `request`, `proposal`, `clarification`, `accept`, `decline`,
  `acknowledge`, `status`, `result`, `error`.
- Directions: `human_to_human`, `human_to_agent`, `agent_to_human`,
  `agent_to_agent`.
- Expected outcomes: one valid and one invalid message per pair.

Invalid paired messages differ from their valid counterpart by one unknown
top-level field. L02 owns separate negative fixtures for unsupported protocol
and intent identifiers; the test also injects an external `$ref` into a
disposable schema copy and requires the schema-reference policy to reject it.

## Reporter contract

The reporter requires a clean committed candidate before qualification. It
captures the exact Git commit, source-tree digest, communication contract,
acceptance contract, dependency lock, schema and fixture-manifest hashes before
running tests, then recomputes them afterwards. A change during the run fails
the run. A VERIFIED receipt must have a valid self-digest, exact item scope, all
owned and prerequisite IDs passing, zero skips/xfails/xpasses, nonzero
collection, and bounded pytest-report and command-log artifacts whose paths,
sizes and hashes validate. The receipt records
`verification_kind: luna_self_verified`; its self-digest provides integrity,
not an independent signature or human approval.

Run after committing the frozen candidate for each active item:

```text
python tools/verify_language_gate.py --item ML-01 --report evidence/language/ML-01.json
python tools/verify_language_gate.py --check-receipt evidence/language/ML-01.json
python tools/verify_language_gate.py --item ML-02 --report evidence/language/ML-02.json
python tools/verify_language_gate.py --check-receipt evidence/language/ML-02.json
python tools/verify_language_gate.py --item ML-03 --report evidence/language/ML-03.json
python tools/verify_language_gate.py --check-receipt evidence/language/ML-03.json
python tools/verify_a2a_gate.py --report evidence/language/ML-06-v0.4.0.json
python tools/verify_a2a_gate.py --check-receipt evidence/language/ML-06-v0.4.0.json
```

ML-06 has a separate verifier because it captures a live loopback HTTP peer in
addition to the synthetic language fixtures. It requires a clean committed
candidate and records the A2A and acceptance contract hashes, source tree,
pytest result for both the independent peer and receipt-checker tests, and
bounded command log. Its `luna_self_verified` receipt is
integrity-protected self-review, not an external A2A conformance certification
or human review.
