# Mudra communication-language human qualification protocol

**Backlog item:** ML-05. **Status:** Study design draft; no participants
recruited and no human evidence collected. This document does not qualify the
SDK or authorize recruitment.

**Scope:** English reference renderer and the `org.mayayai.creative.plan`
1.0.0 profile in the 0.4.0 candidate.

**Owner:** MAYAYAI, with an independent moderator and scoped accessibility and
community reviewers assigned before a study begins.

## Purpose and claim boundary

This formative study checks whether people can inspect the experimental
rendering, understand what a message asserts, correct a mistaken
interpretation, refuse a proposal, and recognize that message roles and
`accept` do not authenticate people or authorize actions. It covers synthetic
human-to-human, human-to-agent, agent-to-human, and agent-to-agent exchanges.

The study does not test gesture recognition accuracy, sign-language meaning,
model quality, production use, a transport adapter, or universal comprehension.
The current SDK is English-only and has no user interface. Results apply only
to the exact package, renderer, locale, and synthetic scenarios tested. A
small formative sample can find issues; it cannot establish statistical
representativeness or broad suitability across communities.

No study may start until the owner has populated and approved the participant
notice and data-handling details below, confirmed whether local ethics or
privacy review is required, and arranged eligible volunteers. Do not recruit,
contact participants, collect responses, or claim review from this draft.

## Study design

Use moderated individual sessions of approximately 30–45 minutes. The
moderator must not be the only implementer of the tested feature. Sessions may
be remote or in person, but the same fixed renderer output and task wording
must be used. Do not record audio, video, screen contents, or keystrokes.

Target 12–16 adult volunteers for an exploratory English-language round. Use
purposive recruitment to include a mix of people who do and do not regularly
use AI/creative tools, plus people who use relevant accessibility features.
Ask only which access supports are useful; do not request diagnoses. Separately
assign at least two reviewers with relevant lived or professional experience
for each community or accessibility claim the project proposes to make. Record
the population, language, modality, and context each reviewer can speak to.
These target counts are planning thresholds, not evidence of statistical
power. If the required access or reviewer coverage is unavailable, document
that limitation and keep the corresponding claim blocked. Any compensation,
recruitment service, or other spending requires separate authorization.

Use only synthetic briefs, participant IDs, and example participant IDs. Do
not ask volunteers to submit personal, customer, confidential, or sensitive
content. Every task uses the exact experimental `render_message` output and
can be completed without an account, model provider, network service, or
gesture input.

## Session procedure and tasks

1. Present the participant notice, answer questions, obtain affirmative
   consent, and assign a random study ID. A refusal or withdrawal ends the
   session without penalty.
2. Explain that the SDK is experimental and show one neutral practice message
   that is excluded from scoring.
3. Present counterbalanced synthetic exchanges covering all four role
   directions. Do not reveal the expected answer before a response is recorded.
4. For each selected message, ask the participant to identify the asserted
   sender and recipient, summarize the message in their own words, identify the
   act and relevant proposal/reply, and state what they would do next.
5. Include a proposal, a revision, an explicit decline, an `accept`, a status,
   a result, and a message whose asserted role/provenance is misleading. Ask
   whether the message authenticates identity, grants permission, or proves
   that an action or artifact exists. Expected answer: it does not.
6. Ask the participant to correct an intentionally mismatched interpretation,
   request clarification, decline the proposal, or choose the available
   non-gesture alternative. No default gesture meaning is shown or implied.
7. Ask which text was unclear and what alternative wording or input would help.
   Remind participants not to include identifying or sensitive details.
8. Close by restating the study limits, withdrawal method, and data deletion
   deadline. Record no more than the approved structured observations.

The task sheet must contain a fixed key for each scenario: intended act,
asserted roles, referenced proposal, safe next-step options, and the specific
non-authorization fact being tested. Two reviewers independently code
open-ended summaries against that key; disagreements are retained and resolved
with a written rationale, not silently averaged. Do not score stylistic
agreement with the authors as correctness.

