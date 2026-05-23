# code_index config show

Print resolved config (config-file values merged with defaults) and index metadata. **Diagnostic — never gates on drift.**

## Synopsis

```
code_index config show [--format text|json] [--config <path>]
```

## Behavior

`config show` is the only subcommand that does **not** refuse on a schema, model, or dim mismatch. Mismatches are reported (the configured value appears under `config.embed_model`, the stored value under `index.embed_model`, etc.) and the exit code stays 0. Use this to diagnose drift; use `code_index index rebuild --yes` to resolve it.

Opens the index file in diagnostic mode (`check_version=False`, `create_if_missing=False`). If the file is absent, `"index"` is `null`. The only failures `config show` raises are:

- Config discovery failure — no `docs/.helpers/config.toml` found.
- Config load failure — malformed TOML, version-pin unsatisfied, etc.
- Index file present but unparseable as SQLite (genuine corruption, not drift).

All other drift conditions (schema mismatch, model mismatch, dim mismatch, missing index file) exit 0 with diagnostic data on stdout.

## Success JSON

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

When the index file is absent, the top-level shape is `{"config": {...}, "index": null}`. Values inside `"index"` are strings (matching SQLite TEXT storage); do not coerce numerically.

## Detecting drift

To check whether queries will refuse:

- `config.embed_model != index.embed_model` — queries will fail with `index.embed_model_mismatch` (code 11).
- `config.embed_backend` change without rebuild — same.
- `index.schema_version` differs from the running engine's expected version — queries will fail with `index.schema_mismatch` (code 10).

In all three cases, the fix is `code_index index rebuild --yes`.

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| No `docs/.helpers/config.toml` discovered | 12 | `index.missing` |
| Malformed config TOML | 2 | `config.parse_error` |
| Config `version` pin unsatisfied | 2 | `config.version_mismatch` |
| Required key missing in config | 2 | `config.missing_key` |
| Index file present but not a valid SQLite database | 10 | `index.unreadable` |

Schema mismatch, model mismatch, dim mismatch, and a missing index file (when the config is present and valid) all exit 0 with diagnostic data — they are not failures of `config show`.
