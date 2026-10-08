# Mudra Interact A2A interoperability contract

**Status:** implemented transport contract; experimental and not a general
A2A-conformance claim. **Backlog:** ML-06. **Specification documentation
snapshot:** `/v1.0.1` (lists released protocol 1.0.0). **Wire version:**
`A2A-Version: 1.0`. **Binding:** JSON-RPC 2.0 over HTTP(S).
**Implementation:** Python standard library; no A2A SDK or runtime dependency.

This adapter sends one structurally valid Mudra message through an A2A peer and
validates a direct agent reply carried back in the A2A response. It supplies
transport only. It does not provide an agent, a human interface, a model call,
tool execution, content generation, or publication. The standard-library
binding is intentionally narrow and must fail closed on unrecognized protocol
shapes. It does not claim support for other A2A editions, protocol versions,
bindings, extensions, streaming, push notifications, discovery, or arbitrary
artifacts.

The wire mapping follows the [A2A specification snapshot](https://a2a-protocol.org/v1.0.1/specification/),
including its JSON-RPC `SendMessage`/`CancelTask` methods, `A2A-Version: 1.0`
header, server-issued task/context identifiers, client/server roles, and
DataPart representation. Mudra's own structure remains governed by the
[language contract](COMMUNICATION_LANGUAGE_CONTRACT.md).

## Data mapping

| Mudra value | A2A representation | Boundary rule |
| --- | --- | --- |
| Full validated Mudra envelope | Exactly one DataPart: `{"data":{"mudra_message":<envelope>},"mediaType":"application/json"}` | No free text, file, URL, second part, or metadata payload is accepted. |
| Mudra `message_id` | Inner envelope only | Never reused as the A2A `messageId`, JSON-RPC request `id`, `taskId`, or `contextId`. |
| A2A `messageId` / JSON-RPC `id` | Fresh, independent UUIDs | Correlation at the A2A layer only. |
| A2A `ROLE_USER` | Client-to-server transport direction | Does not assert a human sender. Mudra identity is read only from the inner envelope and checked against host-supplied principal. |
| A2A `ROLE_AGENT` | Server-to-client transport direction | Does not by itself authenticate a Mudra participant. The configured remote agent identity and authenticated endpoint must agree with the inner Mudra sender. |
| Mudra `conversation_id` | Kept in the inner envelope | Never used as an A2A context identifier. |
| A2A `taskId` / `contextId` | Returned by the server and held in `A2ATaskRef` | Sent only for an explicit continuation; bound locally to endpoint, remote agent/interface tenant, host principal/tenant, and Mudra conversation. A client does not invent them. |
| Remote AgentInterface tenant | Optional `SendMessage.params.tenant` / `CancelTask.params.tenant`, explicitly configured as `remote_tenant` | Opaque remote routing identifier. It must match the selected A2A AgentInterface when that interface declares a tenant. It is not a credential. |
| Host tenant | Local task scope and replay-key input | Never forwarded as the remote A2A tenant. It is an authenticated host boundary and is not proof of remote authorization. |
| Host credential | Optional `Authorization: Bearer …` header from an injected provider | Never accepted in a URL, persisted, logged, or copied into Mudra content. TLS certificate verification is enabled for HTTPS. |

For a first message, the adapter sends neither A2A `taskId` nor `contextId`.
It omits A2A `tenant` unless the host explicitly configures the selected
remote AgentInterface's routing tenant. The host's authenticated tenant is
kept separately for local scope and replay protection.
For a continuation, the caller must supply the task handle returned by the same
client and scope. The adapter rejects a handle from another endpoint, agent,
remote interface tenant, principal, host tenant, or Mudra conversation, and it
rejects terminal tasks.

## Trust, freshness, and replay

The host must authenticate the user or agent before constructing
`AuthenticatedPrincipal`. `participant_id`, `kind`, and `tenant_id` in that
object represent the host's verified session, not claims taken from an incoming
Mudra envelope. The host tenant is separate from optional remote
`AgentInterface.tenant` and is never forwarded as that A2A routing field.
The adapter requires the outgoing envelope's sender to match that principal and
its recipient to match the configured remote agent. On a response, it requires
the remote agent sender, original principal recipient, same conversation,
matching `reply_to`, and same intent. These comparisons bind claims to the
host's configuration; Python objects and a TLS endpoint alone are not a
cryptographic identity service.

The endpoint must be configured by the host, never constructed from message or
user content. Credentials embedded in endpoints, URL query strings, fragments,
and non-loopback cleartext HTTP are rejected. Redirects are not followed.
Response bytes, nesting, timeouts, task IDs, and content types are bounded.
The client makes no automatic retry. A timeout or uncertain network result
consumes the message ID; the host must reconcile the outcome rather than resend
it automatically.

Before sending, the adapter calls the injected host clock and applies Mudra's
freshness rule. It checks an inbound Mudra reply against the injected clock
again after receipt. The core never reads the machine clock.

`ReplayStore.claim(key)` must be atomic and durable across every production
worker. Its key is a SHA-256 digest of principal, tenant, remote agent, and
Mudra message ID. A duplicate claim is rejected before network I/O. The
included `InMemoryReplayStore` is only for tests and single-process examples;
it is not production replay protection. Hosts must retain claims for at least
the full message expiry window plus their clock-skew allowance and meet their
own retention policy.

## Refusal, cancellation, and authority

A Mudra `decline` is sent as a message. It does not call A2A `CancelTask`.
Cancellation occurs only when the host explicitly calls `A2AClient.cancel`
with a task handle in the same authenticated scope. Cancellation cannot undo
side effects already performed by a remote service.

The adapter maps no Mudra act to an execution, account grant, model/provider
call, payment, publication, or tool invocation. `accept` remains a Mudra data
message; it does not itself confer authorization. A consuming agent must apply
its own authenticated action policy. The adapter has no such action API, and
validating or importing a message has no network side effect.

Remote A2A errors are reduced to fixed local error codes; remote error text and
submitted message content are not copied into exceptions. Unknown response
versions, extensions, fields, parts, roles, IDs, or malformed envelopes reject
the complete response.

## Implemented path coverage and limits

| Communication direction | Current support |
| --- | --- |
| Human-to-human | Mudra schema/parser/transcript only; no A2A transport or UI. |
| Human-to-agent | A2A client send using a host-authenticated human principal. |
| Agent-to-human | A2A agent reply returned to a host-authenticated human principal. |
| Agent-to-agent | A2A client send using a host-authenticated agent principal and a configured remote-agent identity. |

These directions mean the asserted Mudra sender/recipient kinds. They do not
make A2A `ROLE_USER` synonymous with a person. The adapter is a client and does
not implement an inbound Mudra receiver/server, a platform-specific agent
runtime, or a general peer discovery flow. A live local A2A peer verifies the
HTTP/JSON-RPC exchange and negative behavior; no public third-party agent,
production host, model provider, or paid operation has been qualified.

## Local test peer and evidence

`tests/test_a2a_interop.py` starts an independent loopback HTTP server that
implements the pinned JSON-RPC wire shape without importing adapter functions.
It exercises an actual socket exchange, task continuation, explicit
cancellation, identity and tenant scope, replay rejection, stale messages,
refusal, injected provider-failure signaling, and malformed responses. The
peer uses only synthetic data and makes no model/provider call. This is a
repeatable integration peer, not an upstream conformance suite or external
deployment qualification.

The human-to-human comprehension study remains separate and open in ML-05.
The study protocol has placeholders for the controller/contact, storage,
retention, withdrawal and age fields that require owner-specific facts and
approval. No participants may be contacted or enrolled from the draft, and no
human usability, legal-compliance, accessibility or cultural-suitability claim
is made from these engineering tests.
