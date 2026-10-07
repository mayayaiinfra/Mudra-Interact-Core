# Local camera adapter contract — DESIGN

**Status: DESIGN ONLY.** This document specifies a future local browser or
native adapter around Mudra Interact Core. It does not implement camera
capture, ship a model, grant device permission, or claim browser, quality,
accessibility, cultural, or licensing proof. No camera dependency is added to
the public core package. A real adapter remains a separate ALLYK or consumer
integration and must pass the proof listed at the end of this document.

## Boundary and responsibilities

The public core accepts bounded, caller-owned landmark frames and returns a
neutral recognition result. The adapter owns the capture device, model
runtime, permission surface, coordinate transform, cancellation and its local
resource lifecycle. The adapter must never reach into core internals or turn a
camera frame into an event without the core session, explicit consent and
editable confirmation checks.

The adapter-to-core boundary is a versioned local message with these fields:

| Field | Requirement |
| --- | --- |
| `adapter_contract_version` | Exact adapter contract version; reject unknown major versions. |
| `session_id` | Fresh opaque session identifier; never a person or device identifier. |
| `track_id` | Fresh monotonic hand-track generation; changes on device/track switch. |
| `frame_sequence` | Strictly increasing integer within one track; duplicates and regressions are rejected. |
| `capture_time_monotonic_ns` | Monotonic capture clock; wall time is metadata only. |
| `viewport` | Positive width/height, rotation and mirror state; validated before conversion. |
| `landmarks` | Bounded finite normalized points copied into a core `Frame`; no image bytes. |
| `model_revision` | Pinned local model/asset revision; never inferred by a network probe. |
| `consent_generation` | Current consent generation; stale callbacks cannot enter a session. |

Only normalized landmark data crosses this boundary. Images, encoded frames,
audio, account identifiers, API keys and model weights stay within the local
adapter process and are never telemetry payloads.

## Assets and licensing

An implementation must check in an asset manifest before it can be enabled.
The manifest is part of the adapter release candidate, not this core package.
Every asset is pinned by immutable upstream reference and digest:

| Asset record | Required value |
| --- | --- |
| `asset_id` and semantic version | Stable identifier and non-floating version. |
| Source URL and commit/tag | Auditable upstream origin; no `latest` or mutable download. |
| SHA-256 digest and byte size | Digest checked before load and retained in the release receipt. |
| SPDX licence and NOTICE text | Licence permits the intended distribution and use; notice is shipped. |
| Model/data scope | Training-data and model-weight terms are recorded separately from code terms. |
| Review state | `pending`, `approved`, `withdrawn`; only `approved` can activate. |

The public core distribution contains no camera model, native capture library,
browser bundle or raw corpus. MediaPipe, ONNX, OpenCV or any other optional
component needs its own pinned hash and licence review. A repository licence
does not approve model weights or training data.

## Consent and lifecycle state machine

The adapter exposes visible Start, Stop and Revoke controls. Start requests
permission and creates a new `session_id`, `track_id` and consent generation;
it never starts from a hidden callback, JSON flag, environment variable or
truthy value. Revoke is stronger than Stop: it invalidates callbacks and drops
all queued frames/results owned by that generation.

| Current state | Trigger | Guard and transition | Queue/result rule |
| --- | --- | --- | --- |
| `idle` | Start | Visible user action + permission + approved asset -> `running`; denial -> `denied`. | No capture or queued work before success. |
| `idle` | Hidden callback | No active generation -> stay `idle`. | Ignore callback; never implicitly start. |
| `denied` | Start again | Visible retry may request permission again -> `running` or `denied`. | Clear any stale error; no frame is accepted. |
| `running` | Frame | Consent generation, track, sequence, clock and geometry all current -> enqueue latest bounded frame. | Reject duplicate/regressed identity; never bypass hold with a duplicate. |
| `running` | Stop | User action or lifecycle hide -> `stopped`; cancel capture and invalidate callback generation. | Drop queued frames and pending results. |
| `running` | Revoke | User revokes consent -> `revoked`; cancel, clear references and require a new Start. | Late result is discarded, never emitted or reauthorized. |
| `running` | Device/track switch | Track identity changes -> `rearming`; reset stabilizer and queue, then neutral `running`. | Old-track callbacks cannot enter new track. |
| `running` | Hand loss | No selected hand or confidence below policy -> `hand_lost`; reset hold. | Do not repeat the last stable gesture. |
| `running` | Tab/app hidden | Visibility loss -> `stopped` (or explicit platform pause state). | Capture is stopped; queued work is discarded. |
| `rearming`/`hand_lost` | Fresh valid frame | New identity and explicit current consent -> `running`. | Start a new hold; no prior result is reused. |
| Any non-running state | Late model callback | Generation, track and frame identity mismatch -> terminal discard. | No event, report or telemetry is produced. |