## Measures and stop rules

Record per-task correct/incorrect/unclear, first-response correction, whether
the participant requests clarification or refuses when appropriate, and any
access barrier. Confidence ratings may be collected on a fixed 1–5 scale but
must not be described as calibrated. Keep any short participant explanation
only as long as needed for independent coding; remove names and incidental
personal details before analysis.

Treat any participant interpreting `accept` as execution permission, a role
claim as authenticated identity, or a result as proof of a generated or
published artifact as a critical comprehension failure. Pause that scenario,
record the failure without blaming the participant, and do not claim the
tested text is safe or clear. A proposed revision must be retested with new
volunteers; the same participant's corrected answer does not erase the initial
failure.

For non-critical task comprehension, pre-register a descriptive threshold of
at least 80% correct first responses for each tested act/direction combination
and report the numerator and denominator. This is a project decision rule for
the small sample, not a validated benchmark. Any accessibility barrier that
prevents completing a task is recorded as a failure for that access path until
remediated and retested. A passing round supports only the narrowly scoped
experimental description; it does not prove universal usability or
accessibility.

## Participant notice draft

This text is not ready to present until bracketed fields are completed and the
owner has approved the actual data flow and contact route:

> **Voluntary study of experimental Mudra Interact message text**
>
> [Legal entity and contact] is asking you to help evaluate whether people can
> understand sample messages from an experimental software library. We will
> ask you to interpret synthetic examples, identify when a message is unclear,
> and try correction or refusal options. The study is limited to English text
> and does not evaluate or certify the product for general use.
>
> Taking part is voluntary. You may skip any question or stop at any time
> without penalty. We will record a random study ID, structured task results,
> access supports you choose to use, and brief explanations needed to code
> comprehension. Please do not provide names, contact details, health
> information, customer content, or other identifying or sensitive details.
> We will not record audio, video, screen contents, or keystrokes, and will
> not send your answers to an AI or analytics provider.
>
> The study team will store the approved study records in [approved storage]
> with access limited to [named roles]. Short explanations will be deleted by
> [date/rule]. Coded study records will be deleted by [date/rule]. The report
> will use aggregate counts and will not identify you. Because a small study
> can make people recognizable from context, we will not call the source data
> anonymous. To withdraw or request deletion before [cutoff], contact
> [approved contact] using study ID [ID]. After [cutoff], records may have
> been aggregated and may no longer be attributable to an individual.
>
> This study is not a service, medical evaluation, or promise that the software
> is safe or suitable for your use. Questions or concerns may be sent to
> [approved contact]. By continuing, you confirm that you are at least
> [approved age] and voluntarily agree to participate.

Do not replace bracketed fields with guessed legal identities, storage
locations, retention promises, ages, or rights channels. If raw explanations
are not necessary for the chosen analysis, remove that field and its collection
entirely. Consent records and study answers must be stored separately where
feasible; the random study ID must not be an account, email, or device ID.

## Evidence and report format

The final report must record the tested package/source identity; protocol and
renderer version; recruitment and exclusion method; participant count and
only the coarse, consented characteristics needed to describe coverage; access
supports; exact scenarios and task-key hashes; raw counts per task; critical
failures; reviewer disagreements; deviations; revisions; retest results; data
deletion evidence; and remaining limitations. Do not include participant
names, contact details, raw recordings, or identifiable quotations. Obtain a
separate explicit permission before publishing a quotation; otherwise
paraphrase only after privacy review.

The study operator signs the evidence as `human_study`, not
`luna_self_verified`. Preserve a source-free summary of results and a restricted
consent/deletion receipt under the approved schedule. A completed questionnaire
or synthetic test is not a participant study. ML-05 remains open until actual
consented sessions, scoped community/accessibility reviews, remediation, and
the final limitations report are present.
