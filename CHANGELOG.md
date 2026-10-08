# Changelog

Changes are recorded by release. The links point to immutable tags and exact-version package pages.

## Mudra Interact 0.4.0 — 2026-10-08

Adds an experimental, standard-library A2A JSON-RPC client to the
communication-language SDK. It maps validated Mudra envelopes to one A2A
DataPart, validates agent replies, binds server-issued tasks to host and remote
scope, rejects replayed or stale messages, and requires a separate explicit
call for task cancellation. The host's authenticated tenant is distinct from
the optional remote AgentInterface routing tenant.

The independent loopback peer exercises the HTTP mapping and safety boundaries.
The exact wheel and source distribution were published to TestPyPI and PyPI,
downloaded, hash-checked and freshly installed. PyPI attestations and the
immutable GitHub release were verified. See [PyPI](https://pypi.org/project/mudra-interact/0.4.0/),
[TestPyPI](https://test.pypi.org/project/mudra-interact/0.4.0/), and the
[GitHub release](https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.4.0).

The client is experimental and has only independent loopback-peer qualification;
no public-agent or production-host qualification is claimed. Human-to-human
remains schema-only. The release includes no model/provider, tool execution,
publishing, human-comprehension, cultural or accessibility qualification.

## Mudra Interact 0.3.0

Adds an experimental, dependency-free communication-language SDK for bounded
human-human, human-agent and agent-agent creative-planning transcripts. The
release includes `Message`, strict message and transcript validation,
freshness checks, deterministic plain-text rendering, the closed language v1
schema and three packaged synthetic planning examples.

The v2 gesture/event protocol and CLI remain compatible with 0.2.0. Language
messages do not authenticate participants or authorize execution. This release
does not include a model/provider call, content generation, camera adapter,
MCP/A2A transport, host UI, publishing integration, or human cultural,
accessibility or usability qualification. The release workflow attaches the
exact wheel and source distribution to
[GitHub release v0.3.0](https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.3.0)
after publication verification.

## Mudra Interact 0.2.0

Prepared release contents:

- Closed v2 frame, recognition, event, batch and catalogue contracts with a
  neutral, provenance-bearing catalogue.
- Strict bounded parsing and geometry, distinct-frame temporal stabilization,
  explicit consent and single-use event confirmation.
- Image-free local CLI and reproducible wheel/source distribution.
- Linux x86_64 and Windows x86_64 support qualification on CPython 3.11–3.14.
- No runtime dependencies, camera capture, model assets or hosted service.

This section records the 0.2.0 package contents. Its exact wheel and source
distribution are attached to the immutable
[GitHub release v0.2.0](https://github.com/mayayaiinfra/Mudra-Interact-Core/releases/tag/v0.2.0).
