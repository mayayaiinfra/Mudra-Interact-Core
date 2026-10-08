# Mudra Interact language: reviewed follow-on contract

Design revision 0.1, Astra technical model review, 2026-10-08.
**Normative contract for the experimental SDK introduced in package 0.3.0 and
extended by the 0.4.0 candidate.** This contract defines a bounded experimental
reference SDK in `mudra-interact==0.4.0`, after the published foundation release. It does not change
the existing event protocol/schema `2.0.0`, four-cue catalogue, consent lifecycle,
or camera-design boundary. The current release remains governed by the
[core specification](../MUDRA_INTERACT_CORE_SPEC.md).

## Product and architecture decision

Mudra Interact is a proposed interaction language with a Python reference SDK.
The language expresses typed communicative acts; it is not a natural language,
signed language, universal gesture vocabulary, reasoning model, transport,
identity provider, or action executor. A communication record cannot authorize
an action. Human-human, human-agent, agent-human and agent-agent records share
the same grammar and validation; roles do not authenticate their participants.

The first implementation is a dependency-free offline validator, immutable
message model, plain-text renderer and synthetic creative-planning transcripts.
It includes no camera/model/provider calls, tool execution, credential handling,
artifact download, browser/server transport, or named host plugin. A creative
plugin is a separately implemented integration requiring a chosen host and real
integration proof; installing this SDK alone is not that plugin.

Keep the existing import namespace. Add a separate
`mudra_interact_core.language` module and packaged `schemas/language/v1`.
Use wire `protocol_version: "1.0.0"` and schema ID
`urn:allyk:mudra-interact:language:1.0.0`. The independent language version must
never be mistaken for historical gesture-event v1. No automatic event/message
conversion, schema sniffing, event consent reuse, or reinterpretation of saved
events is allowed. Existing v2 imports/CLI remain compatible and regression-tested.

## Fixed envelope and bounds

Every object is closed. Every field below is required; only `reply_to` is
nullable. Do not silently add defaults, coerce, trim, normalize or truncate.

| Field | Exact requirement |
| --- | --- |
| protocol_version | String `1.0.0` |
| message_id, conversation_id | Canonical lowercase UUID strings |
| sender, recipient | Each exactly `{participant_id, kind}`; canonical UUID and enum `human` or `agent`; participant IDs must differ |
| reply_to | Null for a root request, otherwise canonical UUID distinct from message_id |
| created_at, expires_at | Valid UTC `YYYY-MM-DDTHH:MM:SS.ffffffZ`; `created_at < expires_at <= created_at + 600 seconds` |
| act | `request`, `proposal`, `clarification`, `accept`, `decline`, `acknowledge`, `status`, `result`, or `error` |
| intent | Exactly `{name, version, payload}` as specified below |
| provenance | Exactly `{mode, adapter_id, adapter_version, interpretation_score, human_reviewed}` as specified below |

One message is at most 65,536 UTF-8 bytes; a transcript at most 1,048,576 bytes,
with 1..128 messages. JSON depth is at most 16. No string exceeds 4,096 Unicode
scalars; tighter field bounds apply below. Use the v2 parser's strict duplicate
key, UTF-8/BOM, surrogate, finite-number, trailing-document and pre-decode depth
rules with the language-specific limits. No remote schema references.
Strings accept Unicode except lone surrogates and controls U+0000..U+001F and
U+007F; LF is allowed only in `brief`, `text`, `summary`, and step `description`.
Other fields cannot contain controls. All lengths include whitespace; text
fields must contain at least one non-whitespace character. Render untrusted
text literally, including escape-like text; never evaluate HTML, Markdown,
template syntax, URLs, commands or embedded instructions.

Only concrete builtin dictionaries, lists, strings, booleans and finite numeric
values enter constructors; lists become immutable tuples internally. UUID/time
validators do not run user-defined conversion hooks. Constructors and wire
parsers enforce the same checks. `payload()` returns detached objects.
Serialization uses sorted keys, compact separators, UTF-8, no NaN, and no
signing/canonicalization claim. Repeated serialization of an unchanged message
is byte-identical. The grammar contains no metadata bag, key, raw media,
landmarks, filesystem path, URL, or automatically dereferenced artifact.
Free text can contain personal data or prompt injection; closed fields do not
make this language's text anonymous or safe to send to a model.

