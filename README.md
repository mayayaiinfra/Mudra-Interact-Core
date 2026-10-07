# Mudra Interact Core

`Mudra Interact Core` is an Apache-2.0, offline-capable protocol library for
consented human and agent gesture interaction.

Canonical public source: [mayayaiinfra/Mudra-Interact-Core](https://github.com/mayayaiinfra/Mudra-Interact-Core).

Implementation and release work is tracked in the
[Mudra Interact Core specification](MUDRA_INTERACT_CORE_SPEC.md).

The source implements the package `0.2.0` and event schema `2.0.0` contract
through the strict API, geometry oracle, bounded session lifecycle, neutral
catalogue and installed CLI gates. The remaining ledger items cover privacy and
mutation proof, the full distribution matrix, adapter design and authorized
publication. Start with the [Luna handoff](docs/LUNA_HANDOFF.md),
[acceptance cases](docs/ACCEPTANCE.md), and
[implementation ledger](IMPLEMENTATION_BACKLOG.json).

```text
local camera or device landmark adapter
-> normalized 21-point hand landmarks
-> conservative recognition candidate
-> stability check
-> image-free MudraEvent
-> ALLYK or another compatible application
```

## What It Does

- Accepts 21 hand landmarks in MediaPipe order.
- Detects a deliberately small set of contact-pattern learning labels.
- Defines `candidate`, `stable`, `uncertain`, and `rejected` states; the revised
  specification requires stricter transitions and distinct-frame checks.
- Produces a portable `MudraEvent` for H-to-H, H-to-A, A-to-H, or A-to-A use.
- Defines an image-free event shape. The revision closes the current arbitrary
  metadata path and removes unsupported claims about host data retention.

## What It Does Not Do

- identify a person, infer sensitive traits, or make health decisions;
- claim therapeutic, religious, or cultural authority;
- upload camera media by default;
- distinguish Gyan from Chin from contact points alone;
- auto-execute an action in ALLYK or any other system.

## Development and CLI check

```powershell
git clone https://github.com/mayayaiinfra/Mudra-Interact-Core.git
cd Mudra-Interact-Core
python -m venv .venv
.venv\Scripts\python -m pip install -e . pytest
.venv\Scripts\python -m pytest -q
.venv\Scripts\mudra-interact.exe --input examples/v2/frame.json
```

On Linux/macOS use `.venv/bin/python` and `.venv/bin/mudra-interact`. The
acceptance tests exercise the v2 API/CLI and installed-package examples. A
candidate or stable local recognition is not authority to share participant
data or execute an action; event output requires both explicit CLI attestations.

The compact examples in [`examples/v2`](examples/v2) contain synthetic,
image-free 21-point frames. `frame.json` produces a local candidate report;
`batch.json` contains three distinct observations and can be stabilized into a
local stable report or an explicitly confirmed event.

An adapter, not the core, is responsible for converting camera/video input into
these landmarks. The intended browser/mobile adapter uses MediaPipe Hand
Landmarker locally. Its source is Apache-2.0, but the adapter, its model asset,
and every future model/data asset need their own release review.

## Licence Policy

The core itself is Apache-2.0. This release has no runtime third-party Python
dependencies. Future distributable components may be included only after their
code, model weights, dataset, and documentation licences pass the allowlist in
`licenses/approved_components.json` and are recorded in `NOTICE`.

The policy rejects non-commercial, source-available-only, unknown, and
unreviewed model or dataset licences. A permissive repository licence alone is
not sufficient.

## Safety And Cultural Boundary

The bundled catalog contains only constrained learning labels. Before shipping
expanded meanings, source texts, transliterations, mantras, or benefit claims,
the publisher must obtain cultural/domain review, provenance records, and an
appropriate content licence. A classifier result is a candidate interpretation,
not a fact about the participant or their beliefs.
