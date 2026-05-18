# CLI surface

## Decision

`codedoc` is a single `typer`-based CLI binary with a small, stable subcommand surface. Every operation an agent or human needs is reachable from one command tree. The CLI is the only supported entry point — there is no Python API contract for external consumers.

## Rationale

- Subagents invoke the tool via Bash. Stable, narrow flags beat a sprawling Python import surface.
- A single binary keeps install simple (`uv tool install ...`) and discovery obvious (`codedoc --help`).
- `typer` gives consistent help, completion, and argument validation across subcommands without ceremony.

## Subcommands

### `codedoc init`

Initializes `docs/.helpers/` in the current project, writing a default `config.toml` and a `.gitignore` for the index file. Idempotent — refuses to overwrite an existing config without `--force`.

```
codedoc init [--name <project-name>] [--force]
```

### `codedoc index build`

Full index build. Walks roots from config, chunks, embeds, stores. Reports counts and timings.

```
codedoc index build [--root <path>]   # override config roots
                    [--dry-run]        # walk and chunk but do not embed/store
                    [--verbose]
```

### `codedoc index sync`

Incremental update. Uses `git diff` against `meta.last_commit` when available, falling back to mtime/hash comparison.

```
codedoc index sync [--since <ref>]    # explicit base
                   [--verbose]
```

### `codedoc index rebuild`

Drops and rebuilds. Required after embedding model changes.

```
codedoc index rebuild [--yes]
```

### `codedoc search`

Hybrid BM25 + dense retrieval. See `retrieval.md`.

```
codedoc search "<query>" [--lang <name>]
                         [--k <int>]           # final top-N, default 20
                         [--bm25-k <int>]      # BM25 pool, default 100
                         [--dense-k <int>]     # dense pool, default 100
                         [--kind <kind>]
                         [--path <glob>]
                         [--mode bm25|dense|hybrid]   # default hybrid
                         [--format text|json]
```

`--format json` returns a stable JSON array, suitable for agent consumption.

### `codedoc symbols`

Symbol lookup over the stored symbols table.

```
codedoc symbols defs <name>           # definitions matching name (substring by default, --exact for exact)
codedoc symbols refs <name>           # references
                     [--lang <name>]
                     [--format text|json]
```

Matching is **substring on `name` by default, case-sensitive**. `--exact` switches to exact-match. `--lang <name>` narrows to one language's symbols. Results include the `scope` field for disambiguation; agents that need a fully-qualified handle can concatenate `lang:scope:name`. The `name` strings themselves are plugin-emitted and not normalized by the engine — see [chunking-and-languages](chunking-and-languages.md), "Symbol identity", for the per-language conventions.

### `codedoc graph`

Lightweight dep / call queries over the edges table.

```
codedoc graph callers <symbol>        # who points at this
codedoc graph deps <path>             # what this file/chunk depends on
                   [--lang <name>]
                   [--format text|json]
```

Graph subcommands accept the same `--lang` filter as `symbols`, and the `<symbol>` argument to `graph callers` follows the same substring-by-default, `--exact`-for-exact, case-sensitive rule (see [chunking-and-languages](chunking-and-languages.md), "Symbol identity").

### `codedoc config show`

Prints the resolved configuration (config file values merged with defaults) and the index metadata (schema version, embed model, last commit). Useful for "is my index up to date with my config?" checks.

```
codedoc config show [--format text|json]
```

### `codedoc doctor`

Intended to diagnose common problems in one place: missing extension, schema mismatch, model mismatch, stale index, missing API key for the configured backend.

**Deferred to v1.1** (see [mvp-scope](mvp-scope.md)). Until it ships, each subcommand emits the relevant failure inline using the codes and `kind` strings defined in [errors-and-exit-codes](errors-and-exit-codes.md).

## Cross-cutting behaviors

- All subcommands accept `--config <path>` to override the discovered config file.
- All subcommands return non-zero exit codes on real errors. `search` returning zero results is **not** an error.
- `--format json` is supported wherever results are structured. The JSON shape is part of the contract and changes only with a CLI major version.

## Discovery and config location

- The CLI walks upward from the CWD looking for `docs/.helpers/config.toml`.
- Found → all commands operate against that project.
- Not found → most commands error with a pointer to `codedoc init`. Some (`--help`, `config show --no-project`) work without a config.

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

- Adding a subcommand is a code change in `code_doc_cli.cli`. Flag changes within a subcommand are minor; argument removal is breaking.
- The CLI is the integration point for the doc-gen pipeline — see `docs-generation-pipeline.md`.

## Open questions

None pinned here. `codedoc watch` and `codedoc search --explain` were demoted to [roadmap](roadmap.md).
