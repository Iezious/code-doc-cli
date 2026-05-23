# CLI surface

## Decision

`code_index` is a single `typer`-based CLI binary with a small, stable subcommand surface. Every operation an agent or human needs is reachable from one command tree. The CLI is the only supported entry point — there is no Python API contract for external consumers.

## Rationale

- Subagents invoke the tool via Bash. Stable, narrow flags beat a sprawling Python import surface.
- A single binary keeps install simple (`uv tool install ...`) and discovery obvious (`code_index --help`).
- `typer` gives consistent help, completion, and argument validation across subcommands without ceremony.

## Subcommands

### `code_index init`

Initializes `docs/.helpers/` in the current project, writing a default `config.toml` and a `.gitignore` for the index file. Idempotent — refuses to overwrite an existing config without `--force`.

```
code_index init [--name <project-name>] [--force]
```

**JSON shape.** Under `--format json`, `init` emits one document with the shape:

```json
{
  "config_path": "/abs/path/docs/.helpers/config.toml",
  "gitignore_path": "/abs/path/docs/.helpers/.gitignore",
  "project": "my-project",
  "force_used": false
}
```

`force_used` is `true` iff `--force` was passed AND an existing file was overwritten; `false` for fresh init or no-op `--force`. Failures use the standard error envelope from [errors-and-exit-codes](errors-and-exit-codes.md) (refuse-without-`--force` etc.).

### `code_index index build`

Full index build. Walks roots from config, chunks, embeds, stores. Reports counts and timings.

```
code_index index build [--root <path>]   # override config roots
                    [--dry-run]        # walk and chunk but do not embed/store
                    [--verbose]
```

**JSON shape.** Under `--format json`, `index build` emits one document with the shape:

```json
{
  "files_walked": 0,
  "files_chunked": 0,
  "chunks_chunked": 0,
  "chunks_inserted": 0,
  "symbols_inserted": 0,
  "edges_inserted": 0,
  "seconds_elapsed": 0.0
}
```

`files_walked` includes files skipped as binary or oversize; `files_chunked` is the subset that produced chunks. `chunks_chunked` is the number of chunks the language plugins produced; `chunks_inserted` is the subset actually written to the index. Under `--dry-run`, `chunks_chunked > 0` and `chunks_inserted == 0`. Failures use the standard error envelope from [errors-and-exit-codes](errors-and-exit-codes.md).

### `code_index index sync`

Incremental update. For each project file, compares mtime and size against the `files` table (see [storage](storage.md)). Re-chunks and re-embeds files whose mtime or size has changed; inserts new files; deletes rows for files that have vanished from the tree. Does not depend on git.

```
code_index index sync [--verbose]
```

**JSON shape.** Under `--format json`, `index sync` emits one document with the shape pinned by Phase 6:

```json
{
  "files_added": <int>,
  "files_changed": <int>,
  "files_unchanged": <int>,
  "files_removed": <int>,
  "chunks_inserted_total": <int>,
  "seconds_elapsed": <float>
}
```

Failures use the standard error envelope from [errors-and-exit-codes](errors-and-exit-codes.md).

### `code_index index rebuild`

Drops and rebuilds. Required after embedding model changes.

```
code_index index rebuild [--yes]
```

`--root` and `--dry-run` are intentionally not supported on `rebuild`; the command is a forced full rebuild against the configured roots. The flag surface is `--yes` plus the cross-cutting `--config`, `--verbose`, `--format`.

