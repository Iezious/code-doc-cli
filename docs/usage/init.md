# code_index init

Scaffold `docs/.helpers/config.toml` and `docs/.helpers/.gitignore` in the current project directory. Idempotent; refuses to overwrite an existing config without `--force`.

## Synopsis

```
code_index init [--name <project-name>] [--force]
                [--format text|json] [--config <path>]
```

## Flags

| Flag | Effect |
|---|---|
| `--name <string>` | Project display name. Default: current directory name. |
| `--force` | Overwrite existing files. Without it, `init` refuses if `config.toml` exists. |

## Behavior

- Writes `docs/.helpers/config.toml` with a minimal `[code_index]` skeleton (see `docs/architecture/config.md`).
- Writes `docs/.helpers/.gitignore` containing `index.sqlite*` so the index file is not committed.
- Refuses without `--force` when `config.toml` already exists; refuses no-op when nothing would be written.
- `force_used` distinguishes "actually overwrote a prior file" from "fresh init" or "no-op `--force`".

## Success JSON

```json
{
  "config_path": "/abs/path/docs/.helpers/config.toml",
  "gitignore_path": "/abs/path/docs/.helpers/.gitignore",
  "project": "my-project",
  "force_used": false
}
```

Paths are absolute, forward-slashed. `force_used` is `true` iff `--force` was passed AND a prior `config.toml` was overwritten; `false` for fresh init or no-op `--force`.

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| `config.toml` already exists, `--force` not passed | 1 | `cli.not_implemented` |

## Next step

After successful `init`, run `code_index index build` to populate the index. Edit `docs/.helpers/config.toml` first if you need non-default `roots`, `embed_model`, or `languages`.
