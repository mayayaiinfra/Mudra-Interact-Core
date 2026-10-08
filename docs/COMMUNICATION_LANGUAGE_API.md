# Mudra Communication Language API (experimental)

Package `mudra-interact==0.4.0` candidate adds the A2A transport adapter to the
versioned, modality-independent message format introduced in 0.3.0. It sits
beside the existing v2 gesture/event API and supports bounded creative
planning conversations among humans and software agents. The current language
protocol is `1.0.0`; the only supported intent profile is
`org.mayayai.creative.plan` version `1.0.0`.

## Workflow

An application or BYOK model can draft a message object. The host should show
the interpretation and requested proposal to the relevant person, allow
clarification or refusal, and validate the complete transcript before using it
in the application. The core supplies structure, sequence checks and a literal
text rendering. It does not choose a model or send messages to one.

```python
from importlib.resources import files

from mudra_interact_core import render_message, validate_transcript

example = files("mudra_interact_core").joinpath(
    "examples", "language", "human-agent.json"
)
messages = validate_transcript(example.read_bytes())

for message in messages:
    print(render_message(message, locale="en"))
```

The packaged examples can be loaded this way after installing the wheel; no
repository checkout or external file is needed. The three examples are
synthetic. They demonstrate human-human planning, a human-agent exchange with
clarification and a revised proposal, and agent-agent planning.

## Python API

- `parse_message(data)` accepts bounded UTF-8 JSON bytes or a built-in dict and
  returns an immutable `Message`. It rejects unsupported versions, extra
  fields, invalid provenance, unknown intent profiles and malformed payloads.
- `check_freshness(message, now_utc)` checks the message expiry against an
  explicit canonical UTC timestamp. It does not authenticate a clock or sender.
- `validate_transcript(data)` validates all messages and their reply graph,
  participant directions, scope, times, proposal dispositions and terminal
  relationships. Any invalid entry rejects the transcript as a whole.
- `render_message(message, locale="en")` returns deterministic plain text for
  review. Unsupported locales fail; rendered text is not a trusted command.
- `LanguageValidationError.code` contains a fixed error category suitable for
  caller handling without exposing submitted content.

The same names are exported from `mudra_interact_core`. The exact JSON contract
and resource limits are defined by
[`language.schema.json`](../src/mudra_interact_core/schemas/language/v1/language.schema.json)
and [the language contract](COMMUNICATION_LANGUAGE_CONTRACT.md).

## Experimental A2A client in the unreleased source

The unreleased source includes `A2AClient` for the A2A specification snapshot
at `/v1.0.1` (released protocol 1.0.0), using wire version 1.0 and JSON-RPC
over HTTP(S). It sends a
validated Mudra envelope in one `application/json` DataPart and validates
returned agent messages. It uses no A2A SDK or runtime dependency. The host
must supply a configured endpoint, authenticated `AuthenticatedPrincipal`,
clock callback, `ReplayStore`, optional remote AgentInterface tenant, and
optional bearer-token provider. The authenticated host tenant is kept local
and is never sent as the remote A2A routing tenant.
Production replay storage must be atomic and durable across workers;
`InMemoryReplayStore` is for tests and single-process demonstrations only.

```python
from mudra_interact_core import A2AClient, AuthenticatedPrincipal

client = A2AClient(
    "https://agent.example/rpc",
    remote_agent_id="44444444-4444-4444-8444-444444444444",
    replay_store=host_durable_replay_store,
    clock_utc=host_trusted_clock,
    token_provider=host_token_provider,
)
reply = client.send(message, principal=authenticated_user)
```

`authenticated_user` must be an `AuthenticatedPrincipal` built from the host's
verified session. The message's sender and recipient must match that principal
and the configured remote agent. A returned task handle is scoped to endpoint,
agent, remote interface tenant, principal, host tenant, and Mudra conversation.
`decline` sends a message;
`cancel()` is a separate explicit operation and cannot undo remote side effects.
Parsing alone does not send anything. `accept` does not authorize execution.

The client implements neither an A2A server nor a human UI. Human-to-human is
schema-only; human-to-agent, agent-to-human replies, and agent-to-agent sends
have local loopback peer coverage. No third-party agent or production host has
been qualified. See the [A2A integration contract](A2A_INTEROPERABILITY_CONTRACT.md).

## Safety and scope

The acts are `request`, `proposal`, `clarification`, `accept`, `decline`,
`acknowledge`, `status`, `result` and `error`. Role fields describe asserted
message roles; they do not prove identity. Provenance fields record assertions
about modality, adapter, score and human review; they are not independently
verified. `accept` and `human_reviewed` values do not authorize tool execution,
publication, payment, provider access or any other consequential operation.

The package makes no network requests and has no runtime dependencies. It
contains no transport, account integration, MCP/A2A adapter, model, content
generator, social-platform publisher, user interface or credentials. BYOK
models and creator tools can be supplied by a consuming application, under its
own visible data and permission policy. This release demonstrates structured
planning and review; it does not claim a complete creative-production plugin.

The contract does not claim universal natural-language or sign-language
coverage, comprehension, cultural suitability, accessibility or user-tested
clarity. Those require the separate human qualification in ML-05. The live
interoperability contract in ML-06 is also separate.
