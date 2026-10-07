# Mudra Core v2 wire contract

This document describes the target wire contract for package 0.2.0. It is not
a claim that the v2 runtime is implemented yet. The bundled schema source is
[`contract.schema.json`](../src/mudra_interact_core/schemas/v2/contract.schema.json);
it uses Draft 2020-12 and local `#/$defs/...` references. No schema lookup needs
network access. Schema validity does not establish frame freshness, stability,
participant consent, confirmation or downstream action authority.

## Frame

Each frame describes one selected hand in a single stream. Points are objects
with explicit finite `x`, `y` and `z` values, in MediaPipe landmark order:

```json
{
  "schema_version": "2.0.0",
  "stream_id": "123e4567-e89b-42d3-a456-426614174000",
  "frame_id": 1,
  "monotonic_ms": 100,
  "coordinate_space": "cartesian_relative_v1",
  "landmarks": [
    {"x": 0, "y": 0, "z": 0}
  ]
}
```

The example abbreviates the required landmarks array; a valid frame has exactly
21 points. Cartesian frames omit image dimensions. `mediapipe_image_v1` frames
include positive `image_width` and `image_height`; the core applies the declared
aspect conversion and does not guess coordinate systems.

## Recognition, event, batch and local report

Recognition uses a fixed neutral gesture ID, a rule score and enumerated
observation/uncertainty codes. It has no caller prose or measured distances. A
shareable event is a separate, closed object with schema version `2.0.0`,
explicit sender and recipient, both confirmation booleans set to true, a stable
recognition, and both `raw_media_included` and `raw_landmarks_included` false.
It has no metadata bag. The event flags describe the event payload; they do not
promise what a host or recipient retains.

A batch is `{ "schema_version": "2.0.0", "frames": [...] }`, with 1–256
frames in one stream and strictly increasing IDs and monotonic times. A local
report is `{ "schema_version": "2.0.0", "recognition": {...}, "reason_code":
null }`; it is not a shareable event and does not require a sharing grant.

The complete field lists and constraints live in the schema and normative
[specification](../MUDRA_INTERACT_CORE_SPEC.md). The example fixture files are
the complete, validated forms used by the contract tests.
