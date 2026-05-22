# Fast feature 001 — usage-subcommand: context

## Goal in one paragraph

Ship the agent-facing usage manual inside the wheel so that downstream Claude agents who installed `code_index` via `uv tool install code_index` (no repo clone) can read the manual at runtime through a new top-level `code_index usage [<topic>]` subcommand. Currently the manual lives at the repo root (`USAGE.md`) and under `docs/usage/*.md` — accessible only to people with the repo checked out.

## Scope

- One new top-level Typer command: `code_index usage`.
- A package-resource directory `src/code_index/usage/` carrying the 9 markdown files distributed in the wheel.
- A pyproject change forcing wheel inclusion of those markdowns.
- A repo-root pointer `USAGE.md` (replaces the current full document).
- One new test module plus a small extension to the cross-subcommand DoD roundtrip test (only if a 1-2 line addition fits the existing pattern).
- Optional stretch: bump `version = "0.1.0"` → `version = "0.2.0"` in `pyproject.toml`.

## Files involved

CLI surface:

- `src/code_index/cli.py` — register the new `usage` command at module top-level alongside `init`.

Packaged resources (all to be created by moving existing files):

- `src/code_index/usage/USAGE.md` — moved from repo-root `USAGE.md`.
- `src/code_index/usage/init.md` — moved from `docs/usage/init.md`.
- `src/code_index/usage/index-build.md` — moved from `docs/usage/index-build.md`.
- `src/code_index/usage/index-sync.md` — moved from `docs/usage/index-sync.md`.
- `src/code_index/usage/index-rebuild.md` — moved from `docs/usage/index-rebuild.md`.
- `src/code_index/usage/search.md` — moved from `docs/usage/search.md`.
- `src/code_index/usage/symbols.md` — moved from `docs/usage/symbols.md`.
- `src/code_index/usage/graph.md` — moved from `docs/usage/graph.md`.
- `src/code_index/usage/config-show.md` — moved from `docs/usage/config-show.md`.

Originals to be deleted after move (these are the same paths listed above, on the source side):

- `USAGE.md` (repo root) — replaced with a thin pointer (see below), not deleted.
- `docs/usage/init.md`, `docs/usage/index-build.md`, `docs/usage/index-sync.md`, `docs/usage/index-rebuild.md`, `docs/usage/search.md`, `docs/usage/symbols.md`, `docs/usage/graph.md`, `docs/usage/config-show.md` — deleted.
- `docs/usage/` directory — removed if empty after the moves.

Repo-root pointer:

- `USAGE.md` — replaced with 3-5 line pointer to `src/code_index/usage/USAGE.md` and the `code_index usage` CLI.

Build config:

- `pyproject.toml` — add explicit `[tool.hatch.build.targets.wheel.force-include]` rule mapping `"src/code_index/usage" = "code_index/usage"`. Optional stretch: bump `version` to `0.2.0`.

Tests:

- `tests/test_usage_cli.py` (new).
- `tests/test_json_roundtrip_dod.py` — extend with one success and one failure entry **only if** it is a 1-2 line addition matching the existing parametric pattern; otherwise document the gap in `outcome.md`.

## Facts and constraints distilled from architecture

- The top-level `app` is a `BoundaryTyper` in `src/code_index/cli.py` (line ~87). New commands register via the `@app.command("<name>")` decorator — same pattern as `cli_init` at lines 163-188. See [`docs/architecture/cli.md`](../../../architecture/cli.md), "Subcommands".
- Cross-cutting flags (`--config`, `--format`, `--verbose`, `--quiet`) are populated on `ctx.obj` by the top-level callback. Subcommands branch on `ctx.obj.get("format", "text")`. The new command only needs to read `format`.
- Error envelope contract — `{"error": {"code", "kind", "message", "detail"}}` on stdout under `--format json`, stderr summary otherwise — is defined in [`docs/architecture/errors-and-exit-codes.md`](../../../architecture/errors-and-exit-codes.md). Unknown-topic uses **`Kinds.CLI_BAD_ENUM`** (exit code 1), same kind that `search --mode <bad>` produces. `detail` must include `flag` (`"<topic>"`), `value` (the rejected string), and `expected` (the full 9-name catalog list).
- Output streams: stdout carries the markdown result; stderr stays empty on success per the "Output streams and logging" section of `cli.md`.
- Writers live in `errors.py` and are re-exported by `cli.py`:
  - `write_result_stdout(payload: str) -> None` — for raw text (adds trailing newline).
  - `write_json_stdout(payload: object) -> None` — for compact JSON via `json.dumps(payload)`.
  - Use `write_result_stdout` for `--format text`, `write_json_stdout` for `--format json` (matches `cli_config_show`).

## Resource access strategy

Use `importlib.resources.files("code_index") / "usage" / "<name>.md"` then `.read_text(encoding="utf-8")`. This works for both editable (`uv tool install --editable .`) and built-wheel installs. No new `importlib.resources` usage exists in `src/code_index/`; the coder is free to keep the loader inline in `cli.py` or split into a tiny helper module — both are acceptable.

## Topic catalog (fixed)

Nine names:

1. `usage` — maps to `USAGE.md` (also the default for bare `code_index usage`).
2. `init` → `init.md`
3. `index-build` → `index-build.md`
4. `index-sync` → `index-sync.md`
5. `index-rebuild` → `index-rebuild.md`
6. `search` → `search.md`
7. `symbols` → `symbols.md`
8. `graph` → `graph.md`
9. `config-show` → `config-show.md`

Bare `code_index usage` (no topic argument) is equivalent to `code_index usage usage`.

## Cross-reference rewrites

The 8 detail files (currently at `docs/usage/<name>.md`) contain links to `docs/architecture/<file>.md`. From their new home at `src/code_index/usage/<name>.md`, the correct relative path is `../../../docs/architecture/<file>.md`. Rewrite all such links at move time. The repo-root `USAGE.md` pointer uses a relative path `src/code_index/usage/USAGE.md` so it renders correctly on GitHub.

## Out of scope (will not be done in this feature)

- Architecture file updates — surfaced via `outcome.md`, applied by `/architect` later.
- README updates other than the new repo-root pointer.
- GitHub Actions / CI changes.
- Tagging `v0.2.0` (happens after verifier PASS, not part of the plan).
- Docstrings, comments, or refactors in unrelated CLI commands.

## References

- [`docs/architecture/cli.md`](../../../architecture/cli.md) — subcommand surface, output streams, cross-cutting flags.
- [`docs/architecture/errors-and-exit-codes.md`](../../../architecture/errors-and-exit-codes.md) — error envelope, `cli.bad_enum` contract.
- [`docs/plans/CLAUDE.md`](../../CLAUDE.md) — plan layout and lifecycle.
