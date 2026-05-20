# Config schema

## Decision

Per-project configuration is a single TOML file at `docs/.helpers/config.toml`, committed to the project's git history. All keys live under one `[code_index]` table. There is no other configuration surface (no environment-variable overrides for behavior, no per-subcommand config files); only `--config <path>` can redirect the loader to a different file.

This doc owns the schema. Loader internals belong in the implementation; rationale for the file location and version pinning belongs in [tool-and-data-split](tool-and-data-split.md); rationale for backend choices belongs in [embeddings](embeddings.md); the consumer of `config show` is documented in [cli](cli.md).

## Rationale

- **One table, one place.** Scattering config across multiple files or sections invites drift. `[code_index]` is flat enough to scan and structured enough that future sections (`[code_index.languages.fsharp]`, etc.) can be added without breaking existing keys.
- **TOML, not JSON or YAML.** TOML round-trips comments cleanly, has a single dialect, and is the default for `pyproject.toml` — the project already lives in that ecosystem.
- **Committed.** Teammates checking out the repo get the indexing parameters for free; index reproducibility requires the same config.

## Rejected alternatives

- **JSON.** No comments. Painful for a file humans hand-edit.
- **YAML.** Multiple dialects, indentation-sensitive, surprising type coercions.
- **`pyproject.toml` `[tool.code_index]` section.** Couples the index config to the *consuming* project's Python packaging, which is wrong for polyglot projects that may not have a `pyproject.toml` at all.
- **Environment-variable overrides for behavior keys.** Hidden state that breaks reproducibility. Env vars are reserved for *secrets* (e.g. backend credentials), not behavior.

## Schema

All keys are under `[code_index]`. Types are TOML types; "list of X" means a TOML array of values of type X.

| Key | Type | Required | Default | Description |
|---|---|---|---|---|
| `version` | string | yes | — | Engine version pin range, PEP 440 specifier syntax. Example: `">=0.3,<0.5"`. |
| `project` | string | no | parent directory name of `docs/.helpers/` | Display name shown in `config show` and surfaced to retrieval result rows. |
| `roots` | list of relative path strings | no | `["."]` | Directories the indexer walks, resolved relative to the project root (the directory containing `docs/.helpers/`). |
| `ignores` | list of glob strings | no | `[]` | Extra ignore patterns, merged with `.gitignore` and the engine's built-in default excludes. |
| `languages` | list of language name strings | no | all seven built-ins | Active language plugins by name (`"fsharp"`, `"csharp"`, `"javascript"`, `"typescript"`, `"go"`, `"python"`, `"lsl"`). A subset disables unlisted built-ins. |
| `extra_languages` | list of relative path strings | no | `[]` | Paths to Python module files providing additional language plugins. Loaded as ordinary Python modules into the plugin registry. |
| `embed_backend` | enum string: `Literal["fastembed"]` | no | `"fastembed"` | Which embedding backend to use. `Literal` framing is kept for forward extensibility; additional backends are roadmap items (see [embeddings](embeddings.md)). |
| `embed_model` | string | no | `"jinaai/jina-embeddings-v2-base-code"` when `embed_backend = "fastembed"` | Model identifier. Backend-specific; the loader picks the right default from the active backend. |
| `embed_batch_size` | int | no | `32` | Batch size passed to the backend's `encode` call. Tunable per project. |

### Example

```toml
[code_index]
version          = ">=0.3,<0.5"
project          = "utils.codedoc"
roots            = ["src", "tests"]
ignores          = ["**/snapshots/**"]
languages        = ["python", "typescript"]
extra_languages  = ["./.helpers/lang_mydsl.py"]
embed_backend    = "fastembed"
embed_model      = "jinaai/jina-embeddings-v2-base-code"
embed_batch_size = 32
```

## Validation rules

- `version` must parse as a PEP 440 specifier. The current engine version must satisfy it; otherwise loud failure (see [errors-and-exit-codes](errors-and-exit-codes.md), code `2`).
- `embed_backend` must be `"fastembed"` — the only value accepted in MVP. The check still produces `config.bad_enum` on any other value; the `Literal` framing leaves room for additional values in future versions without renumbering errors.
- `embed_model` must be compatible with the chosen backend (backend reports its accepted models; mismatch is loud failure).
- `roots` paths must exist and resolve under the project root.
- `extra_languages` paths must exist and be readable Python files.
- `languages` must be a subset of the names registered in the plugin registry (built-ins plus anything `extra_languages` adds).
- Unknown keys under `[code_index]` produce a warning, not a failure — forward-compatibility for older engines reading a config written for a newer one.

## What `init` writes

`code_index init` writes a minimal skeleton. Only the keys below are pinned in the generated file; everything else is left to its default and can be added on demand.

```toml
[code_index]
version       = ">=<current>,<<current-major+2>"   # pinned to the engine version that ran init
project       = "<directory-name>"
roots         = ["."]
embed_backend = "fastembed"
embed_model   = "jinaai/jina-embeddings-v2-base-code"
```

The intent is that the file is small enough to read on first open and obvious enough to extend.

## Cross-references

- File location and the rationale for committing it: [tool-and-data-split](tool-and-data-split.md).
- Engine version pin semantics across the tool/data split: [tool-and-data-split](tool-and-data-split.md).
- Backend choices and the rationale for the fastembed default: [embeddings](embeddings.md).
- `code_index config show` semantics (prints resolved config plus index meta): [cli](cli.md).
- Failure exit codes and `kind` strings for each validation rule: [errors-and-exit-codes](errors-and-exit-codes.md).

## Implications

- Changing `embed_backend` or `embed_model` requires `code_index index rebuild`; the engine refuses queries against an index whose `meta.embed_model` does not match config (see [storage](storage.md) and [errors-and-exit-codes](errors-and-exit-codes.md)).
- `extra_languages` is the supported extension point for project-specific DSLs. The engine stays free of per-project conditionals.
- Because unknown keys only warn, a project pinned to a newer engine can be opened by an older engine without exploding — but the older engine cannot honor the unknown keys, so behavior will differ. The `version` pin is the guard against that.

## Open questions

- **Per-plugin config sub-tables.** The schema rationale anticipates `[code_index.languages.<lang>]` future sections (see "One table, one place" in this doc), but no concrete schema exists. The Phase 3 LSL plugin defers OSSL recognition because it would need exactly such a sub-table (see [chunking-and-languages](chunking-and-languages.md), LSL section). Decide before Phase 4+ work depends on it, or before a Phase 3 OSSL bug forces the question. Two paths: (a) commit a concrete sub-table schema (key naming, nesting rules, validation, surfacing in `config show`), or (b) commit a "deferred to v1.x" stance and document that `extra_languages` is the only per-plugin extension point in MVP.
- Workspace-level config that defaults values across sibling projects is open in [tool-and-data-split](tool-and-data-split.md) and is cut from MVP (see [mvp-scope](mvp-scope.md)).
