# Privacy boundary

Mudra Interact is a local, image-free protocol library. Its runtime has
no network client, telemetry, subprocess, persistence, model download or
camera access. A caller supplies already-normalized landmarks and receives a
detached recognition value. The core does not identify a person, infer a
sensitive trait, or attach prose, URLs, paths, media, raw landmarks or an
arbitrary metadata bag to an event.

The boundary is structural and finite:

- `Frame` accepts exactly 21 finite numeric points, bounded dimensions and a
  declared coordinate space. It copies values and rejects extra fields.
- `Recognition` contains only a neutral ID, bounded score, method, catalogue
  version and enumerated codes.
- `MudraEvent` is a separate `event_only` object with closed fields,
  `consent_confirmed=true`, `participant_confirmed=true`, explicit direction,
  and both raw-data flags false. It is emitted only after a current stable
  session revision is confirmed and the grant is consumed once.
- The CLI reads only one caller-selected local regular file. It rejects URL,
  stdin, UNC, symlink/reparse, directory, pipe and device inputs, bounds reads,
  and emits fixed error codes without paths, input or exception text.

These guarantees concern the object shape and core process. They do not promise
Python memory zeroization, crash-dump erasure, host retention behaviour,
absence of personal information in a caller-chosen UUID, or privacy of a
redirected output file. A camera adapter, UI, storage layer and embedding host must
perform their own consent, retention, access-control and telemetry review.

The privacy tests cover direct constructors, JSON import, event serialization,
session ownership, CLI output/error channels, and attempted runtime egress.
They intentionally do not claim that synthetic tests establish a universal
privacy property for every host embedding.
