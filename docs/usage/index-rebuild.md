# code_index index rebuild

Drop and rebuild the index from scratch. Required when the embedding model changes; also used after engine upgrades that bump the schema.

## Synopsis

```
code_index index rebuild --yes
                         [--verbose]
                         [--format text|json] [--config <path>]
```

`--root` and `--dry-run` are intentionally not accepted on `rebuild`.

## Flags

| Flag | Effect |
|---|---|
| `--yes` | Confirms the destructive operation. Required; without it the command refuses. |

## Behavior

- Drops all rows from `chunks`, `chunks_fts`, `embeddings`, `symbols`, `edges`, `files`.
- Re-walks the configured roots, re-chunks, re-embeds, re-inserts.
- Writes `meta` with the current `embed_model`, `embed_dim`, `schema_version`, `code_index_version`.

Use this after:

- Changing `embed_model` or `embed_backend` in `config.toml`.
- Upgrading `code_index` itself when the schema bumps (signaled by `index.schema_mismatch` on the next read).

For routine post-edit updates, prefer `code_index index sync`.

## Success JSON

Same shape as `index build`:

```json
{
  "files_walked": 0,
  "files_chunked": 0,
  "chunks_inserted": 0,
  "symbols_inserted": 0,
  "edges_inserted": 0,
  "seconds_elapsed": 0.0
}
```

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| `--yes` not passed | 1 | `usage.confirmation_required` |
| No config discovered | 12 | `index.missing` |
| Malformed config | 2 | `config.parse_error` |
| Backend init / model download failed | 20 | `backend.model_download_failed` |
| Encode raised | 20 | `backend.encode_failed` |
| `sqlite-vec` extension missing | 10 | `index.vec_extension_unavailable` |
| FTS5 unavailable | 10 | `index.fts5_unavailable` |
