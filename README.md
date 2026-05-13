# codedoc

Universal codebase index and hybrid semantic/lexical search, built to power Claude Code documentation-generation pipelines across polyglot repositories.

## What it is

A CLI tool (`codedoc`) that walks a codebase, chunks it AST-aware per language, embeds the chunks locally, and stores everything in a per-project SQLite index alongside BM25 full-text search and a lightweight symbol/dep graph. Agents and humans query it the same way.

Supported languages: F#, C#, JavaScript, TypeScript, Go, Python, LSL.

## Why it exists

For large polyglot codebases, asking Claude agents to read raw source for every documentation pass is slow, expensive, and non-deterministic. Building the retrieval layer once — and querying it many times — keeps the orchestrator's context lean, makes follow-up scrapes near-free, and gives the team a durable search artifact.

## Status

Design phase. Implementation begins in a separate session. See `doc/architecture/` for the decisions, `doc/plans/` for the work plans, and `doc/CLAUDE.md` for the documentation layout.

## Install (planned)

```
uv tool install --editable .
```

After install, `codedoc` is on PATH and reads per-project config from `docs/.helpers/config.toml`.

## CLI surface (planned)

```
codedoc init
codedoc index build
codedoc index sync
codedoc search "..." --lang lsl --k 10
codedoc symbols defs Foo
codedoc graph callers Bar
```

See `doc/architecture/cli.md` for the full command surface.
