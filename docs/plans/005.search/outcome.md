# Outcome — Phase 5 / search

Architecture deltas this feature implies. The architect applies these
to `docs/architecture/*.md` during finalization and appends an
`Applied YYYY-MM-DD` footer at the bottom of this file.

## Deltas grouped by target file

### `docs/architecture/storage.md`

- **Section:** new subsection at the end (or fold into "Schema
  versioning" / "Embedding storage").
- **Intended change:** document the exported helper
  `verify_index_compat(conn, backend) -> None` in the storage
  module. State that it raises `index.embed_model_mismatch`
  (code 11) when `meta.embed_model` differs from `backend.name`,
  `index.embed_dim_mismatch` (code 11) when `meta.embed_dim`
  differs from `str(backend.dim)`, and treats missing meta keys
  as a model mismatch with a `code_index index rebuild` prompt.
- **Reason:** Phase 5 introduces the helper in `code_index.storage`
  rather than inline in `search.py` so Phase 6's `symbols` and
  `graph` subcommands can reuse it without duplicating the
  loud-fail check. Storage is the right home — it owns the
  `meta` reads already. Pinning the helper in the doc keeps the
  contract visible to Phase 6's planner.

### `docs/architecture/cli.md`

- **Section:** `code_index search` subsection — append a "JSON
  shape" paragraph (or new sub-subsection) after the flag table.
- **Intended change:** document the `--format json` output shape
  for `search`:
  ```
  {
    "results": [
      {
        "path": "<string>",
        "start_line": <int>,
        "end_line": <int>,
        "language": "<string>",
        "kind": "<string>",
        "name": "<string or null>",
        "scope": "<string or null>",
        "excerpt": "<string>",
        "score": <float>
      }
    ]
  }
  ```
  Zero results: `{"results": []}`. Errors: the standard error
  envelope from `errors-and-exit-codes.md`.
- **Reason:** `cli.md` mentions `--format json` returns "a stable
  JSON array, suitable for agent consumption" but does not pin
  the row shape. Phase 5 ships the first subcommand with a
  finalized JSON output, so the shape needs to be in the doc.
  Phase 7's "JSON polish" pass adopts this shape as-is.

### `docs/architecture/retrieval.md`

- No change required. The doc already pins `k = 60`, the
  filter-on-both-pools rule, candidate pool defaults, the tie-break
  rule, and the ~30-line excerpt default. Phase 5 implements
  against the existing contract.

### `docs/architecture/errors-and-exit-codes.md`

- No new entries. Phase 5 raises only existing kinds:
  `index.missing` (code 12), `index.embed_model_mismatch` (code
  11), `index.embed_dim_mismatch` (code 11),
  `index.schema_mismatch` (code 10, raised by `open_index` from
  Phase 1), `config.unknown_language` (code 2, for `--lang`
  validation), `config.bad_enum` (code 2, for `--mode` if the
  coder routes through `CodeIndexError` rather than letting
  Typer's enum validator emit usage exit code 2 directly).

## Observations

_Populated by the coder as steps complete._

- Step 002: Dense (and therefore hybrid) mode always surfaces the top-`dense_k`
  nearest neighbors regardless of relevance, so "zero results" under hybrid
  mode is unreachable for any query that produces a valid embedding. The
  Phase 5 DoD bullet "Zero results, text mode" is only satisfiable under
  `--mode bm25` (FTS5 returns zero rows for an out-of-corpus token).
  Possible impact: add a sentence to `docs/architecture/retrieval.md`
  noting that the dense pool has no relevance floor — operators relying on
  "no output = nothing relevant" must use `--mode bm25`, or wait for a
  Phase 7 score threshold.

## Applied 2026-05-21

- storage.md: added "Compat check: verify_index_compat" subsection.
- cli.md: replaced search "--format json" one-liner with the pinned JSON shape block (Phase 5 contract).
- retrieval.md: appended dense-no-floor note under "Candidate pool sizes" (covers coder observation on step 002).
- errors-and-exit-codes.md, rest of retrieval.md: no changes (per outcome).
