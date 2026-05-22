# code_index graph

Lightweight dependency / call queries over the `edges` table. Two subcommands: `callers` (who points at this symbol) and `deps` (what this file/chunk depends on).

## Synopsis

```
code_index graph callers <symbol> [--exact] [--lang <name>]
                                  [--format text|json] [--config <path>]
code_index graph deps <path>      [--lang <name>]
                                  [--format text|json] [--config <path>]
```

## Flags

| Flag | Applies to | Effect |
|---|---|---|
| `--exact` | `callers` | Exact match on the target symbol. Default substring, case-sensitive. |
| `--lang <name>` | both | Restrict to one language's edges. |

## Behavior

- `graph callers <symbol>` matches by symbol `name` (same substring-default / `--exact` semantics as `symbols`). Returns edges whose `dst_name` joins to a symbol matching `<symbol>`.
- `graph deps <path>` matches `<path>` **exactly** against the project-root-relative `chunks.path` (forward slashes). No globbing, no substring. Use the same path string format `search` results expose.
- Edges are resolved lazily at query time by joining `edges.dst_name` against `symbols.name`. Consequences:
  - Renames are handled correctly without rewriting edges.
  - Dangling targets return no callers (deletion-tolerant).
  - Cross-file and cross-language edges need no special handling.
- Edge `kind` is plugin-defined: `import`, `call`, `listen`, `link_message`, `http`, `email`, etc.
- Zero matches is success (exit 0) with `[]`.

## Success JSON

### `graph callers`

```json
[
  {
    "path": "<string>",
    "scope": "<string or null>",
    "language": "<string>",
    "start_line": 0,
    "kind": "<edge kind>",
    "dst_name": "<the symbol being called>"
  }
]
```

Each row is one call site (one edge). `path` + `start_line` locate the calling chunk.

### `graph deps`

```json
[
  {
    "path": "<string>",
    "kind": "<edge kind>",
    "dst_name": "<target>",
    "meta": null
  }
]
```

`meta` is either `null` or a JSON-encoded string emitted by the plugin. **Do not blindly `json.loads(meta)`** — contents are plugin-specific and may not be valid JSON in all kinds. Treat it as an opaque blob unless you recognize the edge `kind` and know its `meta` contract.

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| No index | 12 | `index.missing` |
| Schema mismatch | 10 | `index.schema_mismatch` |
| Embedding model mismatch | 11 | `index.embed_model_mismatch` |

## Examples

```bash
code_index graph callers FastembedBackend --exact --format json
code_index graph callers listen --lang lsl --exact --format json
code_index graph deps "src/code_index/cli.py" --format json
```
