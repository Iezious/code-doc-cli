# code_index index sync

Incremental update of the existing index. Compares each project file's mtime and size against the `files` table; re-embeds only files that changed.

## Synopsis

```
code_index index sync [--verbose]
                      [--format text|json] [--config <path>]
```

## Behavior

- Walks the project using the same ignore rules as `index build`.
- Joins the walked file set against the `files` table:
  - **Match** (path present, mtime + size unchanged) — no work.
  - **Differs** (mtime or size differs) — delete the file's rows from `chunks`, `chunks_fts`, `embeddings`, `symbols`, `edges`; re-chunk, re-embed, re-insert; update the `files` row.
  - **New** (path absent from `files`) — chunk, embed, insert; add a `files` row.
  - **Vanished** (path in `files` but not on disk) — delete the file's rows from all five tables and remove the `files` row.
- Does not depend on git. Untracked, staged, and committed edits are handled uniformly.
- Verifies index compat (`embed_model`, `embed_dim`) before any read; a sync against a mismatched index refuses with code 11, not implicit rebuild.

## Success JSON

```json
{
  "files_added": 0,
  "files_changed": 0,
  "files_unchanged": 0,
  "files_removed": 0,
  "chunks_inserted_total": 0,
  "seconds_elapsed": 0.0
}
```

`chunks_inserted_total` covers chunks from both `files_added` and `files_changed` (the latter are re-inserted after their old rows are deleted).

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| No index file | 12 | `index.missing` |
| Schema version mismatch | 10 | `index.schema_mismatch` |
| Stored `embed_model` differs from config | 11 | `index.embed_model_mismatch` |
| Stored `embed_dim` differs from backend | 11 | `index.embed_dim_mismatch` |
| Embedding encode raised | 20 | `backend.encode_failed` |
| Plugin raised (under `--strict`, if added) | 30 | `parsing.plugin_error` |

## Recovery

- `index.embed_model_mismatch` or `index.embed_dim_mismatch` — run `code_index index rebuild --yes`. Sync cannot recover; the stored vectors are tied to the old model.
- `index.schema_mismatch` — the engine was upgraded; run `code_index index rebuild --yes`.
