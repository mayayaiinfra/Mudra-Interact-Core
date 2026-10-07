# Migration from Mudra Core 0.1.0 to 0.2.0

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

- Rename cultural classifier labels to the four neutral contact IDs in the v2
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
