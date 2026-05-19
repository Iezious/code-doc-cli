# Embeddings

## Decision

Embeddings are produced by a pluggable backend. The MVP ships **`fastembed`** with the code-tuned **Jina embeddings v2 base code** model (768-dim, runs locally on CPU) as the sole implementation.

All backends conform to a single interface:

```
encode(texts: list[str]) -> ndarray of shape (N, D)
```

`D` is reported by the backend and must match the dimension stored in `meta.embed_dim`.

## Rationale

- **Local.** No API key, offline-capable, free reindexing — important when running across multiple projects iteratively.
- **Code-tuned over general-purpose.** Jina v2 base code beats general models (OpenAI 3-small, BGE base) on code retrieval at comparable size.
- **Deterministic and free.** A single-user, single-project tool has no justification for per-call billing or network egress on the hot indexing path.
- **Backend interface is small.** The Protocol is preserved so additional backends can be added later without re-architecting the indexer or search path. Lock-in is to the engine API, not the model.

## Rejected alternatives

- **OpenAI `text-embedding-3-large`.** Decent, but general-purpose; code-tuned models of similar tier outperform it on code-specific benchmarks.
- **OpenAI `text-embedding-3-small` as default.** Weaker than Jina code-v2 on code, and not free.
- **Local sentence-transformers without fastembed.** Heavier dependency, slower startup, no ONNX quantization out of the box.
- **Running our own embedding service.** Out of scope.
- **Ensemble of two embedding models.** Rare; usually not worth the complexity. Rejected by default.

## Backend interface

```python
class EmbeddingBackend(Protocol):
    name: str            # e.g. "fastembed:jina-code-v2"
    dim: int             # vector dimension
    def encode(self, texts: list[str]) -> np.ndarray: ...
```

The MVP ships one implementation of this Protocol (`fastembed`). The Protocol is the documented extension point — additional backends are roadmap items, tracked under `## Embedding ecosystem` in [roadmap](roadmap.md).

Backends are instantiated from config:

```toml
[code_index]
embed_backend = "fastembed"
embed_model   = "jinaai/jina-embeddings-v2-base-code"
```

## Switching models

- Switching the model **changes the vector dimension** in general. The stored embeddings are tied to one model.
- The indexer refuses to insert vectors with a different dimension than the existing `embeddings` table.
- `code_index index rebuild` is the supported migration path: drops embeddings, re-embeds with the new model. Other tables are preserved where dimension is irrelevant.
- A future enhancement is a "re-embed only" subcommand that keeps chunk rows and just rewrites the vec table. Not part of the MVP.

## Batching and throughput

- Texts are batched (default 32 per `embed_batch_size` in [config](config.md), tunable per project) before each `encode` call.
- The indexer measures and reports chunks/second for visibility.
- fastembed runs on CPU by default. GPU paths (CUDA, DirectML) are not in scope but not blocked by the interface.

## Caching

An embedding cache keyed by chunk content hash is **planned for v1.1 and not in MVP** (see [mvp-scope](mvp-scope.md), [storage](storage.md)). When it lands, a `chunks.content_hash` column will let the indexer skip re-embedding any chunk whose text matches an already-embedded one, and cache entries will be implicitly invalidated when `meta.embed_model` changes. The column and the cache logic land together via a schema bump rather than as a dormant column in MVP.

## Implications

- The MVP install is fully offline after the first model download (~120MB cached under user home).
- Embedding quality is **one axis** of retrieval quality; the other is BM25. See `retrieval.md` for how the two are fused.

## Open questions

None pinned here. A benchmark harness for comparing backends was demoted to [roadmap](roadmap.md); the ensemble option is now recorded under "Rejected alternatives" above.
