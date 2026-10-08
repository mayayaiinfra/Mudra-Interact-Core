# Mudra Interact

Mudra Interact is an Apache-2.0, offline-capable Python library for two related
capabilities: a conservative image-free gesture/event protocol and an
experimental structured communication language for human-human, human-agent
and agent-agent workflows. Version `0.3.0` adds the language SDK while keeping
the established v2 gesture/event wire contract intact.

The release candidate is `mudra-interact==0.3.0`. Treat it as published only
after the [release runbook](docs/RELEASE_RUNBOOK.md) verifies the exact PyPI and
GitHub artifacts and the downloaded-install proof. The source push or a
successful CI run alone does not establish package availability.

- [PyPI project, version 0.3.0](https://pypi.org/project/mudra-interact/0.3.0/)
- [GitHub release, tag v0.3.0](https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.3.0)
- [Source repository](https://github.com/mayayaiinfra/Mudra-Interact-Core)

After publication is verified, install the exact package with no runtime
dependencies:

```powershell
python -m pip install --no-deps mudra-interact==0.3.0
```

The wheel includes three runnable synthetic language transcripts. This uses
the installed package resources, so it works outside a source checkout:

```python
from importlib.resources import files
from mudra_interact_core import render_message, validate_transcript

examples = files("mudra_interact_core").joinpath("examples", "language")
messages = validate_transcript(examples.joinpath("human-agent.json").read_bytes())
for message in messages:
    print(render_message(message))
```

For an owner-authorized TestPyPI candidate, select that index explicitly and do
not add PyPI as a fallback:

```powershell
python -m pip install --no-deps --index-url https://test.pypi.org/simple mudra-interact==0.3.0
```

## Communication language

The language API provides a bounded envelope, nine explicit acts (`request`,
`proposal`, `clarification`, `accept`, `decline`, `acknowledge`, `status`,
`result`, `error`), participant roles, versioned creative-planning intent,
modality provenance, transcript validation, freshness checks and deterministic
English text rendering. It can carry a planning conversation between people
and agents. Read the [language API and workflow](docs/COMMUNICATION_LANGUAGE_API.md)
and [migration notes](docs/MIGRATION.md) before adopting it.

The bundled examples show a human-to-human plan, a human request with agent
proposal and clarification, and an agent-to-agent plan. An application or
model can create candidate messages, then pass them to Mudra for structural
and transcript checks. Mudra itself does not call a model, provider, tool,
network, social platform or publishing API. The creative profile demonstrates
structured planning and review; it does not generate images or videos.

## Gesture interaction foundation

The v2 gesture/event protocol remains in the same package. It accepts normalized
21-point hand landmarks, reports bounded recognition states, and emits a
`MudraEvent` only after distinct-frame stability plus explicit consent and
confirmation. It has no camera capture or model assets.

- Strict parsing of landmarks, bounded JSON and protocol versions.
- Geometric contact rules with candidate, stable, uncertain and rejected
  states. Scores are heuristic, not calibrated probabilities.
- Explicit temporal stability and one-use event confirmation.
- A neutral catalogue, closed schemas, local CLI and reproducible wheel/sdist.

## Limits and integration boundary

Message validity is not identity, consent, authentication, permission or
authorization. An `accept` act is data and must not itself trigger execution.
Applications remain responsible for identity, transport security, replay
controls, consequential-action confirmation, retention and provider policy.
The package ships no A2A or MCP adapter, model integration, camera adapter,
host UI, hosted service, telemetry or private ALLYK implementation.

No human comprehension study, cultural review, accessibility qualification,
recognition accuracy study or independent security assessment is claimed.
Gesture labels do not assert universal, religious or cultural meanings.
ALLYK remains a private downstream consumer and must verify compatibility
before upgrading.

For the implemented surfaces, see [API](docs/API.md),
[communication-language API](docs/COMMUNICATION_LANGUAGE_API.md),
[compatibility](docs/COMPATIBILITY.md), [release runbook](docs/RELEASE_RUNBOOK.md),
and the [implementation ledger](IMPLEMENTATION_BACKLOG.json).
