# Feature 007 — config-show-json-polish

| Step | File                            | Status  | Verifier | Date |
|------|---------------------------------|---------|----------|------|
| 001  | `001.config-show.md`            | done    | PASS     | 2026-05-21 |
| 002  | `002.init-json.md`              | done    | PASS     | 2026-05-21 |
| 003  | `003.backend-init-wrapping.md`  | done    | PASS     | 2026-05-21 |
| 004  | `004.kinds-formalize.md`        | done    | PASS     | 2026-05-21 |
| 005  | `005.json-roundtrip-dod.md`     | done    | PASS     | 2026-05-21 |

## Files Changed

### Step 001 — `config show` full body
- `src/code_index/cli.py` — replaced `cli_config_show` body with the Phase 7 diagnostic implementation (sibling `"index"` block, `_read_index_meta` helper, two-stanza text format with optional `[mismatch]` marker).
- `tests/test_config_show.py` — new test module covering the eight DoD cases (fresh init, after build, model mismatch, schema mismatch, text mode, config not found, index unreadable, stream discipline).
- `tests/test_cli.py` — updated `test_config_show_valid_text` to the Phase 7 `key: value` two-stanza format (the body replacement supersedes the Phase 1 `key = value` format the test pinned).

### Step 002 — `init` JSON output shape
- `src/code_index/cli.py` — added `--format json` branch to `cli_init` (now accepts `ctx`), emitting the four-key payload (`config_path`, `gitignore_path`, `project`, `force_used`) via `write_result_stdout(json.dumps(..., indent=2))`; captured `config_path.exists()` pre-`write_skeleton` to drive `force_used`.
- `tests/test_init_json.py` — new test module covering the six DoD cases (fresh JSON init, `--name` propagation, `--force` over populated dir, `--force` over empty dir, refuse-without-`--force` envelope round-trip via `_invoke`, text-mode regression).

### Step 003 — fastembed backend exception wrapping
- `src/code_index/embeddings/fastembed.py` — wrapped `__init__` body and the inner `self._model.embed(batch)` call inside `encode` in `try/except CodeIndexError: raise; except Exception as exc:` shells that re-raise as `CodeIndexError(EXIT_BACKEND, Kinds.BACKEND_MODEL_DOWNLOAD_FAILED | BACKEND_ENCODE_FAILED, ...)` with `model` / `cause` / `type` (and `batch_size` for encode) in the detail dict; module docstring updated.
- `src/code_index/embeddings/factory.py` — wrapped the `FastembedBackend(...)` construction call in `from_config` with the same shell so any non-`CodeIndexError` exception leaking out of construction maps to `BACKEND_MODEL_DOWNLOAD_FAILED`; Voyage stub raise is unchanged.
- `tests/test_backend_init_wrapping.py` — new test module covering the seven DoD cases (init wrap, init `from exc` chaining, `from_config` wrap, `from_config` pass-through, encode wrap, encode pass-through, encode happy path, init+encode envelope JSON round-trip, Voyage stub unchanged).

### Step 004 — formalize two new `Kinds` constants
- `src/code_index/errors.py` — added `Kinds.USAGE_CONFIRMATION_REQUIRED = "usage.confirmation_required"` and `Kinds.CLI_BAD_ENUM = "cli.bad_enum"` to the registry under the CLI / usage (code 1) group; no new exit codes (both map to existing `EXIT_USAGE = 1`).
- `src/code_index/cli.py` — `cli_index_rebuild` raise site now sources from `Kinds.USAGE_CONFIRMATION_REQUIRED` (kind string unchanged; pure literal-to-registry swap); replaced Phase 5's `_SearchMode` enum + Typer-driven exit-2 rejection with a `_SEARCH_MODES` string tuple and an explicit pre-check in `cli_search` that raises `CodeIndexError(EXIT_USAGE, Kinds.CLI_BAD_ENUM, ...)` with `detail.flag` / `detail.value` / `detail.expected` so the envelope round-trips under `--format json`; dropped the now-unused `import enum`; touched docstrings on both raise sites.
- `tests/test_search_cli.py` — updated `test_bad_mode_rejected_with_usage_error` from Typer's exit-2 assertion to the new `cli.bad_enum` / exit-1 / detail-set assertions via `_invoke` + `capsys` (mirrors the rebuild-CLI / init-JSON refuse-path pattern).
- `tests/test_new_kinds.py` — new test module covering the five DoD cases (two registry-constant assertions, `index rebuild` without `--yes` envelope, `search --mode garbage` envelope with `detail.expected`, `search --mode hybrid` happy-path regression). Uses the rebuild-CLI fake-plugin + `FakeBackend` fixture pattern so the suite stays fastembed-free.

### Step 005 — cross-subcommand JSON round-trip DoD
- `tests/test_json_roundtrip_dod.py` — new tests-only module operationalizing the Phase 7 DoD across every MVP subcommand (`init`, `index build`, `index sync`, `index rebuild`, `search`, `symbols defs`, `symbols refs`, `graph callers`, `graph deps`, `config show`). Session-scoped `built_project` fixture runs `init` + `index build` once against the polyglot fixture with the persistent fastembed cache at `tests/.cache/fastembed/`; per-test fixtures (`read_only_built`, `mutable_built`) chdir into that tree or copy it to `tmp_path` for mutation cases. Drives the CLI through `_invoke` + `capsys` so the boundary handler routes `CodeIndexError` envelopes to stdout. Asserts each subcommand's success-path JSON shape, each subcommand's failure-mode kind (`index.missing`, `index.embed_model_mismatch`, `usage.confirmation_required`, `cli.bad_enum`), zero-results round-trip for the five result-list subcommands (search uses `--mode bm25` so empty BM25 matches do not get masked by dense's always-top-k behavior), and re-asserts the `config show` schema-mismatch carve-out at the DoD level.

## Notes & Issues

- Step 002: the refuse-without-`--force` test could not use `CliRunner` as the step file's wording suggested — `CliRunner` bypasses the `BoundaryTyper.__call__` wrapper that emits the JSON error envelope to stdout, so the envelope would never appear there. The test routes through `_invoke` + `capsys` instead, mirroring `tests/test_cli_init.py::test_refuses_overwrite_without_force` and `tests/test_index_build_cli.py::test_no_config_found_errors_with_init_hint`. All success-path cases use `CliRunner` as specified.

## Bug Fixes

_populated post-completion by `/bug-fixer` if needed_
