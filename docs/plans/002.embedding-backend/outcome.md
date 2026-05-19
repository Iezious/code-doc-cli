# Outcome — feature 002 embedding backend

Architecture deltas this feature implies. Applied by `/architect` at finalization.

## Planner section

### `docs/architecture/embeddings.md`

- **Target section:** "Backend interface" or "Implications" (architect picks). **Low priority; drop if the architect prefers `embeddings.md` stays implementation-neutral.**
- **Change:** add a sentence noting that the Phase 2 backend is provided as `code_index.embeddings.FastembedBackend` and that the factory entry point is `code_index.embeddings.from_config(config)`.
- **Reason:** records the concrete import path so consumers (the indexer in Phase 4, `config show` in Phase 7) have a single canonical entry point to wire against. Non-load-bearing — the protocol contract remains the doc's authoritative surface.

### `docs/architecture/errors-and-exit-codes.md`

- **Target section:** "Enumerated failure surface" → the "CLI scaffolding (code 1)" subsection added by Feature 001.
- **Change:** note that `cli.not_implemented` is now also raised by the embeddings factory when `embed_backend = "voyage"`, until Phase 7 lands the Voyage backend. Architect-callable question: rename the kind to something surface-neutral (`feature.not_implemented` or split into `cli.not_implemented` + `backend.not_implemented`) before Phase 7 plans, or accept the slight category mismatch and let the kind disappear when Phase 7 ships. Either way, this entry in the enumerated failure surface should reflect the second consumer.
- **Reason:** the kind was introduced as CLI-only in Phase 1; Phase 2 introduces a second consumer outside the CLI surface. Surfacing this now avoids accumulating more surfaces silently before the rename decision is made.

### `docs/architecture/mvp-phases.md`

- **No change.** Phase 2's DoD is met as-stated by this plan. No reordering, scope tightening, or scope expansion.

## Scope summary (for the architect's record)

Phase 2 ships: the `code_index.embeddings` package (`protocol.py`, `fastembed.py`, `factory.py`, `__init__.py`), real-download integration tests against a gitignored `tests/.cache/fastembed/`, and a Voyage stub-raise in the factory using the existing `cli.not_implemented` kind. Phase 2 DoD per `mvp-phases.md`:

- `uv sync --extra dev` succeeds (no new mandatory deps).
- `uv run pytest` / `uv run ruff check` / `uv run pyright` all pass.
- `FastembedBackend("jinaai/jina-embeddings-v2-base-code").encode(["foo", "bar"]).shape == (2, 768)`.
- First-run downloads cache under `tests/.cache/fastembed/`; second run reuses the cache.
- `from_config(config)` returns `FastembedBackend` for `embed_backend="fastembed"` and raises `CodeIndexError(EXIT_USAGE, Kinds.CLI_NOT_IMPLEMENTED, ...)` for `embed_backend="voyage"`.
