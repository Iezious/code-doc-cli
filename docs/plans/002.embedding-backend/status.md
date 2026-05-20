# Feature 002 — embedding-backend

| Step | File                          | Status  | Verifier | Date |
|------|-------------------------------|---------|----------|------|
| 001  | `001.fastembed-backend.md`    | done    | PASS     | 2026-05-19 |
| 002  | `002.factory.md`              | done    | PASS     | 2026-05-19 |

## Files Changed

### Step 001 — Fastembed backend
- `src/code_index/embeddings/__init__.py` — package init; re-exports `EmbeddingBackend` and `FastembedBackend`
- `src/code_index/embeddings/protocol.py` — `EmbeddingBackend` runtime-checkable Protocol
- `src/code_index/embeddings/fastembed.py` — `FastembedBackend` over `fastembed.TextEmbedding` with batching loop
- `tests/test_fastembed_backend.py` — real-download integration tests against `tests/.cache/fastembed/`
- `.gitignore` — added `tests/.cache/` for the persistent fastembed model cache

### Step 002 — Factory
- `src/code_index/embeddings/factory.py` — `from_config(config)` dispatcher; voyage branch raises `CodeIndexError(EXIT_USAGE, Kinds.CLI_NOT_IMPLEMENTED, ...)`
- `src/code_index/embeddings/__init__.py` — re-exports `from_config` alongside `EmbeddingBackend` and `FastembedBackend`
- `tests/test_embedding_factory.py` — factory tests monkeypatching `FastembedBackend`; no real downloads

## Notes & Issues

_populated by the coder when worth saying_

## Bug Fixes

_populated post-completion by `/bug-fixer` if needed_
