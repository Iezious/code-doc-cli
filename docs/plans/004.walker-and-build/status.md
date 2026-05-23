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

### Step 003 — fastembed OOM on long chunks (2026-05-23)
Bug: `code_index index build --verbose` against a real polyglot project (`D:/GitRoot/_SIN` — F#, C#, TypeScript, LSL) crashed mid-build with `[ONNXRuntimeError] : 6 : RUNTIME_EXCEPTION : Non-zero status code returned while running Add node` and a `BFCArena::AllocateRawInternal Failed to allocate memory for requested buffer of size 73489749504` (~68 GB).
Root cause: language plugins emit chunks with no character/token cap. `FastembedBackend.encode` passed raw chunk text to `self._model.embed(batch)` without bounding the per-text token length, so fastembed's tokenizer truncated each chunk to the model's native `model_max_length=8192`. ONNX then pads the entire batch to the longest item; one 8192-token chunk inside a batch of 32 demands `32 * 12 * 8192 * 8192 * 4 ≈ 103 GB` for a BERT-style 12-layer/12-head attention kernel, matching the observed allocation.
Fix: bound per-text token length to a much smaller value at the tokenizer level and pre-cut text at the character level as defense-in-depth; halve the default batch.
- `src/code_index/embeddings/fastembed.py` — new module-level constants `MAX_TOKEN_LENGTH = 1024` and `MAX_CHARS_PER_TEXT = MAX_TOKEN_LENGTH * 8`; `__init__` calls `self._model.model.tokenizer.enable_truncation(max_length=MAX_TOKEN_LENGTH)` inside a narrow `try/except AttributeError` (warns via `write_log_stderr` on failure so genuine model-load failures still raise `BACKEND_MODEL_DOWNLOAD_FAILED`); `encode` builds a capped copy of `texts` before the batching loop; default `batch_size` lowered from `32` to `16`.
- `src/code_index/config.py` — default `embed_batch_size` lowered from `32` to `16`.
- `src/code_index/usage/index-build.md`, `src/code_index/usage/config-show.md` — mirror the new default (16) in the two places that quoted `32`.
- `tests/test_config.py` — `test_defaults_applied` asserts `embed_batch_size == 16` (the assertion pinned the old default; we are intentionally changing it).
Verification: `uv run pytest tests/test_indexer_pipeline.py tests/test_index_build_cli.py tests/test_search_pipeline.py tests/test_phase6_dod.py tests/test_config.py -x` — 43 passed. `uv run ruff check src/code_index/embeddings/fastembed.py src/code_index/config.py` — clean. `uv run pyright src/code_index/embeddings/fastembed.py src/code_index/config.py` — 0 errors / 0 warnings. Real-project sanity: `code_index index build --verbose` in `D:/GitRoot/_SIN` runs stable at ~3.4 GB RSS without the BFCArena allocation error (tail captured in `## Notes & Issues` once the run completes).

### Step 003 — dry-run summary reports zero chunks (2026-05-23)
Scope-stretch: user-confirmed extension of the JSON contract Phase 7 pinned for `index build` / `index rebuild`. Adds a new `chunks_chunked` field to `IndexerResult` and exposes it in the JSON shape; text-mode summary line switches from `chunks_inserted` to `chunks_chunked` so dry-run reports the chunker's actual output. `chunks_inserted == 0` under `--dry-run` remains; for a real build the two values are equal. Downstream consequence: the Fast 001 usage docs for `index build` / `index rebuild` were updated to document the new field.
- `src/code_index/indexer.py` — add `chunks_chunked` to `IndexerResult` and `_Counters`; accumulate at `_PendingFile` registration so dry-run participates; threaded through `IndexerResult` construction; final stderr summary line reads `chunks_chunked`.
- `src/code_index/cli.py` — `cli_index_build` and `cli_index_rebuild` JSON payloads include `chunks_chunked` (after `files_chunked`, before `chunks_inserted`); text summaries switch to `chunks_chunked`.
- `src/code_index/usage/index-build.md`, `src/code_index/usage/index-rebuild.md` — JSON shape blocks include `chunks_chunked`; one-sentence gloss explains the relationship to `chunks_inserted`.
- `tests/test_indexer_pipeline.py` — dry-run case gains `assert result.chunks_chunked > 0` (existing `chunks_inserted == 0` assertion preserved).
- `tests/test_index_build_cli.py` — new `test_json_includes_chunks_chunked_under_dry_run` (dry-run JSON has `chunks_chunked > 0` and `chunks_inserted == 0`); new `test_json_chunks_chunked_equals_inserted_in_real_build` pins the equality contract for non-dry-run.
- `tests/test_json_roundtrip_dod.py` — Phase 7 build / rebuild shape assertions extended to seven keys (`chunks_chunked` added).
- `tests/test_phase6_dod.py` — Phase 6 rebuild shape assertion extended likewise.
- `tests/test_rebuild_cli.py` — JSON shape and per-fixture row-count assertions extended to include `chunks_chunked`.