**JSON shape.** Same shape as [`code_index index build`](#code_index-index-build) above. Failures use the standard error envelope from [errors-and-exit-codes](errors-and-exit-codes.md).

### `code_index search`

Hybrid BM25 + dense retrieval. See `retrieval.md`.

```
code_index search "<query>" [--lang <name>]
                         [--k <int>]           # final top-N, default 20
                         [--bm25-k <int>]      # BM25 pool, default 100
                         [--dense-k <int>]     # dense pool, default 100
                         [--kind <kind>]
                         [--path <glob>]
                         [--mode bm25|dense|hybrid]   # default hybrid
                         [--format text|json]
```

**JSON shape.** Under `--format json`, `search` emits one document with the shape pinned by Phase 5:

```json
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

Zero results render as `{"results": []}` and still exit 0 — an empty result set is not an error. Failures use the standard error envelope from [errors-and-exit-codes](errors-and-exit-codes.md).

### `code_index symbols`

Symbol lookup over the stored symbols table.

```
code_index symbols defs <name>           # definitions matching name (substring by default, --exact for exact)
code_index symbols refs <name>           # references
                     [--lang <name>]
                     [--format text|json]
```

Matching is **substring on `name` by default, case-sensitive**. `--exact` switches to exact-match. `--lang <name>` narrows to one language's symbols. Results include the `scope` field for disambiguation; agents that need a fully-qualified handle can concatenate `lang:scope:name`. The `name` strings themselves are plugin-emitted and not normalized by the engine — see [chunking-and-languages](chunking-and-languages.md), "Symbol identity", for the per-language conventions.

### `code_index graph`

Lightweight dep / call queries over the edges table.

```
code_index graph callers <symbol>        # who points at this
code_index graph deps <path>             # what this file/chunk depends on
                   [--lang <name>]
                   [--format text|json]
```

Graph subcommands accept the same `--lang` filter as `symbols`, and the `<symbol>` argument to `graph callers` follows the same substring-by-default, `--exact`-for-exact, case-sensitive rule (see [chunking-and-languages](chunking-and-languages.md), "Symbol identity").

`graph deps <path>` matches `<path>` exactly against the project-root-relative `chunks.path` (forward slashes). No globbing, no substring. This mirrors the explicit substring-by-default / `--exact` rule already documented for `symbols` and `graph callers`.

### `code_index config show`

Prints the resolved configuration (config file values merged with defaults) and the index metadata (schema version, embed model). Useful for "is my index up to date with my config?" checks.

```
code_index config show [--format text|json]
```

`config show` is the only subcommand that does not refuse on a schema, model, or dim mismatch. Mismatches are reported (both the configured value and the stored `meta` value appear in the output) and the exit code stays 0. Use `config show` to diagnose drift; use `index rebuild` to resolve it.

**JSON shape.** Under `--format json`, `config show` emits one document with the shape:

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
    "embed_batch_size": 16
  },
  "index": {
    "schema_version": "1",
    "code_index_version": "...",
    "embed_model": "...",
    "embed_dim": "768"
  }
}
```

`"index"` is `null` when the index file is absent; meta values inside the `"index"` block are strings (matching SQLite TEXT storage).

### `code_index usage`

Prints agent-facing manual pages packaged inside the wheel. The only subcommand whose primary output is markdown content rather than structured data.

```
code_index usage [<topic>] [--format text|json]
```

Bare `code_index usage` returns the `USAGE.md` index page. With a topic argument, it returns that topic's page. The topic catalog is fixed at 9 names: `usage`, `init`, `index-build`, `index-sync`, `index-rebuild`, `search`, `symbols`, `graph`, `config-show`. (Note `usage` as a topic value resolves to the same index page returned by the no-arg form, so the catalog is self-describing.) Unknown topic raises `cli.bad_enum` (code 1) — see [errors-and-exit-codes](errors-and-exit-codes.md).

**JSON shape.** Under `--format json`, `usage` emits one document with the shape:

```json
{
  "topic": "<resolved name>",
  "content": "<markdown body>",
  "available": ["usage", "init", "index-build", "index-sync", "index-rebuild", "search", "symbols", "graph", "config-show"]
}
```

`content` is a raw markdown string; agents may render or display it directly. `available` is included so an agent can discover topics in one call.

### `code_index doctor`

Intended to diagnose common problems in one place: missing extension, schema mismatch, model mismatch, stale index, missing API key for the configured backend.

**Deferred to v1.1** (see [mvp-scope](mvp-scope.md)). Until it ships, each subcommand emits the relevant failure inline using the codes and `kind` strings defined in [errors-and-exit-codes](errors-and-exit-codes.md).

## Cross-cutting behaviors

- All subcommands accept `--config <path>` to override the discovered config file.
- All subcommands return non-zero exit codes on real errors. `search` returning zero results is **not** an error.
- `--format json` is supported wherever results are structured. The JSON shape is part of the contract and changes only with a CLI major version.

## Discovery and config location

- The CLI walks upward from the CWD looking for `docs/.helpers/config.toml`.
- Found → all commands operate against that project.
- Not found → most commands error with a pointer to `code_index init`. Some (`--help`, `usage`, `config show --no-project`) work without a config; `usage` is project-independent by design and reads only packaged resources.

## Output discipline

- Default human output is terse: one result per stanza, file:line prefixed, optional excerpt.
- `--verbose` adds timings, candidate pool sizes, and the fused score per result.
- `--quiet` suppresses progress reporting (useful in pipelines).

## Output streams and logging

- **stdout** carries command results only. In human format that is one result per stanza as described under [Output discipline](#output-discipline); under `--format json` it is exactly one JSON document covering the whole result, or one error envelope on failure (see [errors-and-exit-codes](errors-and-exit-codes.md)).
- **stderr** carries human-readable logs, warnings, and progress reporting. It never carries command results. The format is plain text — there is no structured stderr in MVP.
- **Log levels** are intentionally minimal: progress and warnings at the default level, plus debug timings and candidate-pool sizes under `--verbose`. There is no separate `--log-level` flag; `--verbose` is the single knob.
- **`--quiet`** suppresses only the stderr progress lines (per-file walk lines, "encoded N batches" lines). Warnings and errors still print to stderr, and `--quiet` does **not** change the shape of stdout.
- Failure shapes — both the stderr summary and the stdout JSON envelope under `--format json` — are specified in [errors-and-exit-codes](errors-and-exit-codes.md).

## Implications

- Adding a subcommand is a code change in `code_index.cli`. Flag changes within a subcommand are minor; argument removal is breaking.
- The CLI is the integration point for the doc-gen pipeline — see `docs-generation-pipeline.md`.

## Open questions

None pinned here. `code_index watch` and `code_index search --explain` were demoted to [roadmap](roadmap.md).
