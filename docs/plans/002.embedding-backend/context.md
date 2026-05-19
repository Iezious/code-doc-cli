# Feature 002 — Embedding backend

This folder plans **Phase 2 — Embedding backend** from [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md). The deliverable is the embeddings package: a structural `EmbeddingBackend` protocol, a working `FastembedBackend` implementation with batching, and a `from_config` factory that dispatches by `embed_backend`. The Voyage backend is a stub-raise here; the real implementation lands in Phase 7.

## Goal

- Stand up `src/code_index/embeddings/` as a package, day one, so Phase 7 can drop `voyage.py` alongside `fastembed.py` with no refactor.
- Provide `EmbeddingBackend` as a structurally-typed Protocol matching [`../../architecture/embeddings.md`](../../architecture/embeddings.md)'s interface section.
- Implement `FastembedBackend` over the `fastembed` library using Jina v2 base code (768-dim, CPU), with the batching loop honoring `embed_batch_size`.
- Implement `from_config(config) -> EmbeddingBackend` that reads `embed_backend`, `embed_model`, `embed_batch_size` off the resolved config, returns `FastembedBackend` for `"fastembed"`, and raises `CodeIndexError(EXIT_USAGE, Kinds.CLI_NOT_IMPLEMENTED, ...)` for `"voyage"`.
- Exercise the real-download cache behavior in tests, using a gitignored `tests/.cache/fastembed/` so CI runs cache between invocations.

## Scope envelope

Strictly Phase 2's bullet list and DoD from `mvp-phases.md`. Out of scope here:

- Voyage backend implementation (Phase 7).
- Wiring the factory into a CLI subcommand or indexer pipeline (Phase 4 walks the tree and calls `from_config`; not this phase).
- Embedding cache keyed on chunk content hash (deferred to v1.1 per [`../../architecture/mvp-scope.md`](../../architecture/mvp-scope.md)).
- `config show` integration (Phase 7).
- Any changes to `errors.py`, `config.py`, `storage/`, `cli.py` from Phase 1 — Phase 2 strictly adds the `embeddings/` package and one `.gitignore` line.

## Architecture inputs (authoritative)

- [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md) — Phase 2 section; bullet list + DoD.
- [`../../architecture/embeddings.md`](../../architecture/embeddings.md) — `EmbeddingBackend` protocol, fastembed default, batching, switching-models stance.
- [`../../architecture/mvp-scope.md`](../../architecture/mvp-scope.md) — Phase 2 ships fastembed only; Voyage is Phase 7.
- [`../../architecture/config.md`](../../architecture/config.md) — `embed_backend`, `embed_model`, `embed_batch_size` keys and defaults.
- [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md) — exit-code table; `backend.*` (codes 20/21/22) is Phase 7. Phase 2 only raises through `cli.not_implemented` (code 1) for the Voyage stub.
- [`../001.foundations/context.md`](../001.foundations/context.md) — Phase 1 framing and shared vocabulary.
- [`../001.foundations/002.errors.md`](../001.foundations/002.errors.md) — `CodeIndexError`, `Kinds.CLI_NOT_IMPLEMENTED`, `EXIT_USAGE`.
- [`../001.foundations/003.config.md`](../001.foundations/003.config.md) — `CodeIndexConfig` shape; `embed_backend` / `embed_model` / `embed_batch_size` fields.
- Root `CLAUDE.md` — Build & Test Commands (verifier reads from here).
- `docs/CLAUDE.md` — markdown conventions; no emojis, no HTML.

## User-confirmed decisions

1. **Module layout: package from day one.** `src/code_index/embeddings/` is a package, not a single module:
   - `__init__.py` — re-exports `EmbeddingBackend`, `from_config`.
   - `protocol.py` — the `EmbeddingBackend` Protocol.
   - `fastembed.py` — `FastembedBackend`.
   - `factory.py` — `from_config(config) -> EmbeddingBackend`.
   Phase 7 drops `voyage.py` into the same package with no refactor.
2. **Integration test strategy: real downloads into a gitignored cache.** Tests point fastembed at `tests/.cache/fastembed/`. The first CI run downloads (~120MB); subsequent runs reuse the cache. Run under the default `uv run pytest` — no `-m slow` marker. Mocked unit tests may exist for non-network behavior (e.g. the batching loop wired against a fake encoder), but cache-population + shape assertions exercise the real download.
3. **Voyage stub in the factory.** When `embed_backend = "voyage"`, the factory raises `CodeIndexError(EXIT_USAGE, Kinds.CLI_NOT_IMPLEMENTED, "voyage backend not available in this build (lands in Phase 7)")`. No new `kind` added — reuses the one Phase 1 introduced. The kind name (`cli.not_implemented`) is technically a slight category abuse here (failure surfaces from a non-CLI module). This is flagged in `outcome.md` for the architect to reconsider before Phase 7 (e.g. rename to `feature.not_implemented` or split the kind by surface).

