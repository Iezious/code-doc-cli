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

The embedding backend ships as one of two mutually-exclusive extras — pick the one that matches your hardware. A bare install with no extra has **no** embedding backend.

CPU (default, zero-config, works everywhere):

```bash
uv tool install "code_index[cpu] @ git+https://github.com/Iezious/code_index.git"
```

GPU (CUDA, recommended on an NVIDIA box — bundles `fastembed-gpu` + the CUDA/cuDNN/cuBLAS wheels):

```bash
uv tool install "code_index[gpu] @ git+https://github.com/Iezious/code_index.git"
CODE_INDEX_DEVICE=cuda code_index index build
```

Both install `code_index` on PATH and read per-project config from `docs/.helpers/config.toml`. See [GPU acceleration](#gpu-acceleration-cuda) below for how device selection works.

### Update

```bash
uv tool upgrade code_index
```

Pulls the latest from the same source URL (and extra) used at install.

### Pinning to a tag

```bash
uv tool install "code_index[cpu] @ git+https://github.com/Iezious/code_index.git@v0.2.1"
```

Optional, for users who want a stable version rather than tracking `HEAD`. Swap `[cpu]` for `[gpu]` as needed.

### For engine development

```bash
uv tool install --editable ".[cpu]"     # or ".[gpu]" on a CUDA box
```

If you're hacking on `code_index` itself, clone the repo and use the editable install with an explicit backend extra. Build/test/typecheck commands live in `CLAUDE.md`.

### GPU acceleration (CUDA)

`fastembed` (CPU) and `fastembed-gpu` are mutually-exclusive PyPI distributions: they share the `fastembed` import namespace and pull mutually-exclusive onnxruntime builds (`onnxruntime` CPU vs `onnxruntime-gpu`), so exactly one must be installed. That is why the backend is split into the `[cpu]` and `[gpu]` install extras above rather than a single base dependency — `pyproject.toml` declares them as `[tool.uv]` conflicts so they can never be resolved together.

The `[gpu]` extra additionally bundles the `nvidia-cudnn-cu12` / `nvidia-cublas-cu12` / `nvidia-cuda-nvrtc-cu12` wheels, and `code_index` calls `onnxruntime.preload_dlls()` at backend startup to load them — so a `[gpu]` install works out of the box on Windows without manually putting cuDNN on `PATH`.

Once installed with `[gpu]`, the `CODE_INDEX_DEVICE` env var selects where the model runs:

- `auto` (default): use CUDA if the ONNX runtime offers a CUDA provider, else CPU. Silent — no warning.
- `cuda`: explicit request. If the CUDA provider is unavailable at runtime, warn on stderr and fall back to CPU.
- `cpu`: force CPU even on a GPU box.

The env var only selects a provider; whether CUDA is actually available depends on which extra you installed. Setting `CODE_INDEX_DEVICE=cuda` on a `[cpu]` install means the CUDA provider is not registered, so `code_index` falls back to CPU with a one-line stderr warning.

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
