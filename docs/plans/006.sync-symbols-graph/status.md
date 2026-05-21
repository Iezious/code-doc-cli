# Feature 006 — sync-symbols-graph

| Step | File                       | Status  | Verifier | Date |
|------|----------------------------|---------|----------|------|
| 001  | `001.sync-engine.md`       | done    | PASS     | 2026-05-21 |
| 002  | `002.rebuild-cli.md`       | done    | PASS     | 2026-05-21 |
| 003  | `003.symbols.md`           | done    | PASS     | 2026-05-21 |
| 004  | `004.graph.md`             | done    | PASS     | 2026-05-21 |
| 005  | `005.dod-integration.md`   | done    | PASS     | 2026-05-21 |

Steps 001 / 002 / 003 / 004 are mutually independent and may be dispatched in parallel. Step 005 depends on all four.

## Files Changed

### Step 001 — sync engine and `index sync` CLI
- `src/code_index/sync.py` — new module: `SyncResult` dataclass, `delete_file_rows` per-file delete helper, and the `sync(...)` engine entry point with per-file insert (option 2 from `001.context.md`).
- `src/code_index/cli.py` — replaced the `index sync` stub with a thin wrapper; added the shared `_preflight(ctx)` helper (module-level in `cli.py` per `001.context.md`) for reuse by steps 003 and 004.
- `tests/test_sync_engine.py` — new: seven scenarios (no-op, new, mtime-change, size-only change, removed, mixed, `delete_file_rows` unit test).
- `tests/test_sync_cli.py` — new: missing-index, embed-model mismatch, embed-dim mismatch, JSON summary shape, plus a text-mode smoke test.
- `tests/test_cli.py` — removed `["index", "sync"]` from the stub parametrize and switched the text-mode stub test to `["index", "rebuild"]` (still a stub until step 002).

### Step 002 — `index rebuild` CLI
- `src/code_index/cli.py` — replaced the `index rebuild` stub with a thin `indexer.build` wrapper gated behind `--yes`; pre-flight model/dim check intentionally omitted per `context.md` decision 7; raises `CodeIndexError(EXIT_USAGE, "usage.confirmation_required", ...)` on missing `--yes` (raise-site literal per `002.context.md`).
- `tests/test_rebuild_cli.py` — new: happy path (row counts unchanged), missing-`--yes` envelope (JSON + text mode), JSON summary shape, no pre-flight model check (rebuild succeeds against mismatched `meta.embed_model`), and no-index-yet (degenerate to build).
- `tests/test_cli.py` — removed `["index", "rebuild"]` from the stub parametrize and switched the text-mode stub test to `["symbols", "defs", "foo"]` (still a stub until step 003).

### Step 003 — symbols module and CLI
- `src/code_index/symbols.py` — new module: frozen `SymbolHit` dataclass and `query_symbols(conn, name, *, kind, exact=False, language=None)` joining `symbols` → `chunks`; uses `PRAGMA case_sensitive_like = ON` (option a per `003.context.md`) and parameterized LIKE / equality; LIKE-wildcard escaping deferred per the per-step context.
- `src/code_index/cli.py` — replaced the `symbols defs` and `symbols refs` stubs with thin wrappers (shared `_run_symbols_query` body) reusing the step 001 `_preflight(ctx)` helper; added `_write_symbols_json` / `_write_symbols_text` emitters matching the `context.md` JSON shape and `003.context.md` text format.
- `tests/test_symbols_query.py` — new: eight SQL cases (substring, exact, case sensitivity for both modes, language filter, kind def vs ref, scope surfacing incl. `None`, empty DB, sort by `(path, line)`).
- `tests/test_symbols_cli.py` — new: missing-index envelope, embed-model mismatch envelope, JSON shape (exact key set), text shape, empty-result (`[]` under JSON, empty stdout under text).
- `tests/test_cli.py` — removed `symbols defs` / `symbols refs` from the stub parametrize and switched the text-mode stub test to `["graph", "callers", "foo"]` (still a stub until step 004).