## First intent profile and speech acts

The only supported intent is `name: "org.mayayai.creative.plan"`,
`version: "1.0.0"`. This names a planning discussion, never generation or
publication permission. Reserve `org.mayayai.*` for the project; other
reverse-domain namespaces need a separately versioned, reviewed profile.
Unknown protocol/intent versions, intent namespaces and acts fail closed with
a fixed error; no guess, implicit downgrade, dynamic plugin import or network
lookup. A host may retain unknown bytes outside the SDK, but cannot call them
validated or interpreted. Extension negotiation and opaque forwarding are
deferred, not partially implemented.

The act selects the exact `intent.payload` shape:

| Act | Required payload fields and bounds |
| --- | --- |
| request | `brief`: 1..4096 scalars; `medium`: `text`, `image`, `audio`, or `video` |
| proposal | `summary`: 1..1024 scalars; `steps`: 1..16 closed objects, each `{step_id, description}`, with `step_id` an integer 1..16 excluding bool and `description` 1..1024 scalars; IDs exactly 1..N in order |
| clarification | `text`: 1..1024 scalars; `about`: `brief` or `proposal` |
| accept | Empty object; acceptance refers to exactly the proposal identified by reply_to |
| decline | `reason`: `not_intended`, `needs_revision`, or `not_now` |
| acknowledge | Empty object; receipt only, no approval claim |
| status | `state`: `planning` or `waiting_for_input`; `text`: 1..1024 scalars |
| result | `summary`: 1..4096 scalars; describes planning output only, no generated-artifact or delivery claim |
| error | `code`: `unsupported_request`, `permission_denied`, `provider_unavailable`, or `internal_error`; no exception text |

All other payload fields fail, including `execute`, `approved`, `consent`,
`token`, `url`, `path` or embedded v2 events. The profile contains no media
generation tool. A synthetic provider-unavailable error tests communication
behaviour, not integration with a live provider.

`provenance.mode` is `text`, `gesture`, `speech`, or `agent`.
`adapter_id` matches `[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+`, length 3..128;
`adapter_version` matches `(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})`.
`interpretation_score` is null or a builtin finite int/float in [0,1], excluding
bool. It is adapter-reported, not a calibrated probability or a core recognizer
score. `human_reviewed` is an exact bool describing an assertion, never proof.
Mode `agent` requires sender.kind `agent`; other modes require `human`.
No adapter ID/version is a claim of installed or trusted code. Text-mode examples
use `org.mayayai.manual_text` version `1.0.0`, null score and a visibly recorded
review step. The SDK cannot establish that review occurred.

## Conversation grammar and validation API

Provide `parse_message(data)`, `validate_transcript(data)`, `Message.to_bytes()`
and `render_message(message, locale="en")`. `data` accepts bounded bytes or an
exact builtin dict; string JSON support is not required. The transcript envelope
is exactly `{protocol_version: "1.0.0", messages: [...]}`. These APIs perform
no external side effects. Failed transcript validation produces no partial
valid transcript. Use a distinct `LanguageValidationError(code)`; fixed codes:
`invalid_json`, `input_too_large`, `invalid_shape`, `invalid_number`,
`unsupported_version`, `unsupported_intent`, `invalid_sequence`, `scope_mismatch`,
`expired_message`, `unsupported_locale`, `input_unavailable`, `internal_error`.
Error precedence: byte/JSON limits, types/closed fields, versions/intent,
field values, then conversation relationships. No input values in errors.

Structural `parse_message` validates shape, versions, act payload, roles and
time interval; it does not claim current freshness, identity or authorization.
`validate_transcript` additionally requires one conversation, consistent kind
for each participant ID, unique message IDs, and nondecreasing creation times.
The first message is a root request and all later messages have nonnull
`reply_to` naming an earlier message in this same transcript. For each reply,
sender/recipient must reverse the referenced message's participant IDs, both
messages must use the same intent/version, and reply creation must not exceed
the referenced message's expiry. An acknowledgement cannot extend expiry.

| Act | Allowed referenced act |
| --- | --- |
| request | None; exactly one root per transcript |
| proposal | request or clarification |
| clarification | request or proposal; `about` equals `brief` for request and `proposal` for proposal |
| accept, decline | proposal; at most one accept OR decline for a given proposal |
| acknowledge | Any act except acknowledge; at most one per referenced message |
| status, result | accept; no status/result after a terminal result or error for that accept |
| error | request or accept; at most one terminal error/result for the same referenced message |

