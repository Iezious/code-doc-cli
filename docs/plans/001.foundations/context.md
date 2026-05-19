# Feature 001 — Foundations

This folder plans **Phase 1 — Foundations** from [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md). The deliverable is the bottom of the engine stack: package skeleton, errors module, config loader, storage open/migration harness, and a Typer CLI scaffold whose only implemented command is `config show`.

## Goal

Stand up the infrastructure every later phase consumes:

- Python package skeleton at `src/code_index/` with a working `code_index` entry point.
- Errors module: exit-code constants, `kind` registry, `CodeIndexError`, JSON envelope writer, stderr summary, stream-discipline helpers.
- Config loader: TOML parse via `tomllib`, full validation per [`../../architecture/config.md`](../../architecture/config.md), mapped to the failure surface in [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md).
- Storage layer: SQLite open helper (WAL mode, sqlite-vec extension load, FTS5 availability check), schema_version writing, forward-only file-per-step migrations harness with `0_to_1.py` creating the full Phase 1 schema.
- CLI scaffold: Typer app with subcommand stubs for every MVP subcommand named in [`../../architecture/cli.md`](../../architecture/cli.md); `config show` is the only one implemented in this phase.

## Scope envelope

Strictly Phase 1's bullet list and DoD from `mvp-phases.md`. Out of scope here:

- Embedding backends (Phase 2).
- Plugins / language interface (Phase 3).
- Walker, indexer, `init`, `index build` (Phase 4).
- Search (Phase 5).
- Sync / symbols / graph / rebuild (Phase 6).
- Voyage backend, full `config show` with index meta, JSON polish across all subcommands (Phase 7).

Anything not on Phase 1's list is a stub or absent.

## Architecture inputs (authoritative)

- [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md) — Phase 1 section; bullet list + DoD.
- [`../../architecture/mvp-scope.md`](../../architecture/mvp-scope.md) — pinned cut line.
- [`../../architecture/storage.md`](../../architecture/storage.md) — schema sketch, indices, schema_version semantics, WAL, sqlite-vec + FTS5, migrations directive.
- [`../../architecture/config.md`](../../architecture/config.md) — TOML schema, defaults, validation rules, what `init` writes (informs the loader; `init` itself is Phase 4).
- [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md) — exit-code table, JSON envelope shape, enumerated failure surface, default vs `--strict`, stream discipline.
- [`../../architecture/cli.md`](../../architecture/cli.md) — subcommand list (used for stubs), shared flags, output discipline, `config show` semantics.
- [`../../architecture/tool-and-data-split.md`](../../architecture/tool-and-data-split.md) — `docs/.helpers/` location, version-pin checks.
- Root `CLAUDE.md` — Build & Test Commands (verifier reads from here).
- `docs/CLAUDE.md` — markdown conventions; no emojis, no HTML.

## User-confirmed decisions

1. **Pydantic v2** is the config validation library. Added to `[project.dependencies]`. Failures in field validators raise `CodeIndexError` directly, or `ValidationError` is caught at the loader boundary and translated to `CodeIndexError`. Implementation choice belongs to the coder; the `kind` strings from the Config section of `errors-and-exit-codes.md` must be the surface either way.
2. **Schema versioning:** initial `meta.schema_version = "1"` (string). Migrations live at `src/code_index/storage/migrations/<from>_to_<to>.py`. The first migration is `0_to_1.py` and contains the full Phase 1 schema (every table, index, FTS5 virtual table, vec0 virtual table from `storage.md`). Fresh installs run all migrations in order; the runner is the single source of truth for schema. No separate "create schema" code path.
3. **Stub behavior** for unimplemented subcommands: print `"<subcommand> not implemented in this build (lands in Phase N)"` to stderr and exit `1`. Under `--format json`, emit the standard error envelope with `code: 1` and `kind: "cli.not_implemented"`. This new `kind` is added to the contract by this feature (recorded in `outcome.md`).
4. **Pyright** is added to `[project.optional-dependencies].dev`. Configure via `[tool.pyright]` in `pyproject.toml` (or `pyrightconfig.json` — coder's call) with `include = ["src/code_index"]`, strict on `src/`, basic on `tests/`.

## Files touched across steps

| Area | Path | Step(s) |
|---|---|---|
| package init | `src/code_index/__init__.py` | 001 |
| module entry | `src/code_index/__main__.py` | 001 |
| project metadata | `pyproject.toml` | 001 |
| pyright config | `pyrightconfig.json` (optional) | 001 |
| errors | `src/code_index/errors.py` | 002 |
| config loader | `src/code_index/config.py` | 003 |
| storage open | `src/code_index/storage/__init__.py` | 004 |
| schema constants | `src/code_index/storage/schema.py` (optional) | 004 |
| migrations runner | `src/code_index/storage/migrations/__init__.py` | 004 |
| first migration | `src/code_index/storage/migrations/0_to_1.py` | 004 |
| CLI app | `src/code_index/cli.py` | 005 |
| tests | `tests/test_*.py`, `tests/fixtures/*.toml` | 001–005 |

## Cross-cutting constraints

- **Stream discipline.** stdout = results only; stderr = logs, warnings, progress, errors-in-text-mode. Under `--format json`, stderr stays human-readable and stdout carries exactly one JSON document (success payload or error envelope). Helpers in `errors.py` are the only sanctioned writers; subcommand code never calls `print` directly.
- **`--format` is global.** Wired at the Typer app level; sub-stubs and `config show` both honor it.
- **No emojis, no HTML in any file.**
- **Forward slashes** in any path strings in tests or docs, per project conventions.
- **Schema version is a string.** `"1"` not `1`. Stored as TEXT in `meta.value`.
- **Engine version source.** `code_index.__version__` is the single source; `pyproject.toml` carries it and the package re-exports it (read via `importlib.metadata` or pinned constant — coder's call, but consistent across the package).
- **Migrations runner is idempotent.** Discovers migration files by name, sorts numerically by `<from>`, applies any whose `<from>` matches the current `meta.schema_version` (treating "no meta row yet" as `"0"`), and advances `meta.schema_version` to the migration's `<to>` after each apply. Wraps each migration in its own transaction.
- **sqlite-vec and FTS5 availability are checked at open time**, not at first query. Failure raises `CodeIndexError` with the correct `kind`/`code`.

## Shared vocabulary

- **Engine version** — value in `pyproject.toml`'s `[project].version`, surfaced as `code_index.__version__`.
- **Schema version** — string stored at `meta.schema_version`; current value `"1"`.
- **Resolved config** — config after defaults applied and validation passed; what `config show` prints.
- **Error envelope** — JSON object on stdout under `--format json` for failures; shape pinned in `errors-and-exit-codes.md`.
- **Stub** — subcommand that prints the not-implemented message and exits 1 (or emits the envelope under `--format json`).

## Dependency direction

```
001 package-skeleton
   |
002 errors
   |     \
003 config  004 storage
        \  /
        005 cli
```

Storage (004) and config (003) are siblings; both depend only on errors (002). CLI (005) depends on both.

## Phase 1 DoD (the contract)

Per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md):

- `uv sync --extra dev` succeeds.
- `uv run pytest` passes.
- `uv run ruff check` passes.
- `uv run pyright` passes.
- `code_index --help` lists every MVP subcommand named in `cli.md`.
- `code_index config show --config <fixture>` validates the fixture, prints resolved values to stdout, exits 0.
- Each Config-category failure mode from `errors-and-exit-codes.md` produces the documented `code` and `kind` under `--format json`.

`uv tool install --editable .` is the user-facing install command; the verifier substitutes `uv sync --extra dev` because it is faster and equivalent in proving deps resolve.
