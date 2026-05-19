# Feature 001 — foundations

| Step | File                       | Status  | Verifier | Date |
|------|----------------------------|---------|----------|------|
| 001  | `001.package-skeleton.md`  | done    | PASS     | 2026-05-19 |
| 002  | `002.errors.md`            | done    | PASS     | 2026-05-19 |
| 003  | `003.config.md`            | done    | PASS     | 2026-05-19 |
| 004  | `004.storage.md`           | done    | PASS     | 2026-05-19 |
| 005  | `005.cli.md`               | done    | PASS     | 2026-05-19 |

## Files Changed

### Step 001 — package skeleton
- `src/code_index/__init__.py` — package init, exports `__version__` via `importlib.metadata`
- `src/code_index/__main__.py` — module entry point, lazily imports `code_index.cli:app`
- `tests/__init__.py` — empty marker for the tests package
- `tests/test_package_skeleton.py` — version-is-str and `__main__` import smoke tests (cli subprocess test xfail until step 005)
- `pyproject.toml` — added `pydantic>=2` to deps, `pyright>=1.1.350` to dev extra, `[tool.pyright]` config (strict on `src/code_index`, basic elsewhere)

### Step 002 — errors
- `src/code_index/errors.py` — exit-code constants, `Kinds` registry (full enumerated failure surface plus `cli.not_implemented`), `CodeIndexError` with `envelope()`, four stream helpers as the only sanctioned stdout/stderr writers
- `tests/test_errors.py` — eight tests covering envelope shape/optional detail, stream-discipline non-crosstalk for all four writers, and contract assertions against the architecture doc's exit-code table and kind strings

### Step 003 — config loader
- `src/code_index/config.py` — `CodeIndexConfig` (Pydantic v2), `EmbedBackend`, `DEFAULT_LANGUAGES`, `ALLOWED_BACKENDS`, `BACKEND_DEFAULT_MODEL`, `load_config`, `discover_config_path`; per-row mapping to Config-section `kind`s; PEP 440 pin via `packaging.specifiers.SpecifierSet`; unknown-key warning via `errors.write_log_stderr`
- `tests/test_config.py` — 12 tests covering valid load, defaults, project dirname fallback, per-backend embed_model default, and one test per Config-section failure mode (parse_error, missing_key, version_mismatch, bad_enum, two bad_path branches, unknown_language) plus the unknown-key warning via `capsys`
- `tests/fixtures/config_valid.toml` — passing fixture used by `test_valid_config_loads`
- `tests/fixtures/config_missing_version.toml` — `config.missing_key`
- `tests/fixtures/config_bad_enum.toml` — `config.bad_enum`
- `tests/fixtures/config_bad_path.toml` — `config.bad_path` (roots branch)
- `tests/fixtures/config_version_mismatch.toml` — `config.version_mismatch`
- `tests/fixtures/config_unknown_key.toml` — unknown-key warning path
- `tests/fixtures/config_malformed.toml` — `config.parse_error`
- `pyproject.toml` — added `packaging>=23` to `[project.dependencies]` (per 003.context.md action item; Pydantic does not pull it transitively)

### Step 004 — storage + migrations
- `src/code_index/storage/__init__.py` — `open_index` (WAL, sqlite-vec load with translated failure, FTS5 compile-option probe, schema-version check, fresh-DB migration run), `CURRENT_SCHEMA_VERSION = "1"`, `get_meta`, `set_meta`
- `src/code_index/storage/migrations/__init__.py` — `Migration` Protocol, `discover_migrations` (pkgutil-based, numeric sort on `<from>`), `run_migrations` (per-migration transaction, advances `meta.schema_version` after each apply, no-op at target)
- `src/code_index/storage/migrations/0_to_1.py` — Phase 1 schema-from-scratch: six tables (`meta`, `files`, `chunks`, FTS5 `chunks_fts`, vec0 `embeddings` dim=768, `symbols`, `edges`) plus the five named indices; writes `meta.code_index_version = code_index.__version__`
- `tests/test_storage.py` — 12 tests: fresh-DB open, WAL, FTS/vec/files-table existence (with `files` column-type/PK introspection), all five indices, reopen idempotency via sentinel row, schema-mismatch raises (code 10, `index.schema_mismatch`), `discover_migrations` numeric sort, `run_migrations` idempotent at target, plus patched probes for `index.vec_extension_unavailable` and `index.fts5_unavailable`

### Step 005 — CLI scaffold
- `src/code_index/cli.py` — Typer app via `BoundaryTyper` subclass, shared-flag callback (`--config`, `--format`, `--verbose`, `--quiet`) storing resolved flags on `ctx.obj`, four sub-typers (`index`, `symbols`, `graph`, `config`), nine stubs raising `cli.not_implemented` with phase numbers, real `config show` implementation (text key=value sorted, JSON envelope per `005.context.md`), `_resolve_config_path` mapping "no config found" to `index.missing` (code 12), boundary handler in `_invoke` routing `CodeIndexError` and synthesizing `kind="unknown"` (code 99) for any other exception
- `src/code_index/__main__.py` — replaced lazy shim with `from code_index.cli import app`; retained thin `main()` for back-compat with step-001's `test_module_main_imports`
- `src/code_index/errors.py` — added `write_json_stdout(payload)` as the success-side JSON writer (companion to `write_error_envelope_stdout`)
- `tests/test_cli.py` — 27 tests covering DoD-1..7: help listings for every MVP subcommand, valid `config show` text+JSON, parametrized Config-row envelopes against all five failure fixtures, stub envelopes + text-mode stderr, unhandled-exception path with `kind="unknown"` via monkeypatched `load_config`, stream discipline (valid/broken in both formats), `python -m code_index --help` subprocess parity

## Notes & Issues

_populated by the coder when worth saying_

## Bug Fixes

_populated post-completion by `/bug-fixer` if needed_
