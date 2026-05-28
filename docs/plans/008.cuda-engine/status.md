# Feature 008 — cuda-engine

| Step | File                          | Status  | Verifier | Date |
|------|-------------------------------|---------|----------|------|
| 001  | `001.device-resolution.md`    | done    | PASS     | 2026-05-28 |
| 002  | `002.backend-device-wiring.md`| done    | PASS     | 2026-05-28 |
| 003  | `003.meta-stamping.md`        | done    | PASS     | 2026-05-28 |
| 004  | `004.config-show-device.md`   | done    | PASS     | 2026-05-28 |
| 005  | `005.gpu-install-docs.md`     | done    | PASS     | 2026-05-28 |

## Files Changed

### Step 001 — Device resolution helper
- `src/code_index/embeddings/device.py` — new: env read/validate, onnxruntime probe, cpu/cuda resolution with single stderr fallback warning
- `tests/test_device_resolution.py` — new: unit tests for the four functions and constants (no real GPU; probe + env monkeypatched)

### Step 003 — Stamp meta.embed_device at build
- `src/code_index/indexer.py` — `build()` stamps `set_meta(conn, "embed_device", backend.device)` inside the existing non-dry-run block; `_auto_rebuild` DELETE clears `embed_device` alongside `embed_model`/`embed_dim`
- `tests/test_indexer_pipeline.py` — `device` attr on `FakeBackend`; assert `embed_device == "cpu"` after build and absent under `--dry-run`
- `tests/test_rebuild_cli.py` — `device` attr on `FakeBackend`; assert rebuild leaves exactly one `embed_device` row, not stale
- `tests/test_sync_engine.py`, `tests/test_sync_cli.py`, `tests/test_graph_cli.py`, `tests/test_new_kinds.py`, `tests/test_symbols_cli.py` — add `device` attr to each local `FakeBackend` (these flow through `build()`, which now reads `backend.device`)

### Step 002 — FastembedBackend device wiring
- `src/code_index/embeddings/protocol.py` — add informational `device: str` to `EmbeddingBackend` Protocol
- `src/code_index/embeddings/fastembed.py` — `__init__` gains `device` param; resolves once via `resolve_device(warn=True)`, stores `self.device`, passes `providers=[CUDA,CPU]` on cuda path
- `src/code_index/embeddings/factory.py` — fastembed branch passes `device=requested_device()` (centralized env read); voyage branch untouched
- `tests/test_backend_init_wrapping.py` — add device-arg construction tests (cuda/cpu/fallback-warning); thread `device` param through fake-init stubs
- `tests/test_embedding_factory.py` — assert factory passes resolved device; end-to-end resolved-device test with stubbed TextEmbedding
- `tests/test_storage_compat.py` — add `device` attr to `_StubBackend` (required by Protocol change to satisfy pyright)
- `tests/test_search_pipeline.py` — add `device` attr to `FakeBackend` (required by Protocol change to satisfy pyright)

### Step 004 — config show device fields
- `src/code_index/cli.py` — import `requested_device`/`resolve_device`; append `embed_device` as final `_INDEX_META_KEYS` element; assemble top-level `requested_device` (raw env) and `effective_device` (`resolve_device(warn=False)`) siblings of `config`/`index` in the JSON document; extend `_config_show_text` signature with the two device values, rendered in a trailing `device:` stanza
- `tests/test_config_show.py` — update `test_after_build_index_block_is_populated` key set/ordering to include `embed_device`; update `test_fresh_init_index_is_null` top-level key set; add device-field tests (requested defaults/echoes env with broken probe, effective cuda-available/unavailable-no-warning, survives broken probe, pre-feature `index.embed_device == ""`, text renders both fields)
- `tests/test_cli.py` — `test_config_show_valid_text`: scope the sorted-keys check to the `config:` stanza and assert the new `device:` stanza (the prior whole-output scrape conflicted with the new device lines)
- `tests/test_json_roundtrip_dod.py` — `test_config_show_success_json_roundtrips`: expand expected top-level key set to include `requested_device`/`effective_device`

### Step 005 — GPU install docs
- `README.md` — new `### GPU acceleration (CUDA)` subsection in the install section: CPU-default unchanged, `fastembed-gpu` manual swap + `CODE_INDEX_DEVICE=cuda`, mutual-exclusivity rationale, no `[gpu]` extra / `pyproject.toml` unchanged, `auto`/`cuda`/`cpu` semantics, and the cuda-on-base-fastembed stderr-fallback note

## Notes & Issues
- Step 001: `uv run ruff format --check` reports ~42 pre-existing repo files needing reformat (e.g. `tests/test_walker.py`); both new files are already formatted. Out of scope for this step — not touched.
- Step 002: adding `device: str` to the Protocol (planner's resolved decision) broke pyright for two existing test stubs (`_StubBackend`, `FakeBackend`) passed to `EmbeddingBackend`-typed functions; added a one-line `device` attr to each. Other `FakeBackend` stubs in CLI tests were not flagged (not passed at a structurally-checked call site) and were left untouched.
- Step 003: `build()` now reads `backend.device` at runtime, so the five `FakeBackend` stubs that flow through `build()` but were not pyright-flagged in step 002 (`test_sync_engine`, `test_sync_cli`, `test_graph_cli`, `test_new_kinds`, `test_symbols_cli`) raised `AttributeError` at runtime; added a one-line `device = "cpu"` attr to each. This is the runtime complement to step 002's pyright-only fix.
- Step 003: `uv run ruff format --check` flags all eight touched files (`indexer.py` + the seven test modules) — confirmed via `git stash` they already failed before this step (pre-existing repo-wide format debt, per step 001's note). New code follows the file's existing hand-wrapped style and introduces no fresh format delta; debt left untouched per brief.
- Step 004: two tests OUTSIDE the step's listed files asserted the now-changed `config show` contract and could not pass unchanged — `test_cli.py::test_config_show_valid_text` (whole-output sorted-keys scrape collided with the new `device:` stanza) and `test_json_roundtrip_dod.py::test_config_show_success_json_roundtrips` (top-level key set was hard-coded to `{config, index}`). Applied minimal contract-alignment edits to both; this is mechanical alignment to the contract this step changes (the same situation as the in-scope `test_config_show.py` assertions), not new scope. No production code beyond `cli.py` was touched.
- Step 004: null vs "" resolved by following the existing sibling-key convention — `_read_index_meta` coerces every absent meta row to `""`, so `index.embed_device` renders `""` (not `null`) for a built pre-feature index; `null` remains the whole-`index`-absent (no db file) case. This matches `schema_version`/`embed_model`/etc. and diverges from cli.md's per-key `null` wording; recorded as a candidate observation in `outcome.md` (Step 004) for the architect to reconcile.
- Step 004: pre-feature `index.embed_device` test constructs the absent-row case with a direct `DELETE FROM meta WHERE key = 'embed_device'`; the briefed `_set_meta_direct` helper only inserts/updates and cannot represent an absent row (a present-but-empty row would not exercise the `get_meta(...) or ""` path correctly), so DELETE is the faithful pre-feature construction.
- Step 004: `uv run ruff format --check` flags `cli.py` and `test_config_show.py` — confirmed via `git stash` both already failed before this step (pre-existing repo-wide format debt, per steps 001/003). New code follows the file's existing hand-wrapped style; debt left untouched per brief. `ruff check` and `pyright` are clean on all touched files; full `pytest` is green.
