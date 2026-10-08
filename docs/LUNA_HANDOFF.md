# Luna implementation and self-verification handoff

Read in order: [specification](../MUDRA_INTERACT_CORE_SPEC.md),
[acceptance matrix](ACCEPTANCE.md), [ledger](../IMPLEMENTATION_BACKLOG.json).
This is the end-to-end public core delivery contract. The authoritative current
implementation state, active gate/item and verification evidence live in
`IMPLEMENTATION_BACKLOG.json`. Update that ledger at each gate completion; do
not duplicate volatile status here, where edits would change source identity.

The [2026-10-08 Astra technical review](ASTRA_REVIEW_2026-10-08.md) supplies
the original gesture/event foundation and release repair/qualification handoff.
The published `0.2.0` remains historical evidence for that bounded foundation.
Package `0.3.0` adds the separately reviewed experimental
[communication-language SDK](COMMUNICATION_LANGUAGE_CONTRACT.md) without
changing the v2 gesture/event wire contract. Qualify and publish that candidate
with fresh M0–M4 evidence; never reuse the 0.2.0 receipts for 0.3.0.

## 1. Working protocol

Use the existing primary checkout as the single development worktree for this
repository. Do not create linked Git worktrees or additional development clones.
Public Mudra Core and private ALLYK remain separate repositories, each with its
own existing checkout; this rule does not authorize merging their contents.

Only one task may edit a given checkout at a time. Before editing, establish
which task owns the active item; a clean Git status alone does not prove another
task is idle. If another task is writing, wait for its handoff. Preserve its
changes and never automatically stash, reset, clean, switch branches or stage
unrelated files to make room. Inspect the diff and stage explicit owned paths.
Finish the current checks/commit before handing the checkout to another task.
Freeze source edits during verification; any observed source change invalidates
the affected evidence and requires a rerun.

Disposable build/mutation copies without Git metadata, isolated virtual
environments and CI verification checkouts are permitted test infrastructure,
not additional development worktrees. Keep them bounded and owned as described
in section 5. Run them against a fixed candidate and never promote their edited
files into the development checkout. The single-worktree rule does not waive
independent installed-package checks or the required OS/Python matrix.

1. Inspect repository status, instructions and current ledger. Preserve unrelated
   edits. Do not copy private ALLYK code into this public repository.
2. Select the first NOT_STARTED item whose dependencies are VERIFIED; mark it
   IN_PROGRESS. One active item; no bypass based on apparent implementation.
3. Read its outputs and ALL owned acceptance cases. Write concrete expected
   outcomes before changing production code; use the fixed spec oracle.
4. Reproduce applicable baseline defects with a failing assertion. Implement
   the full item including public API, errors, docs and relevant fixtures.
5. Run the item's actual checks and impacted prerequisite tests. Fix failures,
   then perform a separate adversarial self-review using section 4 below.
6. Mark IMPLEMENTED only when code and required checks exist. Invoke the
   verifier; mark VERIFIED only from fresh complete passing evidence. Record
   `verification_kind: luna_self_verified` rather than claiming another reviewer.
7. Continue dependent items. At gate completion, run its aggregate checks,
   update ledger/evidence/docs, commit coherent changes and push under the user's
   existing authorization. Report exact passes, failures/limits and next gate.
8. Continue until M4's actual published-artifact acceptance passes, or name a
   concrete external blocker/required decision. Do not stop after just source,
   tests, a wheel, a source push, a TestPyPI upload or an adapter design.

Do not ask after routine components. Do not fabricate authorizations or account
access. Credential/account setup, unavailable runner infrastructure, new spending
or real cultural/accessibility review may need the owner; ask with the precise
missing fact after preparing everything independently possible. Reuse approvals
that already cover the action. Changing the agreed privacy/consent/schema/release
contract requires Astra review; ordinary fixes within it do not.

## 2. Concrete dependency order and files

