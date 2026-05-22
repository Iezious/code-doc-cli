# code_index

Universal codebase index and hybrid semantic/lexical search, built to power Claude Code documentation-generation pipelines across polyglot repositories.

## What it is

A CLI tool (`code_index`) that walks a codebase, chunks it AST-aware per language, embeds the chunks locally, and stores everything in a per-project SQLite index alongside BM25 full-text search and a lightweight symbol/dep graph. Agents and humans query it the same way.

Supported languages: F#, C#, JavaScript, TypeScript, Go, Python, LSL.

## Why it exists

For large polyglot codebases, asking Claude agents to read raw source for every documentation pass is slow, expensive, and non-deterministic. Building the retrieval layer once — and querying it many times — keeps the orchestrator's context lean, makes follow-up scrapes near-free, and gives the team a durable search artifact.

## Status

MVP shipped. Current version: `0.2.0` (adds `code_index usage` subcommand + ships agent docs inside the wheel). `v0.1.0` is tagged on the MVP-complete commit; the `v0.2.0` tag will follow shortly. See `docs/architecture/` for design decisions, `docs/plans/` for delivered features, and `docs/CLAUDE.md` for the documentation layout.

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
uv tool install git+https://github.com/Iezious/code_index.git@v0.2.0
```

Optional, for users who want a stable version rather than tracking `HEAD`.

### For engine development

```bash
uv tool install --editable .
```

If you're hacking on `code_index` itself, clone the repo and use the editable install. Build/test/typecheck commands live in `CLAUDE.md`.

## Quick start

```bash
cd <your-project>
code_index init                          # scaffold docs/.helpers/{config.toml,.gitignore}
code_index index build                   # walk, chunk, embed, store
code_index search "where do we handle dropped sessions" --format json
code_index symbols defs FastembedBackend --exact
code_index graph callers IEnumerable --lang csharp
```

After source edits, run `code_index index sync` to update incrementally. After changing `embed_model` in config, run `code_index index rebuild --yes`.

## Documentation

Agent-facing docs ship inside the wheel and are discoverable at runtime:

```bash
code_index usage                         # index page listing all 9 topics
code_index usage search                  # detail page for a subcommand
code_index --format json usage init      # machine-readable
```

The same docs live in-tree under [`src/code_index/usage/`](src/code_index/usage/). Design rationale lives under `docs/architecture/`.

## CLI surface

`init` · `index build|sync|rebuild` · `search` · `symbols defs|refs` · `graph callers|deps` · `config show` · `usage`

See [`docs/architecture/cli.md`](docs/architecture/cli.md) for the full contract or run `code_index usage` for the agent reference.
