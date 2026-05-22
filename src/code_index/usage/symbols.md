# code_index symbols

Symbol lookup over the stored `symbols` table. Two subcommands: `defs` (definitions) and `refs` (references).

## Synopsis

```
code_index symbols defs <name> [--exact] [--lang <name>]
                               [--format text|json] [--config <path>]
code_index symbols refs <name> [--exact] [--lang <name>]
                               [--format text|json] [--config <path>]
```

## Flags

| Flag | Effect |
|---|---|
| `--exact` | Exact match on `name`. Default is substring, case-sensitive. |
| `--lang <name>` | Restrict to one language's symbols. |

## Behavior

- Pure read against the `symbols` table; no embedding involved, much faster than `search`.
- Matching is case-sensitive (every MVP language is itself case-sensitive).
- Plugin-emitted `name` strings are **not** engine-normalized. Per-language conventions:
  - **F#**: `Module.SubModule.Member`; DU cases as `Module.TypeName.CaseName`.
  - **C#**: `Namespace.Type.Member`.
  - **Go**: `package.Name` for top-level; `package.Receiver.Method` for methods.
  - **JS**: export name as written; default exports as `default::<filename-without-extension>`.
  - **TS**: same as JS, plus type-only exports.
  - **Python**: intra-file dotted form: `Class.method`, `Class.outer.inner`, `Class`, or bare for module-level. **No package-derived prefix.**
  - **LSL**: event handlers as `<state>.<event>`; user functions and globals by bare name.
- Zero matches is success (exit 0) with `[]`.

Full per-language detail in `../../../docs/architecture/chunking-and-languages.md`.

## Success JSON

```json
[
  {
    "path": "<string>",
    "scope": "<string or null>",
    "language": "<string>",
    "name": "<string>",
    "line": 0
  }
]
```

Top-level is a list (not an object). `scope` carries enclosing-context disambiguation (module path, class, state name).

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| No index | 12 | `index.missing` |
| Schema mismatch | 10 | `index.schema_mismatch` |
| Embedding model mismatch (compat check) | 11 | `index.embed_model_mismatch` |

## Disambiguation

Same `name` may exist in multiple languages (e.g. `init`). Two strategies:

1. Filter with `--lang <name>`.
2. Inspect `scope` to distinguish (`Module.Foo` vs `state_running.foo`).

For a fully-qualified handle across the index, combine `language` + `scope` + `name`.

## Examples

```bash
code_index symbols defs FastembedBackend --exact --format json
code_index symbols refs llListenRemove --lang lsl --format json
code_index symbols defs build --lang python --format json
```