| Item | Build these outputs | Required proof before next item |
| --- | --- | --- |
| MI-01 | Package-bundled schemas/v2; synthetic committed fixture manifest; docs/API.md + MIGRATION.md; bootstrap requirements-dev.lock/.gitignore; tools/verify_gate.py; tools/verification_report.py; pytest acceptance-ID reporter; tests/test_contract_spec.py and test_verification_tools.py | E01-E06 prove closed contract and verifier failure handling independently of unfinished runtime. |
| MI-02 | validation.py + errors.py; strict protocol constructors/parsers; frame.py; bounded JSON parser; immutable value handling | E10-E19, including actual earlier coercion/consent-path regressions applicable to this layer. |
| MI-03 | coordinates.py, reviewed recognition.py and local feature extraction; fixed code enums/rule table | E20-E26; independent eight-row oracle and aspect-ratio comparison. |
| MI-04 | session.py; bounded temporal stabilizer; consent grant and event factory; v2 event parsing/serialization; exported typed API | E30-E44; direct low-level calls cannot promote rejected input or bypass factory state. |
| MI-05 | cli.py command/error/batch/event flow; valid examples/v2; README/API usage; preliminary wheel smoke helper | E45-E55 on actually installed package; no reliance on PYTHONPATH/source imports. |
| MI-06 | catalogue2.0 neutral records; robust catalogue loader; historical-alias migration; docs/CATALOG_REVIEW.md with explicit unverified named labels | E56-E61; do not invent provenance or human review. |
| MI-07 | privacy/threat docs; licensing inventory validator; fuzz/resource/mutation tests; tools/run_mutations.py; safe evidence sanitization | E62-E72 and all selected semantic mutations. |
| MI-08 | locked/hash-pinned dev tools; pyproject/package data; .gitignore; build/install/reproducibility tools; CI matrix; SBOM/provenance; tools/verify_release.py; tools/aggregate_platform_matrix.py; docs/COMPATIBILITY.md | E73-E84 and all 8 supported Linux/Windows x86_64 × Python 3.11–3.14 cells, offline/install/source identity proved. macOS is explicitly unsupported and is not represented by Linux evidence. E76 must observe Linux network-namespace isolation or a successful Windows pre-rule control plus an active block for the executable image reported by `GetModuleFileNameW`, followed by a denied/timed-out connect. Windows CI separately checks that pytest still runs from the isolated venv (`sys.executable`); the venv launcher path is not assumed to be the process image path. A timeout qualifies only after both Windows controls pass. Each runner logs its sanitized item receipt and acceptance artifact, and the matrix aggregator rejects missing, stale, duplicate or failed cells. |
| MI-09 | docs/ADAPTER_SPEC.md with state table, interfaces, resource limits and future live-proof requirements; tests/test_adapter_contract.py | E85-E89 verify DESIGN only; camera runtime remains separately unimplemented. |
| MI-10 | CHANGELOG.md, SECURITY.md, release/recovery runbook; protected publish workflow; authorized TestPyPI/PyPI/GitHub release and downloaded install receipts | E90-E99, actual external publication proof plus synthetic failure-recovery tests. |

Dependencies are machine-readable in the ledger. MI-06 follows MI-03; until
then MI-03 may use the frozen neutral contract fixtures without falsely
declaring the runtime catalogue release-ready. MI-05 depends on MI-06 so CLI
output uses the validated catalogue. MI-08 needs all M2 results. MI-09 is design
work and may proceed when MI-06/MI-07 are verified; it never adds a runtime
dependency that defeats the offline core.

Update __init__.py exports and package type marker with the new API. Keep the
runtime dependency-free. Do not introduce unrelated framework/model migrations.
Generated schema files must be deterministic, checked in, and validated against
runtime behaviour and independent examples. Decide one schema source of truth
in MI-01; generated expected test outcomes are forbidden.

MI-01 pins and hashes the bootstrap test/schema/report tools in requirements-dev.lock
so its own evidence has a real tool-lock identity. Extend the same lock in MI-08
for the complete build/publication toolchain; do not postpone reproducible M0
test setup until M3. Each changed lock needs impact reruns. Tests may build a
preliminary wheel in MI-05; that is not the M3 distribution certification.

## 3. Required verifier command contract

These tools are TO BE IMPLEMENTED. Their absence at baseline is not a pass.
MI-01 implements gate/report collection; MI-08 extends package/platform release
checks. Both read the ledger but independently execute checks and validate
receipts. A hand-edited status or claimed count must not produce success.

```text
python tools/verify_gate.py --item MI-01 --report evidence/local/MI-01.json
python tools/verify_gate.py --gate M0 --report evidence/local/M0.json
python tools/run_mutations.py --report evidence/local/mutations.json
python tools/verify_release.py --offline --report evidence/local/candidate.json
python tools/verify_release.py --published --report evidence/local/published.json
```

--item runs all owned IDs and validates prerequisite receipts/identity.
--gate aggregates every required item through that gate, reruns impacted tests
and requires actual executed IDs. It never uploads/publishes. The offline
release mode verifies the M0-M3 candidate and reports `candidate_verified`,
NOT `published`. The published mode additionally verifies exact remote package
identity and M4 receipts; it performs read-only downloads/verification, never
automatically uploads or modifies the ledger. Publication is a separate explicit
release workflow under existing or newly recorded authorization.

CI may rerun a `VERIFIED` item for fresh platform evidence after `active_item`
has advanced. An item that is not yet verified must still match the active item
selection, and an `IN_PROGRESS` item must remain the active item.

