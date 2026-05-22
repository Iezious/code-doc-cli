# Outcome — feature 007 config-show-json-polish

Architecture deltas this feature implies. Applied by `/architect` at finalization.

## Planner section

### `docs/architecture/cli.md`

- **Target section:** `code_index init` subsection.
- **Change:** add an inline-documented JSON shape under `--format json`:

  ```json
  {
    "config_path": "/abs/path/docs/.helpers/config.toml",
    "gitignore_path": "/abs/path/docs/.helpers/.gitignore",
    "project": "my-project",
    "force_used": false
  }
  ```

  Note that `force_used` is `true` iff `--force` was passed AND an existing file was overwritten; `false` for fresh init or no-op `--force`.
- **Reason:** Phase 7 pins the `init` JSON shape that was previously unspecified. The shape is part of the CLI contract per `cli.md` "Cross-cutting behaviors": "`--format json` is supported wherever results are structured. The JSON shape is part of the contract and changes only with a CLI major version."

### `docs/architecture/cli.md`

- **Target section:** `code_index config show` subsection.
- **Change:** add the inline-documented JSON shape under `--format json`:

  ```json
  {
    "config": {
      "version": "...",
      "project": "...",
      "project_root": "/abs/path",
      "config_path": "/abs/path/docs/.helpers/config.toml",
      "roots": ["..."],
      "ignores": ["..."],
      "languages": null,
      "extra_languages": [],
      "embed_backend": "fastembed",
      "embed_model": "...",
      "embed_batch_size": 32
    },
    "index": {
      "schema_version": "1",
      "code_index_version": "...",
      "embed_model": "...",
      "embed_dim": "768"
    }
  }
  ```

  Note that `"index"` is `null` when the index file is absent. `meta` values inside the `"index"` block are strings (matching SQLite TEXT storage).
- **Reason:** Phase 1 pinned the `{"config": {...}}` shape but explicitly deferred the `"index"` sibling to Phase 7. Phase 7 finalizes the shape; `cli.md` should document it inline alongside the subcommand prose.

### `docs/architecture/cli.md`

- **Target section:** `code_index config show` subsection.
- **Change:** add a sentence documenting the diagnostic-vs-gating semantics:

  > `config show` is the only subcommand that does not refuse on a schema, model, or dim mismatch. Mismatches are reported (both the configured value and the stored `meta` value appear in the output) and the exit code stays 0. Use `config show` to diagnose drift; use `index rebuild` to resolve it.

- **Reason:** Phase 7 implements this carve-out (per `context.md` decision 1). Without documentation, the behavior looks inconsistent with `errors-and-exit-codes.md`'s loud-failure stance for codes 10 and 11. The carve-out is intentional and should be on the prose.

### `docs/architecture/errors-and-exit-codes.md`

- **Target section:** "Enumerated failure surface".
- **Change:** add a new subsection "### Usage / CLI (code 1)" (or extend the existing CLI-scaffolding subsection added by Phase 1's outcome) with two new entries:
  - `User confirmation required for a destructive operation → usage.confirmation_required (code 1)`. Producer: `code_index index rebuild` without `--yes`.
  - `CLI flag value not in the flag's allowed enum → cli.bad_enum (code 1)`. Producer: `code_index search --mode <bad>`. Distinct from `config.bad_enum` (code 2), which covers TOML enum violations.
- **Reason:** Phase 7 registers both as `Kinds` constants. Per `errors-and-exit-codes.md` "Implications": "Adding a new failure mode is additive — new `kind`, new entry on the table, possibly a new exit code in the relevant decade." Both new kinds reuse the existing code 1; the table needs the new entries to stay authoritative.

### `docs/architecture/errors-and-exit-codes.md`

- **Target section:** "Enumerated failure surface" → "Embedding backend (codes 20, 21, 22)".
- **Change:** add a note that `backend.model_download_failed` and `backend.encode_failed` now have producers: `code_index.embeddings.from_config(...)` / `FastembedBackend.__init__` for the former; `FastembedBackend.encode(...)` for the latter. Both produce code 20.
- **Reason:** Phase 1 registered both kinds with no producer (transient/no-op at the time). Phase 7 wires the producers. The doc is correct as-is — both entries are already listed — but a one-line "producer" callout per kind would document the now-active state. Architect's call whether to inline this or leave it implicit.

### `docs/architecture/embeddings.md`

- **Target section:** "Backend interface" or "Implications".
- **Change:** add one sentence stating that backend `__init__` and `encode` failures surface as `CodeIndexError` with `backend.model_download_failed` (code 20) and `backend.encode_failed` (code 20) respectively; agents should distinguish by `kind` since both share code 20.
- **Reason:** Phase 7 establishes this contract. `embeddings.md` is the right home for it; `errors-and-exit-codes.md` already enumerates the kinds. The cross-reference closes the loop.

## Scope summary (for the architect's record)

Phase 7 ships: full `config show` diagnostic body, pinned JSON shapes for `init` and `config show`, fastembed exception wrapping into `CodeIndexError`, two new `Kinds` constants formalized, and the cross-subcommand JSON round-trip DoD test. Phase 7 DoD per `mvp-phases.md`:

- `uv sync --extra dev` succeeds (no new deps).
- `uv run pytest` / `uv run ruff check` / `uv run pyright` all pass.
- Every MVP subcommand under `--format json` round-trips through `json.loads` (operationalized in `tests/test_json_roundtrip_dod.py`).
- Failure conditions emit a parseable error envelope with the documented `code` / `kind` (same test file).

## Observations

---
Status: Applied 2026-05-21
Applied items: 6
Rejected items: 0