State transitions are serialized by one lifecycle owner. A cancellation token
and generation counter are checked before model invocation, after model
completion and immediately before handing a frame to core. Queue capacity is
fixed (recommended maximum two entries). Enqueue replaces an older pending
frame only when it is from the same current generation; otherwise it rejects.
There is no unbounded promise, task or image queue. Stopping or revoking
drops queued frames, and a duplicate or regressed identity is rejected. A
duplicate-frame hold bypass is forbidden.

## Geometry, identity and time

The adapter records the input viewport, camera sensor orientation and explicit
mirror flag. It converts points to the core normalized coordinate convention
once, using the selected hand and the same aspect-ratio policy for every
frame. A front-camera preview mirror is a display transform; it is not silently
applied to core coordinates. The final transform, rotation and mirror value
are retained in the local qualification receipt.

The duplicate guard is the tuple `(consent_generation, track_id,
frame_sequence, capture_time_monotonic_ns, model_revision)`. Frame sequence
and monotonic time must advance; wall-clock changes cannot extend a hold or
make an old callback current. A model result carries the exact tuple it
processed. Core stability, freshness and gap rules remain authoritative.

## Failure, offline and accessibility behaviour

* Permission denial returns a neutral local error and keeps the adapter in
  `denied`; it never retries invisibly.
* Model load failure, a corrupt digest or a missing approved asset leaves the
  adapter unavailable and offers the non-camera path. It never downloads a
  replacement in the background.
* Offline or cold-cache operation is expected. The adapter either uses the
  already verified local asset or reports `offline_unavailable`; it does not
  probe a provider, BYOK key, DNS endpoint or remote model to decide whether a
  feature exists.
* Capture, inference and queue errors are bounded, synthetic-safe codes. No
  image, point array, path, token or exception text enters telemetry.
* A keyboard/pointer or imported landmark-file path must expose the same
  consent, confirmation, timing, accessibility and privacy semantics. It is
  an alternative input path, not a bypass around the camera state machine.
* Confirmation is editable and visible. The adapter presents the final neutral
  recognition for user confirmation; only the core event factory may emit a
  sharing event after its consent and confirmation checks.

Telemetry, if enabled by an explicit local policy, contains counters and
fixed error codes only. It is disabled by default, never sends images or
  landmarks, and has no implicit network or BYOK capability probe.

## Required proof before implementation status changes

The following evidence is still required and cannot be manufactured by this
design document:

1. Browser/device permission tests on the supported browsers and operating
   systems, including visible start, stop, revoke, tab hide and device switch.
2. Real model inference with pinned asset bytes, hash verification, cold-cache
   and offline runs, hand-loss and model-failure recovery, and bounded queue
   measurements.
3. Aspect-ratio, rotation, mirror and monotonic-clock tests using real capture
   tracks; duplicate and late-callback races must fail closed.
4. Keyboard/pointer alternative flow, screen-reader labels, focus order,
   reduced-motion behaviour and an accessibility review with representative
   users.
5. Cultural and language review for any optional label pack, including rights,
   tradition scope, prohibited claims and withdrawal records.
6. Independent asset and model/data licence review, security/privacy review,
   and a real integration smoke against the installed public core wheel.

Until those artifacts exist, the adapter remains DESIGN, the camera
runtime remains unimplemented in this public repository, and no recognition
accuracy or cultural approval is claimed.
