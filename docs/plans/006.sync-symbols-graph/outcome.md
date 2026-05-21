# Outcome — Feature 006 sync-symbols-graph

Phase 6 is implementation against pinned design. Expected doc deltas are observation-flavored: the architect may pick up or reject each candidate during finalization. The `## Observations` section at the bottom is populated by the coder after the steps land.

## Candidate doc updates

### `docs/architecture/cli.md`

- **Section:** `code_index index sync` — output shape.
  **Change:** Add a brief note pinning the `--format json` shape Phase 6 produces (`files_added`, `files_changed`, `files_unchanged`, `files_removed`, `chunks_inserted_total`, `seconds_elapsed`).
  **Reason:** `cli.md` currently says nothing about the sync summary. Phase 6 makes the shape stable from day one; users (and Phase 7's JSON polish) benefit from having the shape pinned at the doc level.
  **Architect call:** apply if the doc-level visibility is wanted; otherwise leave as implementation detail and Phase 7 documents it then.

- **Section:** `code_index index rebuild` — flag table.
  **Change:** Confirm the flag surface is `--yes` plus the cross-cutting `--verbose` / `--format` / `--config`. Add an explicit note that `--root` and `--dry-run` are intentionally not supported on `rebuild`.
  **Reason:** Phase 6 deliberately keeps the flag surface narrow; without a doc note, a future reader might add `--root` to mirror `index build`.
  **Architect call:** likely apply — it is a small, defensive addition.

- **Section:** `code_index graph` — path semantics for `deps`.
  **Change:** Document that the `<path>` argument is exact-match against `chunks.path`, project-root-relative with forward slashes. No globbing, no substring.
  **Reason:** `cli.md` is currently silent on the matching semantics for `graph deps`. The `symbols` section explicitly pins substring-by-default, `--exact`-for-exact for names; `graph deps` deserves the same explicitness for paths.
  **Architect call:** apply — closes a real ambiguity in the doc.

### `docs/architecture/errors-and-exit-codes.md`

- **Section:** Exit code table (`1` row) — enumerated failure surface.
  **Change:** Add `usage.confirmation_required` to the enumerated failure surface under code 1.
  **Reason:** Phase 6's `index rebuild` without `--yes` raises `CodeIndexError(EXIT_USAGE, "usage.confirmation_required", ...)`. The kind is currently a free string at the raise site (per `002.context.md`); formalizing it in the registry is the architect's choice. If applied, also add `Kinds.USAGE_CONFIRMATION_REQUIRED` to `code_index.errors.Kinds`.
  **Architect call:** apply if the architect wants the kind contract complete; reject if the kind should stay informal until a second consumer appears.

### No-change items (documented here for traceability)

These were considered and explicitly rejected:

- **`docs/architecture/storage.md`:** no change. Phase 6 is a pure consumer of the v1 schema; the `files` table and edge resolution sections are already accurate.
- **`docs/architecture/architecture.md`:** no change. The "Sync" data-flow section is the spec Phase 6 implements; matches the algorithm in `context.md`.
- **`docs/architecture/chunking-and-languages.md`:** no change. Phase 6 reads symbol identity per the existing "Symbol identity" section.
- **`docs/architecture/mvp-phases.md`:** no change. Phase 6 DoD is what Phase 6 ships.

## Observations

_populated by the coder as steps complete_

- Step 002: `index rebuild` raises `CodeIndexError` with the raw kind string `"usage.confirmation_required"` at the single raise site in `cli.py`. The corresponding `Kinds.*` entry was intentionally not added (per `002.context.md`). Possible impact: if the architect picks up the candidate update to `docs/architecture/errors-and-exit-codes.md` (code 1 row) and adds `Kinds.USAGE_CONFIRMATION_REQUIRED`, the raise site in `cli.cli_index_rebuild` should be flipped to reference the registry constant.

## Applied 2026-05-21

- cli.md: pinned `index sync` JSON shape; documented `index rebuild` deliberate-omissions on `--root`/`--dry-run`; pinned `graph deps` path-match semantics (exact, root-relative, forward slashes).
- errors-and-exit-codes.md: added `usage.confirmation_required` to the CLI scaffolding (code 1) surface; clarified that this entry is not transient.
- storage.md, architecture.md, chunking-and-languages.md, mvp-phases.md: no changes (per outcome).
- Follow-up flagged (out of architect scope): flip the raw `"usage.confirmation_required"` literal in `src/code_index/cli.py` to a new `Kinds.USAGE_CONFIRMATION_REQUIRED` constant.
