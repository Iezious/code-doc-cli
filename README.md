# code_index

Universal codebase index and hybrid semantic/lexical search, built to power Claude Code documentation-generation pipelines across polyglot repositories.

## What it is

A CLI tool (`code_index`) that walks a codebase, chunks it AST-aware per language, embeds the chunks locally, and stores everything in a per-project SQLite index alongside BM25 full-text search and a lightweight symbol/dep graph. Agents and humans query it the same way.

Supported languages: F#, C#, JavaScript, TypeScript, Go, Python, LSL.

## Why it exists

For large polyglot codebases, asking Claude agents to read raw source for every documentation pass is slow, expensive, and non-deterministic. Building the retrieval layer once — and querying it many times — keeps the orchestrator's context lean, makes follow-up scrapes near-free, and gives the team a durable search artifact.

## Status

Design phase. Implementation begins in a separate session. See `docs/architecture/` for the decisions, `docs/plans/` for the work plans, and `docs/CLAUDE.md` for the documentation layout.

## Install

```bash
uv tool install git+https://github.com/Iezious/code_index.git
```

Installs `code_index` on PATH. Reads per-project config from `docs/.helpers/config.toml`.

### Update

```bash
uv tool upgrade code_index
```

Pulls the latest from the same source URL used at install.

### Pinning to a tag

```bash
uv tool install git+https://github.com/Iezious/code_index.git@v0.1.0
```

Optional, for users who want a stable version rather than tracking `HEAD`.

### Voyage backend (optional)

```bash
uv tool install "git+https://github.com/Iezious/code_index.git[voyage]"
```

Requires `VOYAGE_API_KEY` in the environment.

### For engine development

```bash
uv tool install --editable .
```

If you're hacking on `code_index` itself, clone the repo and use the editable install.

## CLI surface (planned)

```
code_index init
code_index index build
code_index index sync
code_index search "..." --lang lsl --k 10
code_index symbols defs Foo
code_index graph callers Bar
```

See `docs/architecture/cli.md` for the full command surface.
