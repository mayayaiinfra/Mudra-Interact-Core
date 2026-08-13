# Mudra Interact Core

`Mudra Interact Core` is an Apache-2.0, offline-capable protocol library for
consented human and agent gesture interaction.

Canonical public source: [mayayaiinfra/Mudra-Interact-Core](https://github.com/mayayaiinfra/Mudra-Interact-Core).

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
- Emits `candidate`, `stable`, `uncertain`, or `rejected` state rather than
  pretending every frame is certain.
- Produces a portable `MudraEvent` for H-to-H, H-to-A, A-to-H, or A-to-A use.
- Keeps raw images and landmark arrays outside the shareable event contract.

## What It Does Not Do

- identify a person, infer sensitive traits, or make health decisions;
- claim therapeutic, religious, or cultural authority;
- upload camera media by default;
- distinguish Gyan from Chin from contact points alone;
- auto-execute an action in ALLYK or any other system.

## Quick Start

```powershell
cd plugins\mudra_interact\core
python -m pip install -e .
mudra-interact --input sample_landmarks.json
```

`sample_landmarks.json` must contain a `landmarks` array of exactly 21 objects:

```json
{"landmarks": [{"x": 0.0, "y": 0.0, "z": 0.0}]}
```

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