Revised proposals have new message IDs and do not inherit acceptance. A status
record does not prove work ran. A result record does not prove an artifact
exists. An accept records agreement to a plan, not a permission grant. The
transcript is a bounded exchange, not a persistent replay database or task
scheduler. Histories beyond 128 messages require a new host-managed scope and
explicit policy; never silently drop the beginning to validate the remainder.

Add a separate pure `check_freshness(message, now_utc)` using an explicitly
provided strict UTC timestamp: reject creation more than 30 seconds ahead of
now and reject `now > expires_at`; equality at expiry is allowed. No system
clock lookup by this helper. Hosts must authenticate participants, validate
scope, enforce idempotency/replay storage, and call freshness checks when
receiving a live message. Pure transcript validation can inspect expired
archives without conferring present authority.

## Human rendering, gestures and authority

English is the only reference locale. Any other locale fails
`unsupported_locale`, never silent mistranslation. Render each envelope/act
using deterministic neutral labels, explicit participant kind/ID, the exact
referenced ID, payload and provenance assertions. Begin with an explicit
experimental message label. Include the fixed sentence: "This message does
not authorize execution." State that participant identities and kinds are
message claims and are not authenticated. This is a literal plain-text
representation, not an accessibility qualification. Render bidirectional
controls visibly and test control/bidirectional text presentation; escape
dangerous formatting at each future HTML/UI boundary.

Humans must be able to inspect the whole interpretation, clarify or decline
it, and use an alternative input path. An adapter may suggest a selected act
from a user-configured cue mapping; no default universal gesture meaning.
The existing four contact cues cannot directly encode a brief or authority.
No adapter is implemented in this milestone. Speech/gesture provenance fixtures
are synthetic assertions and must be labelled accordingly.

The SDK has no authorization or execution API. A future host must independently
bind any consequential action approval to authenticated participants, exact
message/proposal revision, full interpreted action parameters, conversation,
policy and short-lived nonce; deny stale/replayed/mismatched approvals and
consume them once. A claimed `accept`, `human_reviewed=true`, role `human`,
confidence score, or old v2 consent never satisfies those checks. Host action
policy must be designed/reviewed before an executing adapter is added.

## Interoperability and release boundary

Keep transports separate. A2A has its own messages, tasks, lifecycle and
authentication; MCP exposes server tools/resources/prompts. The first bounded
transport is the A2A specification documentation snapshot at `/v1.0.1`, which
lists protocol release 1.0.0; the wire `A2A-Version` is `1.0`, over JSON-RPC
HTTP(S). The exact message/identity/task mapping and
limits are in [the A2A interoperability contract](A2A_INTEROPERABILITY_CONTRACT.md).
The client is implemented directly against the wire contract with the Python
standard library; it does not depend on the A2A SDK. The independent live
loopback peer is engineering evidence, not a public conformance statement or
third-party host qualification. MCP remains unimplemented. Never map `accept`
directly to a tool call. Do not add generic plugins, LLM providers or optional
dependencies to the offline core.

These architectural boundaries are informed by the [A2A specification](https://a2a-protocol.org/latest/specification/),
[MCP server primitives](https://modelcontextprotocol.io/specification/draft/server/index),
and [W3C multimodal framework](https://www.w3.org/TR/mmi-framework/), reviewed
2026-10-08. Their moving URLs are background references, not version pins or
conformance evidence for Mudra.

The [follow-on backlog](COMMUNICATION_LANGUAGE_BACKLOG.json) defines engineering
and external qualification gates. ML-01 freezes the draft-2020-12 JSON Schema,
version map and independent synthetic vectors. ML-02 implements bounded
message parsing and freshness. ML-03 implements bounded transcript relationships,
synthetic exchanges and deterministic plain-text rendering. ML-04 packages and
qualifies the 0.4.0 candidate, including its explicit A2A client, while retaining
the existing gesture matrix. Each engineering gate requires fresh, hash-bound
evidence after its candidate is committed. ML-05 human qualification remains
separate and blocked; ML-06 qualifies only a local A2A peer, not a production
host or public interoperability. Broad usability/cultural/accessibility claims
remain blocked without actual representative human evaluation.
