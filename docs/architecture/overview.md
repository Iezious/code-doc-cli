# Overview

## Decision

`code_index` is a CLI tool that builds a per-project SQLite index of a codebase across F#, C#, JavaScript, TypeScript, Go, Python, and LSL, exposes that index through hybrid BM25 + dense retrieval, and serves as the retrieval layer for documentation-generation pipelines run by Claude agents.

## Rationale

Polyglot codebases at real scale are too large to load into any single LLM context window — and even at 1M tokens, attention quality degrades over heterogeneous source. Asking subagents to re-read raw files for every doc pass is slow, expensive, and non-deterministic.

Building the index **once** and querying it **many times** moves the work to the right layer:

- Retrieval becomes deterministic and inspectable.
- Agents call a CLI rather than spawning sub-scrapers; iteration costs collapse from "another subagent dispatch" to "another SQL query."
- The artifact outlives the doc pass and serves the team as a semantic+lexical code search.

## Audience

1. **Claude Code agents** running documentation pipelines. They invoke the CLI from Bash to fetch relevant chunks, symbols, and dep edges.
2. **Humans** on the team who want a polyglot code search after the docs are written.

Both consume the same CLI; there is no agent-only or human-only mode.

## Scope

In scope:
- Index building, incremental sync, hybrid retrieval, symbol lookup, lightweight dep graph queries.
- Seven languages from day one: F#, C#, JS, TS, Go, Python, LSL.
- A plugin interface so a new language is added by writing one module, not modifying the engine.

Out of scope:
- A full LSP / code-intelligence platform.
- Cross-language semantic linking (function in F# calling endpoint in TS) — this is a candidate for a future cross-language graph pass but is **not** part of the MVP.
- IDE integration.
- Hosted index, multi-user concurrency, or any network-attached index server.

## Rejected alternatives

- **Pure subagent scraping (no index).** Works for small repos; collapses on huge polyglot ones. Re-reads are too expensive and non-reproducible. See `docs-generation-pipeline.md` for how the two combine instead.
- **Off-the-shelf vector DB server (Qdrant, Weaviate, Chroma-server).** Adds a process, network hop, and ops surface for no benefit at single-user-personal-tool scale. SQLite is in-process and portable.
- **A code-intelligence platform (Sourcegraph, etc.).** Too heavy for personal use, and we control the chunking strategy more directly when we own it.

## Implications

- The engine is **global**, the index is **per-project**. See `tool-and-data-split.md`.
- Implementation language is Python, managed by `uv`. This is a personal-scale tool; throughput and concurrency demands are modest.
- Determinism matters more than peak retrieval quality — agents need reproducible results across runs.

## Open questions

None pinned here. The cross-language graph pass and private-package-index publishing were demoted to [roadmap](roadmap.md).
