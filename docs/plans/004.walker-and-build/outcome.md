# Feature 004 — outcome

Architecture deltas this feature implies. Architect applies these during
finalization after every step is `done` with verifier `PASS`.

## `docs/architecture/cli.md`

- **Section: `code_index index build`.** Pin the auto-rebuild semantics:
  when the index already contains rows, `index build` silently drops the
  row data from `chunks`, `chunks_fts`, `embeddings`, `symbols`, `edges`,
  `files`, and resets the indexer-owned `meta` keys (`embed_model`,
  `embed_dim`) before inserting. `meta.schema_version` is preserved. No
  `--force` flag is added or required.
  - Reason: behavior chosen by the user during planning. `index build`
    and `index rebuild` (Phase 6) end up calling the same underlying drop
    path; the distinction between the two subcommands is a user-facing
    convention rather than a state-machine difference. Documenting this
    here keeps the Phase 6 design honest.

- **Section: `code_index index build` flag table.** Confirm that the only
  flags in Phase 4 are `--root`, `--dry-run`, `--verbose`. No `--strict`
  (see next entry).

## `docs/architecture/cli.md` + `docs/architecture/errors-and-exit-codes.md`

- **`--strict` flag inconsistency.** `errors-and-exit-codes.md` names a
  `--strict` mode under "Default vs `--strict` mode" and references it
  from the parsing (code 30) and IO/oversize (code 41) entries.
  `cli.md` does not list `--strict` on any subcommand's flag table.
  Phase 4 defers the resolution; Phase 6 (sync / rebuild) is the natural
  decision point.
  - Reason: introducing `--strict` across one subcommand without the
    others would create a worse inconsistency. The architect should
    either (a) add `--strict` to the relevant cli.md flag tables so
    Phase 6 implements it across `index build`, `index sync`, and
    `index rebuild` together, or (b) remove the `--strict` references
    from errors-and-exit-codes.md and treat skip-and-warn as the only
    mode. Phase 4's behavior is consistent with either resolution.

## `docs/architecture/architecture.md`

- **Section: Indexer walking / Binary detection.** Observation, not a
  required change: the doc says "the NUL probe runs only for
  unknown-extension files that could still be plaintext". In practice
  the walker already rejects unknown extensions at an earlier filter,
  so the NUL probe ends up running against files whose extension *is*
  plugin-registered — i.e. as a belt-and-suspenders check for files
  whose extension matches a plugin but whose content is binary
  (accidental blobs in source trees). The architect may want to either
  reword the doc to match what is implemented, or pin the original
  wording and adjust the walker. Phase 4 chose the belt-and-suspenders
  reading; the polyglot fixture's `data.bin` would be filtered by the
  extension check alone, so this is not load-bearing for the DoD test.

## `docs/architecture/config.md`

No change. Phase 4 implements the "What `init` writes" section exactly
as documented.

## `docs/architecture/storage.md`

No change. Auto-rebuild clears row data only; `meta.schema_version` and
the schema itself are untouched. The doc's existing language about
"refusing queries on schema mismatch" continues to hold. The `files`
table (added to schema v1 in the 2026-05-19 sync-mechanism revision)
is populated by this phase's indexer per the spec already in
`storage.md`'s "Sync state" subsection — no doc change needed.

## `docs/architecture/embeddings.md`

No change. The indexer drives `backend.encode(batch)` per the existing
protocol; empty input is a no-op per the Phase 2 backend implementation.

## Observations

- Step 001: `pathspec>=0.12` resolved to `pathspec==1.1.1` on install. Newer pathspec deprecates the `"gitwildmatch"` factory name in favor of `"gitignore"` (GitIgnoreBasicPattern / GitIgnoreSpecPattern). The walker still uses `"gitwildmatch"` per the pinned wording in `architecture.md` ("Indexer walking" -> "Ignore sources") and `001.context.md` ("Use `pathspec` with `GitWildMatchPattern`"), which surfaces ~1000 `DeprecationWarning` lines in the walker test output. Possible impact: the architect may want to update `architecture.md`'s "Indexer walking" wording to allow either `gitwildmatch` or `gitignore`, or pin a tighter upper bound on `pathspec` (`pathspec>=0.12,<1` keeps the legacy name authoritative). The semantic behavior is unchanged either way.
