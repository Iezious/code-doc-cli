# code_index search

Hybrid BM25 + dense retrieval over indexed chunks. Returns ranked chunks with file path, line range, and excerpt.

## Synopsis

```
code_index search "<query>" [--lang <name>] [--k <int>]
                            [--bm25-k <int>] [--dense-k <int>]
                            [--kind <kind>] [--path <glob>]
                            [--mode bm25|dense|hybrid]
                            [--format text|json] [--config <path>]
```

## Flags

| Flag | Default | Effect |
|---|---|---|
| `--k` | 20 | Final top-N after fusion. |
| `--bm25-k` | 100 | BM25 candidate pool size before fusion. |
| `--dense-k` | 100 | Dense candidate pool size before fusion. |
| `--lang` | — | Restrict to one language (`fsharp`, `csharp`, `javascript`, `typescript`, `go`, `python`, `lsl`). |
| `--kind` | — | Restrict to chunk kind (`function`, `type`, `module`, `class`, `state`, `event`, ...). |
| `--path` | — | Glob filter on chunk path. |
| `--mode` | `hybrid` | `bm25`, `dense`, or `hybrid` (Reciprocal Rank Fusion). |

Filters apply to both pools before fusion, not after — candidate pools stay consistent.

## Behavior

- Embeds the query once via the configured backend (one `encode` call).
- Runs BM25 (FTS5 over `chunks_fts`) and dense (`vec0` cosine over `embeddings`) in parallel.
- Fuses with Reciprocal Rank Fusion, `k = 60` (fixed, not exposed in config).
- Returns top-`k` after fusion. Zero results is success (exit 0) with `{"results": []}`.

**Mode caveat:** dense always returns its top-`dense-k` nearest neighbors regardless of cosine similarity (no relevance floor). Under `--mode hybrid` or `--mode dense`, "zero results" is only reachable if the embed call fails entirely; otherwise expect a non-empty list. For "nothing relevant" semantics, use `--mode bm25` — FTS5 returns zero rows for out-of-corpus tokens.

## Success JSON

```json
{
  "results": [
    {
      "path": "<string>",
      "start_line": 0,
      "end_line": 0,
      "language": "<string>",
      "kind": "<string>",
      "name": "<string or null>",
      "scope": "<string or null>",
      "excerpt": "<string>",
      "score": 0.0
    }
  ]
}
```

`name` and `scope` may be `null` (e.g. anonymous arrow functions, module-body chunks). `score` is the fused RRF score; useful for diagnostics, not absolute comparison across queries.

## Failure modes

| Condition | Code | Kind |
|---|---|---|
| `--mode` not in `bm25\|dense\|hybrid` | 1 | `cli.bad_enum` (detail.expected lists allowed values) |
| No index | 12 | `index.missing` |
| Schema mismatch | 10 | `index.schema_mismatch` |
| Embedding model mismatch | 11 | `index.embed_model_mismatch` |
| Encode raised | 20 | `backend.encode_failed` |

## Examples

```bash
code_index search "where do we handle dropped sessions" --format json
code_index search "llListenRemove" --lang lsl --mode bm25 --format json
code_index search "rate limit" --kind function --path "src/**" --k 10 --format json
```