## Files touched across steps

| Area | Path | Step(s) |
|---|---|---|
| package init | `src/code_index/embeddings/__init__.py` | 001 (create), 002 (edit) |
| protocol | `src/code_index/embeddings/protocol.py` | 001 |
| fastembed impl | `src/code_index/embeddings/fastembed.py` | 001 |
| factory | `src/code_index/embeddings/factory.py` | 002 |
| backend tests | `tests/test_fastembed_backend.py` | 001 |
| factory tests | `tests/test_embedding_factory.py` | 002 |
| repo gitignore | `.gitignore` | 001 (add `tests/.cache/`) |

## Cross-cutting constraints

- **Day-one package layout.** No "single-module then split" refactor in Phase 7. Submodules above are introduced in this phase even though some are minimal.
- **Protocol is structural.** `FastembedBackend` does not inherit from `EmbeddingBackend`; pyright validates assignability structurally. The protocol carries `name: str`, `dim: int`, and `encode(self, texts: list[str]) -> np.ndarray`. Dtype is not pinned by the protocol; the returned array is whatever fastembed produces (typically `float32`).
- **Batching honors config.** `FastembedBackend.encode` slices `texts` by `batch_size` and concatenates results along axis 0. No off-by-one in the tail batch.
- **No network calls in factory tests.** Factory tests mock the `FastembedBackend` constructor; only `tests/test_fastembed_backend.py` performs real downloads.
- **No changes to Phase 1 modules.** The factory consumes a resolved `CodeIndexConfig` (already provided by Phase 1's `config.py`). Phase 2 does not modify `errors.py`, `config.py`, `storage/`, `cli.py`.
- **No emojis, no HTML; forward slashes** in any path strings in tests or docs.

## Shared vocabulary

- **Backend** — an object satisfying `EmbeddingBackend` (`name`, `dim`, `encode`).
- **Backend name** — the `name` attribute, formatted `"<backend>:<model-shortname>"`, e.g. `"fastembed:jina-code-v2"`. Used in logging and surfaced to `meta.embed_model` in later phases.
- **Cache dir** — directory where fastembed stores downloaded ONNX model files. In tests, `tests/.cache/fastembed/`. In production, fastembed's library default (under user home).
- **Resolved config** — the `CodeIndexConfig` instance produced by `load_config` in Phase 1's `config.py`. The factory reads `embed_backend`, `embed_model`, `embed_batch_size` off it.
- **Stub raise** — the factory's behavior for `embed_backend = "voyage"`: raises `CodeIndexError` with `kind = "cli.not_implemented"`. Not an implementation.

## Dependency direction

```
001 fastembed-backend  (protocol + impl, real-download tests)
   |
002 factory            (config dispatch, voyage stub-raise)
```

001 introduces `EmbeddingBackend` and `FastembedBackend`. 002 imports both and adds `from_config`; also edits `__init__.py` to re-export `from_config`. Each step also depends on Phase 1: step 001 imports nothing from Phase 1 directly (it only needs the package skeleton); step 002 imports `CodeIndexError`, `Kinds`, and `EXIT_USAGE` from `code_index.errors` and the `CodeIndexConfig` type from `code_index.config`.

## Phase 2 DoD (the contract)

Per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md):

- `uv sync --extra dev` succeeds (no new mandatory deps — `fastembed` is already pulled by Phase 1's `pyproject.toml`).
- `uv run pytest` passes, including the real-download integration tests. First CI run is slow (~120MB download); subsequent runs reuse `tests/.cache/fastembed/`.
- `uv run ruff check` passes.
- `uv run pyright` passes. `FastembedBackend` satisfies the `EmbeddingBackend` Protocol structurally.
- `FastembedBackend("jinaai/jina-embeddings-v2-base-code").encode(["foo", "bar"]).shape == (2, 768)`.
- `backend.dim == 768`.
- First instantiation downloads model files to `tests/.cache/fastembed/`; second instantiation in the same session reuses the cache.
- `from_config(config)` returns a `FastembedBackend` configured from `embed_model` and `embed_batch_size` when `embed_backend == "fastembed"`.
- `from_config(config)` raises `CodeIndexError` with `code == EXIT_USAGE` and `kind == Kinds.CLI_NOT_IMPLEMENTED` when `embed_backend == "voyage"`; message mentions Phase 7.
