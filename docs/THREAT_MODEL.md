# Threat model and evidence boundary

This document records the public-core threat surface. It is an engineering
review aid, not a security certification or a promise about an embedding host.

| Surface | Threat | Core control | Negative evidence |
| --- | --- | --- | --- |
| JSON/frame parser | Duplicate keys, non-finite numbers, deep or oversized input, coercion | Strict UTF-8 parser, closed fields, finite/bounded values, depth/byte limits | E11, E12, E15, E16 |
| Geometry/session | Replayed frames, rejected streak promotion, gap/clock abuse | Strict stream/frame/time watermarks, bounded deque, hold and confidence checks | E31–E35 |
| Consent/event | Default permission, stale or consumed grant, raw data in event | Exact booleans, revision binding, one-shot consumption, closed event | E38–E44, E62 |
| CLI filesystem | URL/UNC, symlink/reparse, pipe/device, path disclosure | Caller-selected regular-file handle, bounded read, fixed diagnostics | E49–E51, E63 |
| Runtime | Network, subprocess, default file or telemetry side effect | Standard-library offline core and import/startup probes | E64 |
| Resource use | Unbounded points, reports, fuzz input or subprocess | Byte/frame/depth caps, bounded recognition history, output/log limits and deadlines | E65, E66, E70, E71 |
| Distribution | Unreviewed or changed asset | Explicit SPDX policy, component statuses, byte inventory and NOTICE/hash checks | E67–E68 |
| Verification | Stale/tampered receipt or semantic regression | Sealed hashes, fresh identity checks and auditable mutation runner | E69, E71 |

The model excludes a malicious Python process with arbitrary memory access,
compromised operating systems, host data retention, camera model accuracy,
tradition-specific interpretation, accessibility quality, publisher account control and
host-specific integration. Those require their own design and release gates.

It does not assert universal privacy for every host embedding.

The public runtime does not probe for BYOK models or private capabilities. A
future adapter may call this core through the stable input/event contract only
after its own asset, permission, retention and accessibility review.
