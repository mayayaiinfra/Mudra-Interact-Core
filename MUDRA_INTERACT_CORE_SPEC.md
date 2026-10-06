# Mudra Interact Core: Implementation and Release Specification

Status: proposed implementation contract for the public Apache-2.0 core
Version: 0.1
Owner: MAYAYAI

This document defines the work required to turn Mudra Interact Core from a
small landmark recognizer into a dependable, privacy-preserving protocol
library. It does not authorize a camera product, a clinical system, a cultural
authority, automatic actions, or a hosted service.

## 1. Product boundary

Mudra Interact Core accepts caller-supplied hand landmarks, evaluates a small
versioned catalogue of contact patterns, applies explicit uncertainty and
stability rules, and emits an image-free `MudraEvent`. The core must remain
offline-capable and deterministic for the same input, configuration, catalogue,
and clock abstraction.

The core must never:

- accept camera frames, microphone data, accounts, credentials, or network
  access;
- identify a person or infer health, emotion, religion, caste, ethnicity,
  intent, or sensitive traits;
- claim that a label is a fact about a participant or a tradition;
- distinguish culturally meaningful variants from landmark contact alone;
- retain or emit raw images or landmark arrays in a shareable event;
- execute an ALLYK or third-party action without a separate, human-reviewed
  application adapter.

Adapters may convert camera/video input to landmarks locally. An adapter,
model asset, dataset, UI, and downstream action integration are separate
deliverables with separate licences, threat reviews, and release decisions.

## 2. Normative data contracts

### 2.1 Landmark input

The public recognizer input is exactly 21 MediaPipe-order landmarks. Each point
has finite numeric `x`, `y`, and optional `z` values. The recognizer must reject
missing, non-finite, non-numeric, or incorrectly sized input. The caller owns
coordinate normalization; the core must document the expected coordinate
convention and reject a zero or near-zero wrist-to-middle-MCP scale.

The core must not silently accept extra points, reorder points, interpolate
missing points, or infer handedness. A future schema major version is required
for a different landmark topology.

### 2.2 Recognition

`Recognition` is versioned and contains:

- a bounded `gesture_id` from the catalogue or `unknown`;
- confidence in the closed interval `[0, 1]`;
- one of `candidate`, `stable`, `uncertain`, or `rejected`;
- the method and catalogue versions;
- bounded, non-sensitive observations and uncertainties.

Confidence is a recognition signal, not a probability of a person's identity,
belief, health, or intent. The implementation must preserve uncertainty instead
of coercing an ambiguous result to a named gesture.

### 2.3 MudraEvent

`MudraEvent` is the portable application boundary. It contains a schema version,
event ID, UTC occurrence time, direction, sender and recipient party types,
privacy mode, consent status, optional conversation/project references,
recognition, and bounded string metadata. It must explicitly report that raw
media and raw landmarks are not retained.

Human-originated events require explicit consent. Consent withdrawal must be
represented by the consuming application and must stop future capture and
sharing; the core must not invent historical deletion guarantees it cannot
perform.

### 2.4 Catalogue

`catalog/mudra_catalog.json` is a versioned, machine-readable catalogue. Each
entry must declare its ID, neutral contact description, uncertainty notes,
provenance, content licence, and whether it is safe for learning-only display.
The catalogue must not contain medical, therapeutic, religious-authority, or
guaranteed-benefit claims. A catalogue change requires a version bump and a
review record.

## 3. Recognition behaviour

The default implementation remains landmark-only contact rules plus a bounded
frame stabilizer. The following behaviour is required:

1. Normalize contact distances against a documented palm scale.
2. Reject invalid geometry before applying rules.
3. Return `candidate` for a supported contact pattern that still needs
   participant or contextual confirmation.
4. Return `stable` only after the configured number of compatible frames meet
   the minimum confidence and no conflicting gesture is observed.
5. Return `uncertain` for unsupported, conflicting, unstable, or insufficient
   observations.
6. Return `rejected` for invalid input, consent failure, policy denial, or a
   caller-requested stop; rejection must include a safe reason code without
   raw provider or device diagnostics.

Gyan and Chin must remain one ambiguous learning label unless an independently
reviewed orientation/context contract is added. No rule may infer a tradition,
belief, therapeutic result, or participant identity from contact points.

The stabilizer must expose reset semantics, bounded memory, deterministic
configuration, and tests for frame changes, low confidence, invalid input,
clock independence, and concurrent caller isolation.

## 4. Public API and compatibility

The package must expose a small typed Python API for:

- landmark parsing and validation;
- contact-feature extraction;
- recognition;
- stability promotion/reset;
- catalogue lookup;
- event construction and serialization.

CLI output is a stable JSON contract suitable for piping to another local
process. CLI errors must use non-zero exit codes, generic safe messages, and
must never print input paths containing secrets, raw frames, or arbitrary
exception traces.

The project must publish a compatibility table covering Python versions,
landmark schema version, event schema version, catalogue version, and CLI
flags. Breaking changes require a major schema or package version and an
explicit migration note. Unknown future fields must be ignored by readers when
safe; unknown major schema versions must be rejected.

