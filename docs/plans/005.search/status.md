# Feature 005 — search

| Step | File                       | Status  | Verifier | Date |
|------|----------------------------|---------|----------|------|
| 001  | `001.query-pipeline.md`    | done    | PASS     | 2026-05-21 |
| 002  | `002.search-cli.md`        | done    | PASS     | 2026-05-21 |

## Files Changed

### Step 001 — query-pipeline
- `src/code_index/search.py` — new module: hybrid BM25 + dense retrieval with RRF fusion, filter-on-both-pools, mode selection, `SearchResult`/`SearchFilters` dataclasses.
- `src/code_index/storage/__init__.py` — added `verify_index_compat(conn, backend)` for embed-model/dim drift loud-fail.
- `tests/test_search_pipeline.py` — new unit tests using a synthetic 4-dim index and an in-memory `FakeBackend`.
- `tests/test_storage_compat.py` — new tests for `verify_index_compat` (ok, model mismatch, dim mismatch, missing meta).

### Step 002 — search-cli
- `src/code_index/cli.py` — replaced the Phase 1 `search` stub with the full implementation: flag declaration per the step's signature block, `--lang` validation against `active_plugins(config).names()`, mode-skip semantics (`bm25` does not instantiate the backend), `verify_index_compat` before search under `dense`/`hybrid`, and text-stanza / JSON-document formatters. `--mode` uses an `enum.StrEnum` so Typer rejects unknown values with usage exit code 2 (per `002.context.md`).
- `tests/test_search_cli.py` — new E2E tests against a session-scoped polyglot fixture build that reuses the Phase 2 fastembed cache; covers every DoD bullet (symbol-name + conceptual queries, mode-skip backend instantiation, JSON shape, zero-results, `--lang`/`--kind`/`--path` filters, missing-index, embed_model drift, bad enum, `--bm25-k 0`).
- `tests/fixtures/projects/polyglot_minimal/main.py` — augmented with `def search_me() -> None:` carrying the docstring "Handle dropped websocket sessions with a reconnection loop." (Option A from `002.context.md`); provides both the symbol-name and conceptual-query targets in one chunk without disturbing Phase 4's `>=1` per-language assertions.
- `tests/test_cli.py` — removed `["search", "foo"]` from the stub-envelope parametrize (mirroring the Phase 4 precedent for `init` and `index build`); search is no longer a stub.

## Notes & Issues

_populated by the coder when worth saying_
