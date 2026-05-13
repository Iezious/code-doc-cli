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

### `codedoc graph`

Lightweight dep / call queries over the edges table.

```
codedoc graph callers <symbol>        # who points at this
codedoc graph deps <path>             # what this file/chunk depends on
                   [--depth <int>]    # transitive, default 1
                   [--lang <name>]
                   [--format text|json]
```

### `codedoc config show`

Prints the resolved configuration (config file values merged with defaults) and the index metadata (schema version, embed model, last commit). Useful for "is my index up to date with my config?" checks.

```
codedoc config show [--format text|json]
```

### `codedoc doctor`

Diagnoses common problems: missing extension, schema mismatch, model mismatch, stale index, missing API key for the configured backend.

```
codedoc doctor
```

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

## Implications

- Adding a subcommand is a code change in `codedoc.cli`. Flag changes within a subcommand are minor; argument removal is breaking.
- The CLI is the integration point for the doc-gen pipeline — see `docs-generation-pipeline.md`.

## Open questions

- Whether to add a `codedoc watch` daemon mode for live indices. Plausible v1.x; not MVP.
- Whether `codedoc search --explain` should dump the per-source contributions for diagnostics. Likely yes; cheap.