## 5. Adapter boundary

An optional adapter package may later provide local camera/mobile/browser input.
It must be a separate package and repository directory from the core API, with:

- local-only processing by default;
- an explicit permission and capture indicator;
- no upload path in the default build;
- a documented model and asset licence;
- a bounded frame rate, memory budget, and shutdown path;
- landmark-only handoff to the core;
- tests proving that image bytes do not enter `MudraEvent` or logs.

MediaPipe, ONNX Runtime, OpenCV, model weights, and datasets remain optional
until their exact versions, notices, licences, hashes, and redistribution
rights are recorded. Non-commercial or unknown assets are blocked from a
public distribution.

## 6. Safety, privacy, and cultural review

Before adding labels or explanatory copy, maintain a catalogue review record
with the source, contributor, licence, cultural/domain reviewer, intended
learning interpretation, prohibited claims, and withdrawal process. The review
must distinguish a geometric contact pattern from its name or cultural meaning.

The library must provide a privacy statement describing local processing,
event-only mode, consent, retention responsibility, and the fact that the core
does not provide erasure of data held by a consuming application. Add a threat
model covering malicious landmark input, metadata injection, event replay,
cross-project confusion, denial of service, and accidental logging.

No event should contain a person's name, face, camera image, raw landmark set,
model prompt, credential, or unbounded user text. Metadata keys and values stay
bounded and are treated as untrusted strings.

## 7. Test and quality gates

The following gates define done for the core:

### M0 — Contract baseline

- JSON examples exist for valid, invalid, uncertain, stable, rejected, and
  consent-denied events.
- The landmark, recognition, event, and catalogue contracts are documented and
  tested.
- Serialization is deterministic apart from explicitly generated event IDs and
  timestamps.

### M1 — Recognition correctness

- Tests cover every catalogue rule, threshold boundaries, malformed geometry,
  conflicting contacts, scale invariance, and unsupported patterns.
- Stabilizer tests cover promotion, reset, frame changes, low confidence, and
  independent instances.
- Property tests prove confidence bounds and bounded identifiers/metadata.

### M2 — Privacy and safety

- Tests prove that raw media and landmarks cannot appear in event payloads,
  CLI output, exception output, or logs.
- Consent denial and rejected input fail closed.
- Fuzz tests cover JSON, numeric values, metadata, and oversized input.
- The licence allowlist and NOTICE check pass for every distributed component.

### M3 — Packaging and portability

- Build a clean wheel and source distribution from a clean checkout.
- Install and run the CLI in a fresh Python 3.11+ environment on Windows,
  Linux, and macOS, or document a supported-platform exception.
- Run the complete test suite without network access.
- Verify package contents, catalogue inclusion, reproducible version metadata,
  and absence of credentials or local paths.

### M4 — Release review

- Publish a changelog, signed or hash-addressable release artifact, SBOM, and
  dependency/licence report.
- Complete security, privacy, and cultural/domain review for changed labels or
  adapters.
- Confirm that the README claim boundary matches the implementation.
- Record an owner decision to release, defer, or reject each optional adapter.

Passing M0–M3 is engineering evidence only. It is not evidence of clinical,
religious, cultural, accessibility, or commercial efficacy.

## 8. Backlog

| ID | Work item | Dependency | Done when |
| --- | --- | --- | --- |
| MI-01 | Freeze landmark/event/catalogue schemas | none | Contract examples, version rules, and compatibility tests are merged. |
| MI-02 | Harden numeric and metadata validation | MI-01 | Non-finite, oversized, malformed, and hostile inputs fail safely. |
| MI-03 | Complete recognizer boundary tests | MI-01 | Rule, threshold, ambiguity, scale, and unsupported-pattern tests pass. |
| MI-04 | Complete stabilizer and concurrency tests | MI-03 | Reset, frame conflict, low-confidence, and instance-isolation tests pass. |
| MI-05 | Add safe CLI error/output contract | MI-01, MI-02 | Exit codes, JSON examples, redaction, and pipe tests pass offline. |
| MI-06 | Add catalogue provenance/review format | MI-01 | Every entry has provenance, licence, uncertainty, and prohibited-claim fields. |
| MI-07 | Add threat/privacy documentation and fuzz tests | MI-02, MI-05 | Threat model, privacy statement, fuzz corpus, and no-raw-data tests pass. |
| MI-08 | Clean build and supported-platform matrix | MI-02, MI-05 | Wheel/sdist install and offline tests pass on declared platforms. |
| MI-09 | Optional local adapter design | MI-06, MI-07 | Separate adapter spec, asset review, permission model, and no-upload proof exist. |
| MI-10 | Release packet | MI-06, MI-07, MI-08 | Changelog, SBOM, notices, hashes, security review, and owner decision are recorded. |

## 9. Explicit non-goals

This specification does not commit the project to a hosted recognition API,
cloud inference, biometric identification, medical or wellness guidance,
religious instruction, automatic ALLYK actions, a multimodal model, a public
camera application, or a commercial efficacy claim.
