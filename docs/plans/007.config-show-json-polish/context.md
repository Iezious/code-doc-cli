# Feature 007 — config-show-json-polish

Phase 7 of the MVP per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md). The final MVP phase. Delivers the real `code_index config show` body (replacing Phase 1's stubbed-shape implementation), pins the two remaining JSON shapes (`init`, `config show`), wraps native fastembed exceptions in `CodeIndexError`, formalizes two new `Kinds` entries (`USAGE_CONFIRMATION_REQUIRED`, `CLI_BAD_ENUM`) that were previously raised as free strings or under the wrong kind, and verifies via integration test that every MVP subcommand round-trips through `json.loads` on both success and at least one failure path.

This is the cleanup phase. No new modules, no schema changes, no new subcommands. Three production files are touched (`cli.py`, `embeddings.py`, `errors.py`) plus tests.

## Goal

- Replace the Phase 1 `config show` body with a diagnostic implementation that reads `meta.schema_version`, `meta.code_index_version`, `meta.embed_model`, `meta.embed_dim` and prints them alongside the resolved config. The subcommand **never raises** on missing index, schema mismatch, model mismatch, or dim mismatch — it reports the data instead.
- Pin the `init` JSON output shape (currently unpinned anywhere) and pin the `config show` JSON shape (extended from Phase 1's `{"config": {...}}` to add an `"index"` sibling).
- Wrap native fastembed exceptions raised from `from_config(...)` and `FastembedBackend.__init__` / `.encode(...)` in `CodeIndexError` carrying `Kinds.BACKEND_MODEL_DOWNLOAD_FAILED` (code 20) for instantiation / model-download failures and `Kinds.BACKEND_ENCODE_FAILED` (code 20) for encode-time failures. Both kinds are already registered in Phase 1's `Kinds` registry; this phase wires the producers.
- Register two new `Kinds` constants and update the existing raise sites:
  - `USAGE_CONFIRMATION_REQUIRED = "usage.confirmation_required"` (code 1, `EXIT_USAGE`) — replaces the free-string kind Phase 6's `index rebuild` raise site uses without `--yes`.
  - `CLI_BAD_ENUM = "cli.bad_enum"` (code 1, `EXIT_USAGE`) — replaces the `Kinds.CONFIG_BAD_ENUM` Phase 5 currently uses for `--mode` enum validation. Distinguishes CLI-flag enum violations from config-file enum violations (the latter keeps `config.bad_enum`).
- Add a cross-subcommand integration test that asserts every MVP subcommand's `--format json` stdout round-trips through `json.loads` and emits a parseable error envelope on at least one failure mode.

## Scope envelope

Strictly Phase 7's bullets from `mvp-phases.md` plus the four polish strands enumerated under "User-confirmed decisions" below. Out of scope:

- `code_index doctor` (deferred to v1.1 per [`../../architecture/mvp-scope.md`](../../architecture/mvp-scope.md)).
- A uniform `{"data": ...}` envelope wrapper across subcommands (rejected; each subcommand keeps the shape its originating phase pinned — see decision 2).
- Re-parsing `graph deps`'s `meta` JSON string field (rejected; stays a raw string per decision 7).
- Voyage backend (roadmap'd; see [`../../architecture/roadmap.md`](../../architecture/roadmap.md)).
- Embedding cache by content hash (roadmap; see [`../../architecture/embeddings.md`](../../architecture/embeddings.md) "Caching").
- Architecture-doc fold-ins from prior phases' `outcome.md` files (those are `/architect` finalization work, not Phase 7 plan scope).
- Schema changes. No migration in this phase.
- New top-level modules. Only `cli.py`, `embeddings.py`, `errors.py` change.
- Changes to Phases 1–6 step files. Phase 7 builds on top; it does not amend prior plans.

## Architecture inputs (authoritative)

Read these before any step. Phase 7 introduces no new design decisions; everything below this line is implementation against pinned design.

- [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md) — Phase 7 section. DoD is the scope contract: "every MVP subcommand under `--format json` round-trips through `json.loads`; the same subcommands under failure conditions emit a parseable error envelope."
- [`../../architecture/cli.md`](../../architecture/cli.md) — `config show` section, output streams and logging, `--format json` cross-cutting behavior.
- [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md) — JSON error envelope shape, exit-code table, "Enumerated failure surface", additive-kind discipline. The two new kinds and the two newly-producing kinds (`backend.model_download_failed`, `backend.encode_failed`) all live under this surface.
- [`../../architecture/config.md`](../../architecture/config.md) — resolved-config shape; what `config show` prints.
- [`../../architecture/storage.md`](../../architecture/storage.md) — `meta` key enumeration: `schema_version`, `code_index_version`, `embed_model`, `embed_dim`. (`last_commit` was removed by the 2026-05-19 revision; do not reference it.)
- [`../../architecture/embeddings.md`](../../architecture/embeddings.md) — single-backend reality (`fastembed` only in MVP); `EmbeddingBackend` Protocol; backend init contract.
- Root `CLAUDE.md` — Build & Test Commands.
- `docs/CLAUDE.md` — markdown conventions; no emojis, no HTML.

## User-confirmed decisions

1. **`config show` is diagnostic, not gating.** Reads `meta.embed_model`, `meta.embed_dim`, `meta.schema_version`, `meta.code_index_version` and prints them alongside the configured values. **Never raises** on:
   - Missing index file → emits `"index": null` (JSON) or `index: not built` (text), exit 0.
   - Model mismatch (`config.embed_model != meta.embed_model`) → prints both values, exit 0. Text mode may add a `[mismatch]` marker on the affected line; not required.
   - Dim mismatch → same.
   - Schema mismatch → same. This is the **only** subcommand that does not gate on schema mismatch; every other subcommand gates via `open_index`'s schema check. `config show` opens the index with `check_version=False` (or a hand-rolled gentle open) so the read never raises.

   The only failures `config show` raises are:
   - Config discovery failure: no `docs/.helpers/config.toml` discovered → `CodeIndexError(EXIT_INDEX_MISSING, Kinds.INDEX_MISSING, "no docs/.helpers/config.toml found; run `code_index init`")`. This reuses the same kind Phase 1 pinned for the "config not found" case.
   - Config validation failure: `load_config(...)` raises (malformed TOML, version mismatch, etc.) — let propagate; the boundary handler routes.
   - Index file present but unparseable (e.g. not a valid SQLite database) → `CodeIndexError(EXIT_INDEX_SCHEMA, Kinds.INDEX_UNREADABLE, ...)`. If the read connection raises before any `meta` row can be fetched, the wrapper translates the raw `sqlite3.DatabaseError` into this `kind`.

2. **Heterogeneous JSON shapes preserved.** No uniform `{"data": ...}` envelope wrapper. Each subcommand keeps the shape pinned by its originating phase. Phase 7's job is to **verify** each shape round-trips through `json.loads` and to **document each shape inline per subcommand in cli.md** via `outcome.md` candidate items. Phase 6's commitment ("shape fixed from day one") is honored — Phase 7 does not redesign existing shapes.

3. **`init` JSON shape** (newly pinned by Phase 7):

   ```json
   {
     "config_path": "/abs/path/docs/.helpers/config.toml",
     "gitignore_path": "/abs/path/docs/.helpers/.gitignore",
     "project": "my-project",
     "force_used": false
   }
   ```

   Mirrors the values Phase 4's `init` body already computes. `force_used` is `true` if `--force` was passed and an existing file was overwritten; `false` otherwise (fresh init, or `--force` with no prior file).

4. **`config show` JSON shape** extends Phase 1's `{"config": {...}}` to:

   ```json
   {
     "config": {
       "version": "...",
       "project": "...",
       "project_root": "/abs/path",
       "config_path": "/abs/path/docs/.helpers/config.toml",
       "roots": ["/abs/path/..."],
       "ignores": ["..."],
       "languages": null,
       "extra_languages": [],
       "embed_backend": "fastembed",
       "embed_model": "jinaai/jina-embeddings-v2-base-code",
       "embed_batch_size": 32
     },
     "index": {
       "schema_version": "1",
       "code_index_version": "0.3.0",
       "embed_model": "jinaai/jina-embeddings-v2-base-code",
       "embed_dim": "768"
     }
   }
   ```

   When the index file is absent, `"index"` is `null`. When mismatch is detected, both `config.embed_model` (in the `config` block) and `index.embed_model` (in the `index` block) are emitted with their actual values; consumers compare. No marker field is added in JSON. Values inside `index` are strings (matching how `meta.value` is stored in SQLite as TEXT); do not coerce numerically.

5. **Backend init wrapping in scope.** `code_index.embeddings.from_config(...)` and `FastembedBackend.__init__` / `.encode(...)` wrap native fastembed exceptions in `CodeIndexError`:
   - Instantiation / model-download failure (any exception raised inside `FastembedBackend.__init__` or `from_config` when constructing the backend) → `Kinds.BACKEND_MODEL_DOWNLOAD_FAILED` (code 20).
   - `encode(...)` runtime failure → `Kinds.BACKEND_ENCODE_FAILED` (code 20).

   Both kinds are already in the Phase 1 `Kinds` registry; Phase 7 adds the producers. Native exception text is preserved in the `detail` dict (`{"cause": str(exc), "type": type(exc).__name__}`); `CodeIndexError` is raised `from exc` so traceback is preserved for the boundary handler's stderr summary.

6. **Two new `Kinds` constants formalized**, both code 1 / `EXIT_USAGE`:
   - `USAGE_CONFIRMATION_REQUIRED = "usage.confirmation_required"` — replaces the free-string `kind` Phase 6's `index rebuild` raise site uses without `--yes`. See `006.sync-symbols-graph/002.rebuild-cli.md` line 28 and line 44 — the current code emits the bare string; Phase 7 promotes to a registered constant.
   - `CLI_BAD_ENUM = "cli.bad_enum"` — replaces the `Kinds.CONFIG_BAD_ENUM` Phase 5 currently uses for `--mode` enum validation. See `005.search/002.context.md` lines 33–54 — the planner there picked `CONFIG_BAD_ENUM` with a recommended-defer-to-Phase-7 note. Phase 7 cleans this up. CLI-flag enum violations now use `cli.bad_enum`; config-file enum violations (`embed_backend` value not in allowed set) keep `config.bad_enum` (code 2).

   Both new kinds go into the `Kinds` class in `errors.py`. Both are recorded in `outcome.md` for the architect to add to `errors-and-exit-codes.md`'s "Enumerated failure surface" — `usage.confirmation_required` under a new "Usage (code 1)" subsection (or extending the existing CLI-scaffolding subsection from Phase 1's outcome), and `cli.bad_enum` in the same place.

7. **`graph deps`'s `meta` field stays a JSON string.** Phase 7 does not re-parse it. The shape Phase 6 pinned (`"meta": null` or `"meta": "<json-string>"`) is the final MVP contract. Phase 7's integration test only asserts `json.loads(stdout)` succeeds on the outer document, not on `meta`'s contents.

8. **Existing per-phase outcome.md → cli.md fold-ins (from phases 1, 4, 5, 6) are NOT Phase 7's responsibility.** Those land via `/architect` finalization passes after each phase ships. Phase 7's `outcome.md` proposes its own cli.md deltas (for the two newly-pinned JSON shapes and for `config show`'s diagnostic semantics), not the other phases' deltas.

## Files touched across steps

| Area | Path | Step(s) |
|---|---|---|
| CLI app | `src/code_index/cli.py` | 001 (config show body), 002 (init JSON branch), 004 (search `--mode` kind + index rebuild `--yes` kind) |
| embeddings backend | `src/code_index/embeddings.py` (or `embeddings/` package per Phase 2 layout: `embeddings/factory.py` and `embeddings/fastembed.py`) | 003 |
| errors module | `src/code_index/errors.py` | 004 |
| tests | `tests/test_config_show.py`, `tests/test_init_json.py`, `tests/test_backend_init_wrapping.py`, `tests/test_new_kinds.py`, `tests/test_json_roundtrip_dod.py` | 001–005 |

Per Phase 2's planner decision, embeddings is a package (`src/code_index/embeddings/`), not a single module. The "Module layout" pointer from the briefing reads `src/code_index/embeddings.py` as a convenience; the actual touch site is `embeddings/factory.py` (for `from_config`) and `embeddings/fastembed.py` (for `FastembedBackend.__init__` and `.encode`). Step 003 confirms the path in `003.context.md`.

## Cross-cutting constraints

- **Stream discipline (per `cli.md`).** Results to stdout; warnings / progress / errors-in-text-mode to stderr via the Phase 1 sanctioned writers (`write_result_stdout`, `write_log_stderr`, `write_error_envelope_stdout`, `write_error_summary_stderr`). Subcommand code never calls `print` directly.
- **`config show` never raises on index state.** Missing, schema-mismatched, model-mismatched, or dim-mismatched indexes are reported with `"index": null` or the mismatched values, exit 0. This is the only subcommand with this carve-out; every other Phase 6/5 subcommand still gates via `open_index`'s schema check and the embedding-compat check.
- **Backend wrapping respects the boundary handler.** `CodeIndexError` raised from `from_config` or `encode` propagates to the boundary handler unchanged; no subcommand catches and re-raises with a different kind. The handler is the single sink.
- **Additive `Kinds` discipline.** New kinds are appended to the `Kinds` class; existing entries are not renamed. Per `errors-and-exit-codes.md` "Implications": renaming a `kind` is a major-version break.
- **Forward slashes** in any path strings emitted to JSON or stderr.
- **No emojis, no HTML** in any file.
- **No schema changes.** Phase 7 reads `meta` but does not bump `schema_version` or add new keys.
- **JSON output is exactly one document per stdout.** Both success and error envelopes are single-document. The DoD integration test (step 005) enforces this via `json.loads(stdout)` rather than line-iterating.

## Prior-phase artifacts this phase consumes

### From Phase 1 (`docs/plans/001.foundations/`)

- `code_index.errors`:
  - `CodeIndexError(code: int, kind: str, message: str, detail: dict | None = None)` with `.envelope()` method.
  - Exit-code constants: `EXIT_OK = 0`, `EXIT_USAGE = 1`, `EXIT_CONFIG = 2`, `EXIT_INDEX_SCHEMA = 10`, `EXIT_INDEX_MODEL = 11`, `EXIT_INDEX_MISSING = 12`, `EXIT_BACKEND = 20`, `EXIT_UNKNOWN = 99`.
  - `Kinds` registry. Already-registered kinds Phase 7 reuses or adds producers for: `INDEX_MISSING = "index.missing"`, `INDEX_UNREADABLE = "index.unreadable"`, `INDEX_SCHEMA_MISMATCH = "index.schema_mismatch"`, `BACKEND_MODEL_DOWNLOAD_FAILED = "backend.model_download_failed"`, `BACKEND_ENCODE_FAILED = "backend.encode_failed"`, `CONFIG_BAD_ENUM = "config.bad_enum"` (left in place for `embed_backend` validation), `CLI_NOT_IMPLEMENTED = "cli.not_implemented"` (untouched).
  - Stream writers: `write_result_stdout`, `write_log_stderr`, `write_error_envelope_stdout`, `write_error_summary_stderr`. (Spelling verified against `001.foundations/002.errors.md`.)
- `code_index.config`:
  - `load_config(path, *, project_root=None, engine_version=None) -> CodeIndexConfig` (Pydantic v2 model).
  - `discover_config_path(start) -> Path` (config-discovery walk upward from CWD).
- `code_index.storage`:
  - `open_index(db_path, *, create_if_missing=True, check_version=True) -> sqlite3.Connection`. **Step 001 uses `check_version=False`** so schema mismatch does not raise during diagnostic reads.
  - `get_meta(conn, key) -> str | None`. Step 001 reads `schema_version`, `code_index_version`, `embed_model`, `embed_dim`.
  - `set_meta(conn, key, value) -> None` (not used by Phase 7).
- `code_index.cli`:
  - Typer app with `--config`, `--format`, `--verbose`, `--quiet` on `ctx.obj`.
  - `config_app.command("show")` — Phase 1's body. Step 001 replaces it.
  - `cli_init` (Phase 4 body). Step 002 adds the JSON output branch.
  - `cli_search` (Phase 5 body) — `--mode` enum validation currently raises `Kinds.CONFIG_BAD_ENUM`. Step 004 updates to `Kinds.CLI_BAD_ENUM`.
  - `cli_index_rebuild` (Phase 6 body) — `--yes` confirmation raise currently uses the free-string kind. Step 004 promotes to `Kinds.USAGE_CONFIRMATION_REQUIRED`.
  - Boundary exception handler routes `CodeIndexError` through the envelope writer; unchanged.

### From Phase 2 (`docs/plans/002.embedding-backend/`)

- `EmbeddingBackend` Protocol with `name: str`, `dim: int`, `encode(texts: list[str]) -> np.ndarray`.
- `code_index.embeddings.from_config(config) -> EmbeddingBackend` — currently lets native fastembed exceptions propagate. Step 003 wraps them.
- `FastembedBackend.__init__(model: str, batch_size: int)` and `.encode(...)`. Step 003 wraps both.
- Package layout: `src/code_index/embeddings/__init__.py`, `protocol.py`, `fastembed.py`, `factory.py`. Step 003 edits `factory.py` and `fastembed.py`.

### From Phase 4 (`docs/plans/004.walker-and-build/`)

- `cli_init` body in `cli.py` — currently emits text-mode output only. Step 002 adds the JSON branch.
- Polyglot fixture at `tests/fixtures/projects/polyglot_minimal/`. Step 005's DoD integration test reuses it (runs `init` + `index build` + `index sync` + `search` + `symbols` + `graph` + `config show` against the same tmp_path copy).
- `index build` JSON shape (pinned by `004.walker-and-build/004.context.md` lines 62–71): `{"files_walked", "files_chunked", "chunks_inserted", "symbols_inserted", "edges_inserted", "seconds_elapsed"}`. Step 005 verifies round-trip; no edits.

### From Phase 5 (`docs/plans/005.search/`)

- `code_index search` body. JSON shape pinned at `005.search/002.context.md` lines 86–102 (`{"results": [...]}`). Step 005 verifies round-trip; no edits.
- `--mode bm25|dense|hybrid` validation. **Step 004 changes the kind** from `Kinds.CONFIG_BAD_ENUM` to `Kinds.CLI_BAD_ENUM`. If the Phase 5 coder used Typer's enum / `Literal` to delegate to Typer (which yields exit 2 by default), step 004 verifies the path and either keeps Typer's behavior or wraps it to emit `cli.bad_enum` (code 1). See step 004 for the disposition.

### From Phase 6 (`docs/plans/006.sync-symbols-graph/`)

- Six JSON shapes pinned in `006/context.md` lines 192–250: `index sync`, `index rebuild`, `symbols defs/refs`, `graph callers`, `graph deps`. Step 005 verifies round-trip; no shape edits.
- `index rebuild` confirmation raise site: `006.sync-symbols-graph/002.rebuild-cli.md` lines 28, 44 — currently uses a free-string `kind="usage.confirmation_required"`. **Step 004 promotes** to `Kinds.USAGE_CONFIRMATION_REQUIRED` (same dotted string; now sourced from the registry).
- `sync.delete_file_rows`, `verify_index_compat`, the symbols / graph query helpers — all consumed read-only by step 005's DoD test.

## Shared vocabulary

- **Diagnostic read** — `config show`'s gentle-open path that reads `meta` without raising on schema, model, or dim mismatch. Uses `open_index(..., check_version=False)` (or a hand-rolled equivalent if the storage helper does not expose `check_version`).
- **Backend wrapping** — the try/except shell around `FastembedBackend.__init__`, `.encode`, and `from_config` that converts native fastembed exceptions into `CodeIndexError` with the correct kind.
- **JSON round-trip** — `json.loads(captured_stdout)` returning a dict / list without raising. The DoD integration test's primary assertion.
- **Error envelope** — the `{"error": {"code", "kind", "message", "detail"}}` shape Phase 1 pinned in `errors-and-exit-codes.md`.
- **Mismatch reporting** — `config show`'s practice of emitting both the config value and the index value (in different blocks of the JSON document) when they disagree; no marker field.

## Dependency direction

```
001 config-show ─┐
                 │
002 init-json    ├── 005 json-roundtrip-dod
                 │
003 backend-wrap ┤
                 │
004 kinds        ┘
```

- 001, 002, 003, 004 are mutually independent.
- 005 depends on all four (the DoD integration test exercises every shape and every newly-registered kind).

## Phase 7 DoD (the contract, verbatim from `mvp-phases.md`)

> every MVP subcommand under `--format json` round-trips through `json.loads`; the same subcommands under failure conditions emit a parseable error envelope.

Operationalized as step 005's `tests/test_json_roundtrip_dod.py`. The test enumerates every MVP subcommand (`init`, `index build`, `index sync`, `index rebuild`, `search`, `symbols defs`, `symbols refs`, `graph callers`, `graph deps`, `config show`) and asserts:

1. Success path: `--format json` stdout round-trips through `json.loads` and matches the inline-documented shape.
2. Failure path: at least one failure mode per subcommand emits a parseable error envelope with the expected `code` and `kind`.

## Build and test commands

Per root `CLAUDE.md`:

- `uv sync --extra dev` — install dev environment.
- `uv run pytest` — run tests.
- `uv run ruff check` — lint.
- `uv run ruff format` — format.
- `uv run pyright` — typecheck.

The verifier reads these from root `CLAUDE.md`; do not duplicate command lines in step files unless the step has a non-standard invocation.
