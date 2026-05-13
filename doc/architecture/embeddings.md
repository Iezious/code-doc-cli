# Embeddings

## Decision

Embeddings are produced by a pluggable backend. The default is **`fastembed`** with the code-tuned **Jina embeddings v2 base code** model (768-dim, runs locally on CPU). **Voyage `code-3`** is supported as an opt-in alternative via the `voyage` install extra.

All backends conform to a single interface:

```
encode(texts: list[str]) -> ndarray of shape (N, D)
```

`D` is reported by the backend and must match the dimension stored in `meta.embed_dim`.

## Rationale

- **Local default.** No API key, offline-capable, free reindexing — important when running across multiple projects iteratively.
- **Code-tuned over general-purpose.** Jina v2 base code beats general models (OpenAI 3-small, BGE base) on code retrieval at comparable size. The retrieval quality gap to Voyage code-3 is real but narrows substantially under hybrid BM25 + dense fusion.
- **Backend interface is small.** Switching is one config line plus a rebuild. Lock-in to the engine API, not the model.

## Rejected alternatives

- **OpenAI `text-embedding-3-large`.** Decent, but general-purpose. Code-tuned models of similar tier (Voyage code-3 / Jina code-v2) outperform it on code-specific benchmarks. If we are going to pay for an API, Voyage is the better spend.
- **OpenAI `text-embedding-3-small` as default.** Weaker than Jina code-v2 on code, and not free. No reason to pick it.
- **Local sentence-transformers without fastembed.** Heavier dependency, slower startup, no ONNX quantization out of the box.
- **Running our own embedding service.** Out of scope.

## Backend interface

```python
class EmbeddingBackend(Protocol):
    name: str            # "fastembed:jina-code-v2", "voyage:code-3", ...
    dim: int             # vector dimension
    def encode(self, texts: list[str]) -> np.ndarray: ...
```

Backends are instantiated from config:

```toml
[codedoc]
embed_backend = "fastembed"           # or "voyage"
embed_model   = "jinaai/jina-embeddings-v2-base-code"
```

Voyage requires `VOYAGE_API_KEY` in the environment. Absence is detected at backend init, not deep in the indexer loop.

## Switching models

- Switching the model **changes the vector dimension** in general. The stored embeddings are tied to one model.
- The indexer refuses to insert vectors with a different dimension than the existing `embeddings` table.
- `codedoc index rebuild` is the supported migration path: drops embeddings, re-embeds with the new model. Other tables are preserved where dimension is irrelevant.
- A future enhancement is a "re-embed only" subcommand that keeps chunk rows and just rewrites the vec table. Not part of the MVP.

## Batching and throughput

- Texts are batched (typical batch size 32–64) before each `encode` call. Tunable in config.
- The indexer measures and reports chunks/second for visibility.
- fastembed runs on CPU by default. GPU paths (CUDA, DirectML) are not in scope but not blocked by the interface.

## Caching

- A content-hash column on `chunks` enables an embedding cache: if a chunk with identical text already has an embedding, skip the re-embed.
- Cache invalidation is automatic when the model changes (different `meta.embed_model` value).

## Implications

- The default install is fully offline after the first model download (~120MB cached under user home).
- Adding Voyage support is a `uv tool install --editable ".[voyage]"` opt-in.
- Embedding quality is **one axis** of retrieval quality; the other is BM25. See `retrieval.md` for how the two are fused.

## Open questions

- Whether to ship a small benchmark harness so a user can compare backends on their own corpus. Useful but not MVP.
- Whether to support an "ensemble" of two embedding models (rare; usually not worth the complexity). Rejected by default.
