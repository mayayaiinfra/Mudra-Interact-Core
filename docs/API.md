# Mudra Core v2 wire contract

This document describes the gesture/event wire contract included in the
0.4.1 candidate (and first released in package 0.2.0). The
bundled schema source is
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

## CLI

The installed `mudra-interact` command is offline and reads exactly one caller
selected local regular file. It rejects URLs, `-`, UNC paths, directories,
symlinks/reparse points, pipes and devices. Input bytes are bounded before JSON
parsing; errors are one fixed JSON line on stderr and never include a path or
exception text.

```text
mudra-interact recognize --input examples/v2/frame.json
mudra-interact recognize --input examples/v2/batch.json --stabilize
mudra-interact recognize --input examples/v2/batch.json --stabilize \
  --emit-event --consent --confirm
mudra-interact validate-event --input event.json
```

Without `--stabilize`, the input is one v2 `Frame` and the result is a local
candidate report. With it, the input is a v2 `{schema_version, frames}` batch
and all frames are parsed before one `RecognitionSession` processes them. A
single frame remains non-stable. The report has exactly `schema_version`,
`recognition`, and `reason_code`; it is never a shareable event.

`--emit-event` is allowed only with `--stabilize`. The caller must supply both
`--consent` and `--confirm` flags for the selected batch. They are command-line
attestations, never values read from JSON or environment variables. A successful
event has closed v2 fields, explicit sender/recipient (defaults are human and
agent), and both raw-media flags set to false. `validate-event` only returns
`{"schema_version":"2.0.0","valid":true}` after strict event validation; it
does not reauthorize or echo the submitted event.

The CLI uses the same exit classes in every platform: 0 for valid output, 2 for
usage or validation input, 3 for consent/confirmation denial, 4 for local I/O,
platform or internal failure, and 130 for interruption. A caller owns any
retention caused by redirecting stdout; the core does not write files or retain
raw landmarks after recognition.

The 0.3.0 release introduced the experimental communication-language SDK. The
0.4.0 added an experimental A2A client; both remain separate from
gesture events. See the [communication-language API](COMMUNICATION_LANGUAGE_API.md).
The v2 gesture wire format does not contain or import language messages.
