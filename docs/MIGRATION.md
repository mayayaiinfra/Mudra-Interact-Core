# Migration to Mudra Interact 0.4.2

## From package 0.4.1 to 0.4.2

Version 0.4.2 clarifies the public package description and fixes the release
links to point to the exact package version. It preserves the language v1 and
gesture/event v2 contracts and the experimental A2A JSON-RPC client. No runtime
dependency or migration step is introduced.

## From package 0.4.0 to 0.4.1

Version 0.4.1 updates the public description and documentation to explain the
vendor-neutral communication contract and its role in future multi-agent
workflows. It keeps the language v1 and gesture/event v2 contracts and the
experimental A2A JSON-RPC client unchanged. No runtime dependency or migration
step is introduced.

To use the A2A client added in 0.4.0, construct `A2AClient` with the configured
remote agent, host clock, authenticated `AuthenticatedPrincipal`, and an atomic
durable `ReplayStore`.
Set `remote_tenant` only when the selected remote AgentInterface requires its
own routing tenant. Do not pass the authenticated host tenant as the remote
tenant. Use `A2ATaskRef` only with the client and authenticated scope that
created it. `decline` sends a message; explicit `cancel()` is a separate request
and cannot undo remote side effects. `accept` never authorizes execution.

The included `InMemoryReplayStore` is for tests and single-process examples;
replace it with a durable, atomic store for multi-worker hosts. Human-to-human
remains schema-only, and a local peer test does not qualify a public agent or
production host. See the [A2A interoperability contract](A2A_INTEROPERABILITY_CONTRACT.md).

## From package 0.2.0 to 0.3.0

This is an additive package release. The v2 gesture/event schema and CLI
contract remain unchanged. Existing v2 frames, reports, batches, events and
imports continue to use the same `mudra_interact_core` namespace and
`2.0.0` protocol. The version map now identifies package `0.3.0`.

The new experimental language surface is separate from v2 gesture events:

- Import `Message`, `parse_message`, `check_freshness`,
  `validate_transcript`, `render_message` and `LanguageValidationError` from
  `mudra_interact_core`.
- Keep language `protocol_version: "1.0.0"` distinct from gesture
  `schema_version: "2.0.0"`. A gesture event is not a language message and
  cannot be converted into a language-level approval.
- Use the packaged synthetic transcripts through `importlib.resources` as
  shown in [the communication-language API](COMMUNICATION_LANGUAGE_API.md).
- Handle `LanguageValidationError` without logging submitted message content.
  The parser enforces size and shape limits; it does not authenticate the
  sender, verify provenance or authorize execution.
- Keep transports, BYOK credentials, models, provider calls and consequential
  action approvals in the host application. No MCP/A2A or publishing
  integration is included in this release.

The package has no runtime dependencies. Installing 0.3.0 does not perform an
automatic data migration or change behavior of v2 consumers.

## From package 0.1.0 to 0.2.0

Version 0.2.0 is a breaking protocol and API revision. The v1 reference package
uses event schema `1.0`; the v2 contract uses protocol and event schema `2.0.0`
and catalogue `2.0.0`. See the bundled
[`version-map.json`](../src/mudra_interact_core/schemas/v2/version-map.json).

## Data and permission

Treat a v1 event as historical data for inspection and manual migration only.
A v1 event is not accepted as a v2 event. Do not infer current
consent or participant confirmation from an old event, stored boolean, sender
type, or truthy string. New sharing requires fresh, validated observations,
current participant confirmation and an unconsumed grant bound to that stream,
scope and result revision.

## Field changes

- Rename tradition-specific classifier labels to the four neutral contact IDs in the v2
  specification. Historical names are unverified migration aliases and are not
  enabled or inferred by the core.
- Supply explicit `schema_version`, stream/frame IDs, monotonic time and a
  declared coordinate space for frames. Image-normalized input also supplies
  its dimensions.
- Recognition carries fixed `method`, catalogue version and code enums. Remove
  caller prose, arbitrary method names, free-form observations and distances.
- Remove the event metadata bag and `raw_*_retained` claims. V2 has closed event
  fields and `raw_media_included` / `raw_landmarks_included` flags describing
  the event itself.
- Use `event_only`, explicit `consent_confirmed` and
  `participant_confirmed` values, and the computed sender/recipient direction.
- Do not import a caller-provided `stable` value as proof. Stability comes from
  the session processing distinct, ordered frames and meeting the hold period.

Map business data in the consuming application after review. Do not silently
rewrite stored records, auto-upgrade private consumers, or reuse legacy consent.
The v2 contract does not define a database migration or authorize downstream
actions.