### Step 004 — graph module and CLI
- `src/code_index/graph.py` — new module: frozen `CallerHit` / `DepHit` dataclasses and `query_callers(conn, symbol, *, exact=False, language=None)` / `query_deps(conn, path, *, language=None)` joining `edges` → `chunks`; callers uses `PRAGMA case_sensitive_like = ON` (option a per `003.context.md`/`004.context.md`); deps uses strict equality on `chunks.path` (decision 4 — no globbing, no substring). Unresolved `dst_name` values pass through; `meta` surfaced as raw string-or-`None` per `004.context.md`.
- `src/code_index/cli.py` — replaced the `graph callers` and `graph deps` stubs with thin wrappers reusing the step 001 `_preflight(ctx)` helper; added `_write_callers_json` / `_write_callers_text` / `_write_deps_json` / `_write_deps_text` emitters matching the `context.md` JSON shapes and `004.graph.md` text formats. Removed the now-unused `_stub(...)` helper (last stub call site was these two commands; pyright reportUnusedFunction would otherwise fail).
- `tests/test_graph_query.py` — new: 12 SQL cases (callers substring/exact/case/lang; deps exact-path/no-globbing/no-substring/unresolved/meta-string/meta-null; sort order callers and deps).
- `tests/test_graph_cli.py` — new: missing-index envelope, embed-model mismatch envelope, JSON shape (callers and deps separately, exact key set), text shape (both subcommands), empty-result split into callers and deps cases (`[]` under JSON, empty stdout under text).
- `tests/test_cli.py` — removed the stub parametrize block and the text-mode stub test entirely (no remaining stubs once `graph callers|deps` are real); left a comment block in their place pointing at the prior pattern in case a future phase reintroduces a stub.

### Step 005 — end-to-end Phase 6 DoD integration test
- `tests/test_phase6_dod.py` — new: single end-to-end test driving `init` → `index build` → mutate `main.py` (force-advanced mtime via `os.utime` per `005.context.md`) → `index sync` (JSON) → `symbols defs newly_added_symbol` (JSON) → `symbols refs <db-read-name-or-empty>` (JSON) → `graph callers <db-read-target> --exact` (JSON) → `graph deps main.py` (JSON) → `index rebuild --yes` (JSON), against the Phase 4 polyglot fixture; uses `_invoke` and only the public `code_index.storage.open_index` for DB snapshots (no direct import of `code_index.sync` / `symbols` / `graph`); `warm_fastembed` fixture patches `from_config` in `embeddings`, `indexer`, and `sync` to redirect to `tests/.cache/fastembed/` so CI reuses the Phase 2 model cache.

## Bug Fixes

### Step 005 — DoD test imported `code_index.sync` to redirect `from_config` (2026-05-21)
- `src/code_index/sync.py` — replaced `from code_index.embeddings import from_config` with an `embeddings` module import and a call-time `embeddings.from_config(config)` lookup so a single patch on `embeddings.from_config` redirects the backend; no behavior change. `indexer.py` left as-is (Phase 4 tests `test_indexer_pipeline.py` / `test_index_build_cli.py` rely on its existing `indexer.from_config` binding).
- `tests/test_phase6_dod.py` — dropped `from code_index import sync as sync_module` and its monkeypatch (now redundant given sync.py's dynamic lookup); resolved `_FASTEMBED_CACHE` to an absolute path so the shared `tests/.cache/fastembed/` cache survives `monkeypatch.chdir(tmp_path)` (bonus fix per the verifier's advisory).
- `tests/test_sync_engine.py` — removed the now-stale `monkeypatch.setattr(sync_module, "from_config", ...)` line; the `embeddings.from_config` patch is sufficient.
- `tests/test_sync_cli.py` — same: dropped the `sync_module.from_config` patch.
- `tests/test_symbols_cli.py` — same: dropped the `sync_module.from_config` patch.
- `tests/test_graph_cli.py` — same: dropped the `sync_module.from_config` patch.

## Notes & Issues

_populated by the coder when worth saying_
