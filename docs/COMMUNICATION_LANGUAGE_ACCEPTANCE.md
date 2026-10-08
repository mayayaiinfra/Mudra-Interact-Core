# Mudra Interaction Language acceptance contract

Revision 0.1. Evidence for these cases is separate from the v2 gesture/event
acceptance IDs. Language reports use only `Lxx` identifiers and must never be
counted as M0–M4 or E90–E99 evidence.

| ID | Owner | Required outcome |
| --- | --- | --- |
| L01 | ML-01 / `tests/test_language_contract.py` | The committed synthetic manifest has one independently authored valid and invalid message for every one of the nine acts in each of the four sender-to-recipient role directions. All valid messages pass the closed v1 schema; all paired invalid messages fail it. Missing, duplicate, extra, path-escaping, symlinked, stale or hash-mismatched fixtures fail closed. |
| L02 | ML-01 / `tests/test_language_contract.py` | Unknown protocol versions, intent names/versions, acts and fields reject; schema references are local-only and a remote `$ref` is rejected; a mutated fixture cannot pass against its old manifest digest. |
| L03 | ML-01 / `tests/test_language_verification.py` | The language reporter rejects missing/unknown IDs, empty or incomplete collections, nonzero exit, skipped/xfail/xpass cases, duplicate nodes, stale source/spec/acceptance/lock/schema/fixture identity, missing/tampered pytest or command-log artifacts, unsafe evidence paths and a forged VERIFIED receipt. |

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
the run. A VERIFIED receipt must have a valid self-digest, exact ML-01 scope,
all required IDs passing, zero skips/xfails/xpasses, nonzero collection, and
bounded pytest-report and command-log artifacts whose paths, sizes and hashes
validate. The receipt
records `verification_kind: luna_self_verified`; its self-digest provides
integrity, not an independent signature or human approval.

Run after committing the frozen ML-01 source:

```text
python tools/verify_language_gate.py --item ML-01 --report evidence/language/ML-01.json
python tools/verify_language_gate.py --check-receipt evidence/language/ML-01.json
```
