# code_index index build

Full build of the SQLite index. Walks the configured roots, chunks each file via its language plugin, embeds, and stores into `docs/.helpers/index.sqlite`.

## Synopsis

```
code_index index build [--root <path>] [--dry-run] [--strict]
                       [--verbose]
                       [--format text|json] [--config <path>]
```

## Flags

| Flag | Effect |
|---|---|
| `--root <path>` | Override config `roots`. May repeat to add multiple roots. |
| `--dry-run` | Walk and chunk but do not embed or store. Useful for validating coverage. |
| `--strict` | Raise on plugin errors and oversize files instead of skipping with a warning. |

## Behavior

- Reads config, walks roots applying `.gitignore` + built-in excludes (`node_modules/`, `__pycache__/`, `dist/`, `.venv/`, etc.) + `[code_index] ignores`.
- Dispatches each file to its language plugin; collects `Chunk`, `Symbol`, `Edge` lists.
- Files above 1 MiB are skipped with a stderr warning by default; `--strict` raises `io.oversize`.
- Binary files (unknown extension OR first 8 KiB contain a NUL) are skipped silently.
- Batches chunk text to the embedding backend (`embed_batch_size`, default 32).
- Inserts into `chunks`, `chunks_fts` (BM25), `embeddings` (vec0), `symbols`, `edges`, `files`; writes `meta` (`schema_version`, `code_index_version`, `embed_model`, `embed_dim`).
- On a populated index: drops existing data and rebuilds (same effect as `index rebuild --yes`).

The embedding model is downloaded on first run and cached under the user home directory (~120 MB for `jinaai/jina-embeddings-v2-base-code`).

## Success JSON

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

`files_walked` includes skipped files (binary, oversize); `files_chunked` is the subset that produced chunks.

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| No `docs/.helpers/config.toml` discovered | 12 | `index.missing` |
| Malformed config TOML | 2 | `config.parse_error` |
| Required key missing | 2 | `config.missing_key` |
| `embed_backend` not in allowed enum | 2 | `config.bad_enum` |
| Config `version` pin unsatisfied | 2 | `config.version_mismatch` |
| `roots` path missing | 2 | `config.bad_path` |
| `sqlite-vec` extension missing | 10 | `index.vec_extension_unavailable` |
| FTS5 unavailable in linked SQLite | 10 | `index.fts5_unavailable` |
| Embedding model download / load failed | 20 | `backend.model_download_failed` |
| Encode call raised | 20 | `backend.encode_failed` |
| Plugin raised (under `--strict`) | 30 | `parsing.plugin_error` |
| File exceeds size cap (under `--strict`) | 41 | `io.oversize` |

## Notes

- Re-running `index build` on a populated index forces a full rebuild. Prefer `index sync` for incremental updates.
- The walker does not follow directory symlinks (loops are not possible); it does follow file symlinks.
- Files are decoded as UTF-8; on `UnicodeDecodeError` the walker retries with `errors="replace"` and warns.
