# Mudra Interact as a communication language — proposal

**Status: historical direction proposal, technically reviewed 2026-10-08.**
The [review decision](ASTRA_REVIEW_2026-10-08.md) and
[follow-on contract](COMMUNICATION_LANGUAGE_CONTRACT.md) settle the bounded
next step. The original `0.2.0` gesture/event foundation remains governed by
`MUDRA_INTERACT_CORE_SPEC.md` 0.3.1 and event schema `2.0.0`; package `0.3.0`
adds the separately specified experimental language SDK.
As a tracked document, this proposal changes source identity and requires
candidate evidence to be refreshed even though it changes no wire behaviour.

## Product direction

Define Mudra Interact as a versioned, modality-independent interaction
language: a shared vocabulary and grammar for expressing intent, proposals,
questions, confirmations, refusals, status, and results between people and
software agents. The Python package would be the reference SDK and validator.
Gesture, text, speech, and other input methods are adapters that map signals to
the shared language; they are not the language by themselves.

The product should support three communication paths:

1. **Human to human:** render a structured intent in a form both participants
   can understand and answer. Mudra must not claim to replace natural languages
   or signed languages, nor claim universal gesture meanings.
2. **Human to agent:** express a request, inspect the agent's interpretation,
   clarify it, and explicitly approve consequential execution.
3. **Agent to agent:** exchange typed requests, proposals, acknowledgements,
   status and results while preserving provenance, task scope and authorization
   boundaries.

## Interoperability position

Mudra should own shared interaction semantics and modality provenance, not
reinvent every transport. A2A already defines agent discovery, task
collaboration and message exchange between independent agents. MCP exposes
tools, resources and prompts between AI applications and model clients. W3C's
Multimodal Interaction work established a modality-separated architecture for
recognition, interaction management, and input/output components. Mudra's
potential contribution is a human-readable semantic layer and consistent
clarification/confirmation behavior that can be carried by those systems.

Initial integrations should therefore map Mudra messages to A2A tasks/messages
and expose Mudra operations through MCP tools/resources. They must retain the
native transport's identity, authentication and lifecycle rather than treating
a Mudra event as authenticated or authorized merely because it validates.

## Proposed message model

The new contract should separate these concepts instead of overloading a
gesture event:

- **Envelope:** exact protocol version, message ID, conversation/task scope,
  sender and recipient roles, creation time, reply/correlation ID, and bounded
  expiry or replay rules where applicable.
- **Act:** a closed vocabulary such as `request`, `proposal`, `clarification`,
  `accept`, `decline`, `acknowledge`, `status`, `result`, and `error`.
- **Intent:** a namespaced, versioned meaning with a schema-validated payload.
  Unknown meanings remain uninterpreted; implementations must not guess.
- **Modality provenance:** input/output mode, adapter and model revision,
  interpretation confidence and whether a human reviewed the interpretation.
  Confidence is evidence about an adapter result, never authorization.
- **Authority:** a separate host-owned decision about what may execute. A
  message that says `accept` does not by itself prove a human approved it.
  Sensitive or irreversible actions need a fresh, scope-bound host confirmation.
- **Rendering:** a localized human-readable explanation of the interpreted
  message and requested action, with a way to clarify or reject it.

Base messages should be bounded, closed, deterministic and transport-neutral.
Extensions use namespaced vocabularies with explicit version negotiation.
Media and large artifacts travel by separate, access-controlled references;
they are not embedded in an unrestricted metadata bag. No images, voice,
landmarks, keys or private account data are sent to a model unless an adapter's
separate, visible policy permits that specific transfer.

## Role of the current gesture core

Keep the existing four geometric contact cues as one experimental input
adapter. They may signal simple controls such as select, request clarification
or confirm only after a user-configured mapping and visible review. The cues do
not encode rich prose, intent, emotion, identity, cultural meaning or a complete
message. The current stabilizer, consent checks and image-free event remain a
useful safe input substrate, not evidence that the full communication language
exists.

## Creative AI as the first demonstrator

Use a creator workflow as the first end-to-end profile, not as the language
definition. A creator supplies a brief; an agent proposes a content plan,
storyboard and asset prompts; the creator can clarify, accept or reject each
proposal; generation tools return referenced artifacts and a result message.
The human remains the publisher. BYOK model providers and image/video engines
are optional adapters, separately configured, with credentials kept out of
Mudra messages and saved workflow data.

This gives the package a practical demonstration while keeping the core useful
for other domains. It does not imply that the current gesture recognizer
generates creative content or that a generic PyPI install is itself a UI plugin.

## Required review and acceptance before implementation

Before revising the normative contract, Astra should settle:

1. Product name and definition: language, interaction protocol, SDK, or a
   deliberately layered combination.
2. Relationship and version mappings to A2A and MCP, including conformance
   vectors and unknown-version behavior.
3. The first closed speech-act and intent vocabularies, extension namespace,
   localization/rendering rules, and message/resource bounds.
4. Sender identity, provenance, authentication, replay protection, consent,
   confirmation and host action authority; identify what remains outside the
   public core.
5. Human-human validation, including language, cultural, accessibility and
   representative-user review. Synthetic tests alone cannot pass this gate.
6. Package/repository boundaries: core SDK versus MCP/A2A/creative adapters,
   optional dependencies, distribution names and release versions.

The new acceptance matrix should include positive and negative conformance
vectors for all three communication paths, semantic mismatch and clarification,
unknown extension/version, tampered/stale/replayed messages, permission denial,
localization/rendering, provider failure and real integration tests. M4
publication evidence for the gesture-only `0.2.0` must not be reused to claim
conformance for the language implementation or its later release.

## References

- [A2A Protocol specification](https://a2a-protocol.org/latest/specification/)
- [MCP server primitives](https://modelcontextprotocol.io/specification/draft/server/index)
- [W3C Multimodal Interaction Framework](https://www.w3.org/TR/mmi-framework/)
