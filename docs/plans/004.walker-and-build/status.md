# Feature 004 — walker-and-build

| Step | File                          | Status  | Verifier | Date |
|------|-------------------------------|---------|----------|------|
| 001  | `001.walker.md`               | done    | PASS     | 2026-05-20 |
| 002  | `002.init.md`                 | done    | PASS     | 2026-05-20 |
| 003  | `003.indexer-pipeline.md`     | done    | PASS     | 2026-05-20 |
| 004  | `004.index-build-cli.md`      | done    | PASS     | 2026-05-21 |

## Files Changed

### Step 001 — walker
- `src/code_index/walker.py` — new module: `WalkedFile` dataclass and `walk(root, config)` iterator implementing all "Indexer walking" rules.
- `pyproject.toml` — add `pathspec>=0.12` to `[project.dependencies]`.
- `tests/test_walker.py` — new: 24 tests covering every walker rule.
- `tests/fixtures/walker/encoding/latin1.py` — new: checked-in binary fixture with a `\xff` byte for the decode-fallback test.

### Step 002 — init
- `src/code_index/init.py` — new helper module: `write_skeleton(project_root, project_name, force)` writes `docs/.helpers/config.toml` + `.gitignore`, `compute_version_pin` produces the PEP 440 pin from the running engine version.
- `src/code_index/cli.py` — replace the `init` stub with a real implementation that delegates to `write_skeleton` and emits a single-line stdout summary; add `--name`/`--force` flag wiring (signatures unchanged).
- `tests/test_cli_init.py` — new: five DoD test cases (fresh init, refuse-without-force via `_invoke` boundary, `--force` overwrites, `--name` sets project, `.gitignore` idempotency under `--force`).
- `tests/test_cli.py` — remove `["init"]` from the `test_stub_subcommands_envelope` parametrize and switch `test_stub_text_mode_stderr_only` to `index sync` now that `init` is no longer a stub.

### Step 003 — indexer pipeline
- `src/code_index/indexer.py` — new module: `IndexerResult` dataclass and `build(config, root, *, dry_run, verbose)` composing the Phase 4 walker, Phase 3 plugin registry, Phase 2 embedding backend, and Phase 1 storage; auto-rebuild clears the six row-data tables and the two indexer-owned meta keys; per-file `files` upsert; plugin raises and per-file IO errors skip+warn via `write_log_stderr`.
- `tests/test_indexer_pipeline.py` — new: eight DoD cases (fresh happy path, `files` row contents, auto-rebuild, `dry_run=True`, plugin raise, per-file IO error, empty input, embedding batching) using fake plugins, a deterministic 768-dim fake backend, and a real on-disk SQLite via the Phase 1 storage helper.

### Step 004 — index build CLI
- `src/code_index/cli.py` — replace the `index build` stub with a real implementation: discovers config via `_resolve_config_path`, resolves the walk root (`--root` flag or the project root above `docs/.helpers/`), calls `indexer.build(...)`, and emits a single-line stdout summary under `--format text` or the `IndexerResult` JSON object under `--format json`. Adds the `code_index.indexer` import.
- `tests/test_index_build_cli.py` — new: four DoD cases (polyglot integration / phase DoD, auto-rebuild row-count equality, `--dry-run` writes no rows, no-config-found exits with `index.missing` envelope). The `warm_fastembed` fixture monkeypatches `indexer.from_config` to reuse `tests/.cache/fastembed/`.
- `tests/fixtures/projects/polyglot_minimal/` — new fixture tree: one tiny but real source file per language (`main.py`, `main.cs`, `main.js`, `main.ts`, `main.go`, `main.fs`, `main.lsl`), root `.gitignore` listing `ignored/`, `ignored/skip_me.py`, and 16-byte `data.bin` starting with `b"\x00binary"`.
- `tests/test_cli.py` — drop the `["index", "build"]` entry from the `test_stub_subcommands_envelope` parametrize now that the subcommand is no longer a stub.

## Notes & Issues

_populated by the coder when worth saying_

## Bug Fixes

### Step 002 — init JSON refuse-path leaks Windows backslashes (2026-05-23)
- `src/code_index/init.py` — `write_skeleton` refuse-without-force branch now formats `config_path` via `Path.as_posix()` for both `message` and `detail["path"]`, matching the success-path forward-slash contract.
- `tests/test_init_json.py` — new `test_refuse_without_force_path_uses_forward_slashes` regression test asserting `"\\"` is absent from `error["detail"]["path"]` and `error["message"]`.
