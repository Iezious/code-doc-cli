# Retrieval

## Decision

Retrieval is **hybrid**: every search query runs an FTS5 BM25 query and a `sqlite-vec` cosine query in parallel, then fuses them with **Reciprocal Rank Fusion (RRF)** to produce the final ranked list. The same hybrid pipeline serves both `codedoc search` (for humans and agents) and any internal lookup the planner-explorer pipeline issues.

## Rationale

- **Dense alone is weak on identifiers.** Symbol names like `llListenRemove`, `IEnumerable`, `useEffect` rarely cluster well in vector space; BM25 nails them.
- **BM25 alone is weak on concepts.** Queries like "where do we handle dropped sessions" rarely match the exact wording in code; dense recovers it.
- **RRF is robust without tuning.** It needs no calibration of score scales between the two systems — it just fuses ranks. The default `k = 60` is the published value from the original paper and works well in practice.

## Rejected alternatives

- **Pure dense retrieval.** Loses on symbol queries and on small/niche-language corpora (LSL especially).
- **Pure BM25.** Loses on conceptual queries; cannot bridge synonyms or paraphrases.
- **Score-normalized linear blending.** Requires scale calibration and re-tuning when the embedding model changes. RRF is simpler and more stable.
- **Learned-to-rank reranker.** Out of scope — adds a model dependency and training requirement.

## Fusion details

For each result list (BM25 and dense), each item gets a contribution:

```
contribution(item) = 1 / (k + rank(item))      with k = 60
```

Items appearing in both lists have their contributions summed. Final ranking is by total contribution, descending. Ties broken by rank in the dense list (semantic preferred for equal contribution).

## Query shape

```
codedoc search "<query>" [--lang fsharp|csharp|js|ts|go|python|lsl]
                         [--k <int>]              # final top-N
                         [--project <name>]
                         [--kind function|type|...]
                         [--path <glob>]
```

Filters are applied to both BM25 and dense queries before fusion, not after. This keeps the candidate pools consistent.

## Output

Each result row carries:

- `path`, `start_line`, `end_line`
- `language`, `kind`, `name`, `scope`
- A short excerpt of `content` (configurable length, default ~30 lines)
- The fused RRF score (for diagnostics)

The default rendering is one result per stanza, prefixed by `path:start-end`, suitable for either human reading or LLM context.

## Candidate pool sizes

- BM25 retrieves up to `--bm25-k` (default 100) before fusion.
- Dense retrieves up to `--dense-k` (default 100) before fusion.
- After fusion, top `--k` (default 20) are returned.

Larger pools improve recall at the cost of query latency. Defaults are tuned for "fast enough that an agent calls this many times per pipeline run."

## Latency budget

- Cold queries (first after process start): dominated by SQLite open + extension load. Targets sub-second.
- Warm queries: targets <100ms for a 50k-chunk index on commodity hardware.
- Embedding the query string is one `encode` call; the embedding backend's per-call latency is the floor.

## Implications

- BM25 indexing is automatic (FTS5 trigger from `chunks_fts`), no extra step at index time.
- Symbol-heavy queries (lots of identifier text) benefit most. Long natural-language queries benefit more from the dense side.
- Hybrid means agents can write either kind of query and not have to think about which retrieval mode to invoke.

## Open questions

- Whether to expose `--mode bm25|dense|hybrid` for diagnostics. Likely yes; cheap to add.
- Whether RRF `k` should be tunable in config. Probably leave at 60 unless a corpus shows clear evidence to change.
- Whether to add a coarse rerank step (e.g., BM25 over the fused top 50) for niche-language queries. Deferred; revisit if LSL retrieval is weak.
