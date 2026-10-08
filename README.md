# Mudra Interact

Mudra Interact is an Apache-2.0, offline-capable Python library for a
conservative, image-free gesture interaction protocol. It accepts normalized
21-point hand landmarks, reports bounded recognition states, and emits a
`MudraEvent` only after distinct-frame stability plus explicit consent and
confirmation.

This release is `mudra-interact==0.2.0`. The [release runbook](docs/RELEASE_RUNBOOK.md)
defines the evidence required before treating a published artifact as verified.
Check the exact-version pages and artifact digests before installing; a missing
package page alone does not prove that its name is available or authorize
claiming it. First publication may use an owner-authorized pending Trusted
Publisher as described in the runbook.

These exact-version pages are the distribution sources:

- [PyPI project, version 0.2.0](https://pypi.org/project/mudra-interact/0.2.0/)
- [GitHub release, tag v0.2.0](https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.2.0)
- [Source repository](https://github.com/mayayaiinfra/Mudra-Interact-Core)

After publication is verified, install the exact release and run the synthetic
example from a source checkout (the examples are repository fixtures):

```powershell
python -m pip install --no-deps mudra-interact==0.2.0
git clone --branch v0.2.0 --depth 1 https://github.com/mayayaiinfra/Mudra-Interact-Core.git
Set-Location Mudra-Interact-Core
mudra-interact --input examples/v2/frame.json
```

On Windows, use `mudra-interact.exe` if the scripts directory is not on PATH.
The runtime has no third-party Python dependencies; `--no-deps` prevents an
unreviewed dependency from being pulled into the environment.

For an owner-authorized TestPyPI candidate, select that index explicitly. Do
not add PyPI as an extra index fallback:

```powershell
python -m pip install --no-deps --index-url https://test.pypi.org/simple mudra-interact==0.2.0
```

TestPyPI may not host runtime dependencies required by another package; this
library has none. A successful source push or GitHub Actions run does not mean
the package is available. Check both exact-version pages and verify the
published artifacts before following these commands.

## What it provides

The longer-term direction is a communication language for human-human,
human-agent and agent-agent interaction. This release supplies the gesture/event
foundation only. The [reviewed follow-on design](docs/COMMUNICATION_LANGUAGE_CONTRACT.md)
is not implemented or claimed as language, creative-plugin, MCP or A2A support
in `0.2.0`.

- Strict validation for MediaPipe-order 21-point landmarks, bounded JSON and
  protocol versions.
- A small geometric rule oracle with explicit candidate, stable, uncertain and
  rejected states; scores are heuristic and are not calibrated probabilities.
- Distinct-frame temporal stability, scope-bound consent and one-use event
  confirmation.
- A neutral catalogue, closed schemas, local CLI and reproducible wheel/sdist.
- Image-free events that can be consumed by ALLYK or another compatible client.

## What it does not provide

- Camera capture, browser UI, model downloads, hosted services or remote
  inference. A local camera adapter is designed separately and is not
  implemented in this package.
- Identity, sensitive-trait or health inference; therapeutic, religious or
  cultural authority; or an automatic action in ALLYK.
- A claim of state-of-the-art recognition accuracy, independent user research,
  accessibility qualification or human cultural review.
- A way to distinguish Gyan from Chin using contact points alone.

The intended data path is:

```text
local device adapter -> normalized landmarks -> conservative candidate
-> temporal stability and explicit confirmation -> image-free MudraEvent
-> ALLYK or another compatible application
```

For the contract and integration boundary, see [API](docs/API.md),
[migration notes](docs/MIGRATION.md), [support matrix](docs/COMPATIBILITY.md),
and the [release runbook](docs/RELEASE_RUNBOOK.md). Implementation and
verification status is tracked in the [backlog ledger](IMPLEMENTATION_BACKLOG.json)
and [acceptance contract](docs/ACCEPTANCE.md).

## Development check

Use the locked verification dependencies and run the applicable acceptance
gate. See [Luna handoff](docs/LUNA_HANDOFF.md) for the repository verification
rules. The checked-in synthetic examples contain no camera frames or user data.

## Licensing and cultural boundary

The core is Apache-2.0 and ships `LICENSE` and `NOTICE`. Runtime dependencies
are empty. Optional adapters, model weights, datasets and expanded meanings
need their own source, licence, provenance and domain review before inclusion.
The bundled catalogue contains constrained learning labels only; it does not
establish cultural or religious interpretation.
