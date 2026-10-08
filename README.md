# Mudra Interact

Mudra Interact is an open, vendor-neutral Apache-2.0 Python SDK for structured
communication between people and AI agents, with an offline gesture-event
protocol in the same package. Its experimental communication-language SDK
provides a shared, versioned JSON contract, deterministic validation, transcript
and freshness checks, and readable rendering for human-to-human,
human-to-agent, and agent-to-agent workflows.

As software moves from standalone assistants toward teams of agents, messages
need to travel across products, models, and providers without losing their
meaning. Prompts and vendor-specific payloads do not give an independent
receiving application a dependable way to check who sent a message, what kind
of response it represents, which earlier message it answers, or whether it has
expired. Mudra makes those details explicit in a bounded, versioned record that
each application can validate locally. The record names participants; it does
not authenticate them. That gives people and software a common
starting point for reviewing, routing, and carrying structured work across
systems, without requiring a shared model, provider, or hosted service.

The value is the interoperability contract: applications can exchange a
validated request, proposal, clarification, decision, or result while keeping
their own models, tools, identity systems, and user experience. The same
message structure works for person-to-person, person-to-agent, and
agent-to-agent conversations. This is useful now for experiments and controlled
integrations, and provides a foundation for future multi-agent workflows as
more compatible applications adopt it. Mudra is a protocol library, not a
model, hosted service, chat interface, or adopted industry standard; useful
interoperability depends on independent applications choosing to implement the
contract.

Install from PyPI:

```powershell
python -m pip install mudra-interact
```

## Structured communication

The language defines nine acts (`request`, `proposal`, `clarification`,
`accept`, `decline`, `acknowledge`, `status`, `result`, and `error`), participant
roles, versioned intent, modality provenance, transcript checks, freshness
validation and deterministic English rendering. Its creative-planning profile
structures plans and reviews; it does not create media.

Applications can use their own model or other tools to draft messages, then
validate the resulting data with Mudra. The communication-language core does
not call an LLM, provider or tool. Version 0.4.0 adds an experimental A2A 1.0
JSON-RPC client for human-to-agent and agent-to-agent sends and replies. It
uses the Python standard library and sends only when the host calls it with a
configured endpoint and authenticated scope; there are no background or
implicit network requests. The host must provide authenticated principal and
tenant context, a trusted clock, credentials when required, and an atomic
durable replay store. Human-to-human remains schema-only; no user interface,
A2A server, model call, or production host is included. See the
[A2A integration contract](docs/A2A_INTEROPERABILITY_CONTRACT.md).

The wheel includes three runnable synthetic transcripts. This example loads
them from the installed package:

```python
from importlib.resources import files
from mudra_interact_core import render_message, validate_transcript

examples = files("mudra_interact_core").joinpath("examples", "language")
messages = validate_transcript(examples.joinpath("human-agent.json").read_bytes())
for message in messages:
    print(render_message(message))
```

Read the [communication-language API](docs/COMMUNICATION_LANGUAGE_API.md) and
[migration notes](docs/MIGRATION.md). The bundled examples cover
human-to-human, human-to-agent and agent-to-agent conversations.

## Gesture events

The gesture/event protocol accepts normalized 21-point hand landmarks, reports
bounded recognition states, and emits a `MudraEvent` only after distinct-frame
stability plus explicit consent and confirmation. It processes landmark data;
it does not capture camera images or video.

- Strict parsing of landmarks, bounded JSON and protocol versions.
- Geometric contact rules with candidate, stable, uncertain and rejected
  states. Scores are heuristic, not calibrated probabilities.
- Explicit temporal stability and one-use event confirmation.
- A neutral catalogue, closed schemas, local CLI and reproducible wheel/sdist.

## Safety and scope

Message validity is not identity, consent, authentication, permission or
authorization. An `accept` act is data and must not itself trigger execution.
Applications remain responsible for identity, transport security, durable
replay controls, consequential-action confirmation, retention and provider
policy. The package includes no model integration, social publishing, camera
adapter, host UI, hosted service or telemetry.

No human-comprehension study, community review, accessibility qualification,
recognition-accuracy study or independent security assessment is claimed.
Gesture labels do not assert universal, religious or tradition-specific meanings.

See the [gesture API](docs/API.md),
[communication-language API](docs/COMMUNICATION_LANGUAGE_API.md),
[compatibility policy](docs/COMPATIBILITY.md), and [changelog](CHANGELOG.md).
The source and release history are on
[GitHub](https://github.com/mayayaiinfra/Mudra-Interact-Core). Find the current
release on [PyPI](https://pypi.org/project/mudra-interact/0.4.2/),
[TestPyPI](https://test.pypi.org/project/mudra-interact/0.4.2/), and
[GitHub releases](https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.4.2).
