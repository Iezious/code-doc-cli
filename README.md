# code_index

Universal codebase index and hybrid semantic/lexical search, built to power Claude Code documentation-generation pipelines across polyglot repositories.

## What it is

A CLI tool (`code_index`) that walks a codebase, chunks it AST-aware per language, embeds the chunks locally, and stores everything in a per-project SQLite index alongside BM25 full-text search and a lightweight symbol/dep graph. Agents and humans query it the same way.

Supported languages: F#, C#, JavaScript, TypeScript, Go, Python, LSL.

## Why it exists

For large polyglot codebases, asking Claude agents to read raw source for every documentation pass is slow, expensive, and non-deterministic. Building the retrieval layer once — and querying it many times — keeps the orchestrator's context lean, makes follow-up scrapes near-free, and gives the team a durable search artifact.

## Status

MVP shipped. Current version: `0.2.1` (patch: fixes fastembed ONNX OOM on long chunks by capping per-text tokens at 1024 and lowering default `embed_batch_size` from 32 to 16; adds `chunks_chunked` to the `index build` / `index rebuild` JSON shape; fixes init JSON refuse-path Windows backslashes). Tags `v0.1.0` and `v0.2.0` are on prior milestones; `v0.2.1` follows this commit. See `docs/architecture/` for design decisions, `docs/plans/` for delivered features, and `docs/CLAUDE.md` for the documentation layout.

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
uv tool install git+https://github.com/Iezious/code_index.git@v0.2.1
```

Optional, for users who want a stable version rather than tracking `HEAD`.

### For engine development

```bash
uv tool install --editable .
```

If you're hacking on `code_index` itself, clone the repo and use the editable install. Build/test/typecheck commands live in `CLAUDE.md`.

### GPU acceleration (CUDA)

The base install keeps `fastembed` (CPU) as the default hard dependency, so the zero-config, offline CPU path is unchanged — you get CPU embedding out of the box with no extra steps.

GPU acceleration is a manual package swap. Replace `fastembed` with `fastembed-gpu`, then point `code_index` at CUDA:

```bash
uv pip install fastembed-gpu          # replaces fastembed
CODE_INDEX_DEVICE=cuda code_index index build
```

`fastembed` and `fastembed-gpu` are mutually-exclusive PyPI distributions: they share the same `fastembed` import namespace and pull mutually-exclusive onnxruntime builds (`onnxruntime` CPU vs `onnxruntime-gpu`). Install one or the other, never both. Because an additive install extra cannot satisfy both cleanly, there is intentionally no `[gpu]` extra and `pyproject.toml` is unchanged — the swap is manual by design.

The `CODE_INDEX_DEVICE` env var selects where the model runs:

- `auto` (default): use CUDA if the ONNX runtime offers a CUDA provider, else CPU. Silent — no warning.
- `cuda`: explicit request. If the CUDA provider is unavailable at runtime, warn on stderr and fall back to CPU.
- `cpu`: force CPU even on a GPU box.

The env var only selects a provider; whether CUDA is actually available depends on which onnxruntime build is installed. Setting `CODE_INDEX_DEVICE=cuda` on a box with only the base `fastembed` means the CUDA provider is not registered, so `code_index` falls back to CPU with a one-line stderr warning.

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
