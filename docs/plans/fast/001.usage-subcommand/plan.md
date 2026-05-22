# Fast feature 001 — usage-subcommand: plan

## Goal

Add a top-level `code_index usage [<topic>]` Typer subcommand that reads agent-facing manual pages packaged inside the wheel at `code_index/usage/*.md`, so agents installed via `uv tool install code_index` can access usage docs at runtime in both text and JSON formats.

## Files to create or modify

Move + rewrite cross-refs (no LoC, but mandatory):

- `USAGE.md` → `src/code_index/usage/USAGE.md` — move; no cross-ref changes expected (it's the index).
- `docs/usage/init.md` → `src/code_index/usage/init.md` — move; rewrite any `docs/architecture/*.md` link to `../../../docs/architecture/*.md`.
- `docs/usage/index-build.md` → `src/code_index/usage/index-build.md` — same.
- `docs/usage/index-sync.md` → `src/code_index/usage/index-sync.md` — same.
- `docs/usage/index-rebuild.md` → `src/code_index/usage/index-rebuild.md` — same.
- `docs/usage/search.md` → `src/code_index/usage/search.md` — same.
- `docs/usage/symbols.md` → `src/code_index/usage/symbols.md` — same.
- `docs/usage/graph.md` → `src/code_index/usage/graph.md` — same.
- `docs/usage/config-show.md` → `src/code_index/usage/config-show.md` — same.
- `src/code_index/usage/USAGE.md` — also rewrite internal links: any `docs/usage/<name>.md` link inside it becomes `<name>.md` (sibling), and any `docs/architecture/*.md` link becomes `../../../docs/architecture/*.md`.
- Delete the empty `docs/usage/` directory after moves.

Create:

- `USAGE.md` (repo root) — thin 3-5 line pointer document. Replaces the moved file.

Modify:

- `src/code_index/cli.py` — register a new top-level `usage` command using the existing `@app.command(...)` pattern. Add the topic catalog (a frozen list of 9 names) and a small loader using `importlib.resources.files("code_index") / "usage" / "<name>.md"`. Map `usage` and the no-arg case to `USAGE.md`; map the other 8 names to `<name>.md`. On unknown topic, raise `CodeIndexError` with `Kinds.CLI_BAD_ENUM`.
- `pyproject.toml` — add `[tool.hatch.build.targets.wheel.force-include]` rule mapping `"src/code_index/usage" = "code_index/usage"`. Optional stretch: bump `version` from `"0.1.0"` to `"0.2.0"`.

Tests:

- `tests/test_usage_cli.py` — new, full coverage of the success and failure paths.
- `tests/test_json_roundtrip_dod.py` — extend with one success entry (`["usage", "init"]` or equivalent) and one failure entry (`["usage", "garbage"]`) **only if** the addition is 1-2 lines and matches the existing parametric pattern. If it requires fixture surgery, skip and note in `outcome.md`.

## Signatures

The new Typer command on `app` (in `src/code_index/cli.py`):

```python
@app.command("usage")
def cli_usage(
    ctx: typer.Context,
    topic: Annotated[
        str | None,
        typer.Argument(help="Usage topic to display; omit for the index page."),
    ] = None,
) -> None:
    ...
```

Module-level constants in `src/code_index/cli.py` (names indicative; coder may rename):

```python
USAGE_INDEX_NAME: str = "usage"
USAGE_TOPICS: tuple[str, ...] = (
    "usage",
    "init",
    "index-build",
    "index-sync",
    "index-rebuild",
    "search",
    "symbols",
    "graph",
    "config-show",
)
```

JSON success shape (under `--format json`):

```json
{
  "topic": "<resolved-name>",
  "content": "<markdown body>",
  "available": ["usage", "init", "index-build", "index-sync", "index-rebuild", "search", "symbols", "graph", "config-show"]
}
```

JSON failure shape on unknown topic — standard error envelope with:

```json
{
  "error": {
    "code": 1,
    "kind": "cli.bad_enum",
    "message": "unknown topic: '<value>'; expected one of: usage, init, index-build, index-sync, index-rebuild, search, symbols, graph, config-show",
    "detail": {
      "flag": "<topic>",
      "value": "<value>",
      "expected": ["usage", "init", "index-build", "index-sync", "index-rebuild", "search", "symbols", "graph", "config-show"]
    }
  }
}
```

Resource resolution: `importlib.resources.files("code_index") / "usage" / f"{filename}.md"` where `filename = "USAGE"` when the resolved topic is `"usage"` and `filename = topic` otherwise.

## Tests

All tests live in `tests/test_usage_cli.py` and invoke the CLI via Typer's `CliRunner` (matching the existing pattern in `tests/test_init_cli.py` / `tests/test_config_show_cli.py`).

- `test_usage_no_arg_text` — `code_index usage` exits 0; stdout starts with `# code_index` (the heading from `USAGE.md`); stderr is empty.
- `test_usage_no_arg_json` — `code_index --format json usage` exits 0; stdout parses as JSON with `topic == "usage"`, non-empty `content`, and `available` equal to the full 9-name catalog list in declared order.
- `test_usage_init_text` — `code_index usage init` exits 0; stdout is raw markdown starting with `# code_index init`.
- `test_usage_init_json_contains_marker` — `code_index --format json usage init` exits 0; JSON `topic == "init"`; `content` contains a marker substring drawn from the current `init.md` body (e.g. `"Scaffold"` — coder picks a stable substring at implementation time).
- `test_usage_all_topics_json` — parametric over all 9 catalog names; each invocation exits 0 and JSON `topic` matches the requested name; `content` is non-empty.
- `test_usage_unknown_topic_json` — `code_index --format json usage garbage` exits 1; stdout is a single JSON document with `error.kind == "cli.bad_enum"`, `error.code == 1`, `error.detail.flag == "<topic>"`, `error.detail.value == "garbage"`, and `error.detail.expected` equal to the 9-name catalog.
- `test_usage_unknown_topic_text` — `code_index usage garbage` exits 1; stderr summary mentions the bad value and lists allowed values; stdout is empty.
- `test_usage_resource_present` — sanity test that `importlib.resources.files("code_index") / "usage" / "USAGE.md"` is readable from the test process (guards against the pyproject force-include regressing).

Cross-subcommand roundtrip test extension (optional, only if trivial):

- In `tests/test_json_roundtrip_dod.py`, add one success entry `(["usage", "init"], ...)` and one failure entry `(["usage", "garbage"], ...)` to the existing parametric data. If the existing fixture shape requires more than 1-2 lines of plumbing per case, skip and record the gap in `outcome.md`.

## Definition of done

- `code_index usage` (no args) prints the contents of `USAGE.md` to stdout under `--format text` and exits 0.
- `code_index usage <name>` for each of the 9 catalog names prints the matching markdown body under `--format text` and exits 0.
- `code_index --format json usage [<name>]` emits the JSON success shape above with `topic`, `content`, and `available` for every catalog name and exits 0.
- `code_index usage <bad>` exits 1 with `kind == "cli.bad_enum"` under `--format json`, and prints a stderr summary listing allowed topics under `--format text`. Stdout is empty in text mode; stdout is the error envelope in JSON mode.
- `src/code_index/usage/*.md` contains all 9 markdown files; the originals at repo root (`USAGE.md`) and under `docs/usage/` have been moved (repo-root `USAGE.md` replaced with the thin pointer; `docs/usage/` removed if empty).
- Internal cross-references in the moved files have been rewritten so that links to `docs/architecture/*.md` resolve from the new location (`../../../docs/architecture/<file>.md`).
- `pyproject.toml` contains the `[tool.hatch.build.targets.wheel.force-include]` rule mapping `"src/code_index/usage" = "code_index/usage"`. The wheel built from this checkout (verifier may invoke `uv build` or rely on the `test_usage_resource_present` test plus the editable install) contains `code_index/usage/*.md`.
- `tests/test_usage_cli.py` exists and passes.
- `uv run pytest` passes the full suite.
- `uv run ruff check` passes.
- `uv run pyright` passes.
- Stretch (if performed): `pyproject.toml` `version` is `"0.2.0"`.

## Out of scope

- Updating `docs/architecture/cli.md` to document the new subcommand — deferred to `/architect` via `outcome.md`.
- Updating `docs/architecture/errors-and-exit-codes.md` to add `usage` as a producer of `cli.bad_enum` — deferred to `outcome.md`.
- README updates beyond the new repo-root `USAGE.md` pointer.
- Tagging `v0.2.0`.
- Renaming or refactoring unrelated subcommands.
- Adding a `--list` flag or any topic-discovery affordance beyond the `available` field in JSON output.
- Tutorials, examples, or expanded content inside the moved markdown files (move-and-rewrite-links only).