The normal `push`/PR workflow qualifies each MI-08 platform cell. After all
eight current-source receipts and the aggregate matrix report are committed,
dispatch `.github/workflows/verify.yml` to execute the complete M3 gate on an
isolated Ubuntu runner. The manual job runs the gate against the committed
matrix and prerequisite receipts inside a network namespace, fetches full Git
history for receipt ancestry validation, and emits a sanitized gate report plus
its linked pytest evidence. This avoids treating a local WSL namespace
limitation or an unelevated desktop firewall as evidence.

Every runner returns zero only for its declared successful scope. Nonzero means
FAILED or BLOCKED, with safe error code and missing conditions. Timeout, signal,
missing executable, empty/truncated/malformed result, absent required ID, skip,
xfail/xpass, changed source, or missing required platform prevents success.
The runner must collect failures instead of allowing a later passing command
to overwrite the earlier exit status. Shell command chaining must stop/aggregate
correctly; process creation is not completion. Await jobs and inspect their final
exit codes. Never delete artifacts from a still-running build.

Reports contain: report_schema_version, scope, state, verification_kind,
source_commit, source_tree_sha256, spec_sha256, acceptance_sha256, tool_lock_sha256,
platform (OS/architecture/Python build), started_at/finished_at, commands,
test_counts, acceptance_cases (actual nodes/outcomes), mutation_results,
artifact path/hash/size references, prerequisites and limitations. Distinguish
local synthetic, actual-OS installed, offline-isolated and published evidence.
No fabricated reviewer field. Store complete bounded local logs; commit only
safe synthetic summaries/fixtures. Reject receipts whose files no longer hash.

The source-tree digest includes tracked product code, tests, fixtures, schemas,
build configuration and normative docs; exclude the mutable implementation and
communication-language status ledgers, evidence output and ignored build/cache
directories. Status-only commits refer to the qualified candidate commit.
Changing code, tests, contract or tool locks invalidates affected receipts;
dependency impact must be recomputed and needed gates rerun. Editing acceptance
to ease a failure is a contract change, not a fix.

A fixture/header checker does not prove behaviour. Run assertion tests, enumerate
parametrizations and retain results. The verifier itself has failure-injection
tests E04-E06/E71. Test suites must not conditionally silently omit required
tests based on available modules, OS or credentials.

## 4. Separate adversarial self-review after each item

Without editing expected results, inspect changed entry points and ask:

- Can direct constructor/API calls bypass the parser or session checks?
- Can booleans, NaN, huge integers, strings, duplicate keys or Unicode reach
  geometry/serialization through a different path?
- Can a rejected/stale/duplicate result become stable, or can wall-time changes
  bypass monotonic hold/expiry checks?
- Can a scope change, event import, same-frame reconfirmation or revoked grant
  authorize a new emission? Can mutable originals modify a stored result?
- Do IO/internal/argument errors leak input, paths or arbitrary exception text?
- Do tests derive expectations from the same implementation they are checking?
- Can zero collected tests, a missing test module or a skip be mistaken for pass?
- Did the wheel import source checkout files, fetch a dependency online or omit
  package data? Is evidence for a different source/version/platform?
- Did a pending asset/reviewer decision become approved merely through a flag?
- Did an upload rebuild/mutate the accepted artifact, or retry an unknown result?

Record findings and fixes with acceptance IDs. All actionable failures need a
regression and appropriate rerun. A prose checklist with no execution is not
VERIFIED. Required semantic mutations prove key guards are actually exercised;
full absence-of-bugs, security certification or recognition accuracy is not claimed.

## 5. Safe execution, evidence and completion reporting

Use a dedicated .venv and owned ignored build/evidence scratch paths. Pin/hash
setup dependencies; don't modify global Python to satisfy a tool. Separate
dependency download from offline testing. Full platform runs may use approved
CI access; no new billing/host purchase is implied by this plan.

Before deleting a disposable test/mutation tree, resolve the absolute target,
check it is beneath the intended scratch root and contains the expected ownership
marker, reject reparse points/links, and use one native shell/API end-to-end.
Never use broad clean/reset, delete a computed repository root, or modify
unrelated work. A blocked cleanup is a reported problem, not a reason to bypass
approval/tool policy through another primitive.

Every gate update to the user states: gate/item IDs, source/artifact identity,
actual check results and skips, discovered/fixed defects, commit/push status,
remaining limits and next dependency. State explicitly if no package was
published. Final completion requires VERIFIED M0-M4, exact release URLs/hashes
and fresh installed download proof. Adapter implementation/accuracy/cultural
approval stay separately unclaimed. Missing external proof keeps M4 BLOCKED
while all achievable local engineering work is preserved.
