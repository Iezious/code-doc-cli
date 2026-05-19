# Outcome — feature 001 foundations

Architecture deltas this feature implies. Applied by `/architect` at finalization.

## Planner section

### `docs/architecture/errors-and-exit-codes.md`

- **Target section:** "Enumerated failure surface" — add a new subsection "### CLI scaffolding (code 1)" (placed immediately after the "Config (code 2)" subsection to keep numeric order? — code 1 is "usage" so place either before Config or as a sub-entry under "Exit code table"; architect picks. Suggest a new subsection "CLI scaffolding (code 1)" before "Config (code 2)" since `usage` is already in the table at code 1).
- **Change:** add the entry `Unimplemented subcommand stub → cli.not_implemented (code 1)`.
- **Reason:** Phase 1 lands stubs for every MVP subcommand to satisfy `code_index --help`. The stubs need a stable `kind` so agents can distinguish "not implemented yet in this build" from "real usage error". This `kind` is transient — entries are removed from the enumerated surface as later phases (4, 5, 6) implement each subcommand. Note the transience in the subsection text so it does not look like a permanent failure mode.

### `docs/architecture/storage.md`

- **Target section:** "Schema versioning".
- **Change:** add one sentence stating that fresh schema creation is itself migration `0_to_1.py`, applied via the same migrations harness that handles upgrades. Today the section says "Migrations are forward-only and live in `code_index.storage.migrations.<from>_to_<to>.py`" but does not pin that creation flows through this path.
- **Reason:** Phase 1's storage layer makes this choice concrete and the doc should match. Removes the ambiguity of "does fresh-create use migrations or a separate CREATE TABLE path?".

### `docs/architecture/config.md`

- **Target section:** "Implications" (append) — **low priority; drop if architect prefers config.md stays implementation-neutral.**
- **Change:** add one sentence noting that validation is implemented via Pydantic v2 models.
- **Reason:** records the user-confirmed implementation choice in a non-load-bearing way. Coder note: skip this entry entirely if the architect prefers implementation neutrality; the decision is recorded in `context.md` regardless.

### `docs/architecture/cli.md`

- **Target section:** "`code_index config show`" plus "Output streams and logging".
- **Change:** add a sentence noting that Phase 1's `config show` prints **resolved config only**; Phase 7 extends it with `index` metadata (schema_version, embed_model). Optionally include the Phase 1 JSON shape (see `005.context.md`) as the documented contract under `--format json`.
- **Reason:** the section currently describes the final-state behavior. Pinning the Phase 1 intermediate shape avoids drift between this plan and Phase 7's plan.

## Scope summary (for the architect's record)

Phase 1 ships: package skeleton, errors infrastructure, config loader, storage layer with migrations harness, CLI scaffold with stubs and a working `config show`. Phase 1 DoD per `mvp-phases.md`:

- `uv sync --extra dev` succeeds.
- `uv run pytest` / `uv run ruff check` / `uv run pyright` all pass.
- `code_index --help` lists every MVP subcommand.
- `code_index config show --config <fixture>` validates the fixture and prints resolved values, exit 0.
- Each Config-row in `errors-and-exit-codes.md` produces the documented `code` / `kind` under `--format json`.

## Observations

- Step 005: chose `kind = "unknown"` (not `"unknown.exception"`) for the unhandled-exception envelope (`code = 99`). Documented inline in `src/code_index/cli.py` (`_UNKNOWN_KIND`) and pinned by `tests/test_cli.py::test_unhandled_exception_envelope`. Possible impact: add a line under "Enumerated failure surface" in `docs/architecture/errors-and-exit-codes.md` recording `"unknown" (code 99)` as the catch-all kind alongside the existing exit-code-table entry. The doc currently names code 99 in the table but does not pin a `kind` string for it.
- Step 005: Phase 1 `config show` JSON shape is the single key `"config"` containing eleven fields (the resolved-config fields plus `project_root` and `config_path`). Pinned by `tests/test_cli.py::test_config_show_valid_json`. Phase 7 will add an `"index"` sibling per the planner's `cli.md` delta in this outcome file.
- Step 005: the `cli.not_implemented` `detail` payload includes `subcommand` and `phase` keys so agents can dispatch on either; not yet documented in `errors-and-exit-codes.md`. Possible impact: add a one-line note in the upcoming "CLI scaffolding (code 1)" subsection naming the detail keys.
