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

The Phase 2 implementation is exposed as `code_index.embeddings.FastembedBackend`; consumers (the indexer, `config show`'s Phase 7 extension) instantiate backends via the single factory entry point `code_index.embeddings.from_config(config)` rather than constructing implementation classes directly.

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

- Texts are batched (default 16 per `embed_batch_size` in [config](config.md), tunable per project) before each `encode` call. The default was 32 in earlier versions; lowered to 16 after real-world polyglot codebases triggered an ONNX attention-buffer OOM when a long chunk was batched alongside others (a batch of 32 at the model's 8192-token capacity demands ~100 GB of attention buffer). Batch size combined with the per-text token cap (next bullet) bounds the per-encode memory footprint.
- **Per-text token cap.** Each text passed to `encode` is truncated to 1024 tokens at the backend's tokenizer (with an 8192-character defense-in-depth cap applied before the tokenizer ever sees the text). Chunks longer than ~1024 tokens are silently truncated by the backend; chunkers should target chunks well under that limit (see [chunking-and-languages](chunking-and-languages.md), "Chunk sizing guidance"). The cap is a backend-level safety net against ONNX padded-attention blowup; it is not exposed as a config knob.
- The indexer measures and reports chunks/second for visibility.
- fastembed runs on CPU by default. CUDA GPU acceleration is now a supported path, selected by the `CODE_INDEX_DEVICE` env var (see "Update 2026-05-28: GPU acceleration" below). DirectML remains rejected.

## Caching

An embedding cache keyed by chunk content hash is **planned for v1.1 and not in MVP** (see [mvp-scope](mvp-scope.md), [storage](storage.md)). When it lands, a `chunks.content_hash` column will let the indexer skip re-embedding any chunk whose text matches an already-embedded one, and cache entries will be implicitly invalidated when `meta.embed_model` changes. The column and the cache logic land together via a schema bump rather than as a dormant column in MVP.

## Implications

- The MVP install is fully offline after the first model download (~120MB cached under user home).
- Embedding quality is **one axis** of retrieval quality; the other is BM25. See `retrieval.md` for how the two are fused.
- Backend `__init__` and `encode` failures surface as `CodeIndexError` carrying `backend.model_download_failed` (code 20) and `backend.encode_failed` (code 20) respectively. Agents should distinguish by `kind` since both share code 20. See [errors-and-exit-codes](errors-and-exit-codes.md).

## Open questions

None pinned here. A benchmark harness for comparing backends was demoted to [roadmap](roadmap.md); the ensemble option is now recorded under "Rejected alternatives" above.

### Update 2026-05-28: GPU acceleration

GPU acceleration of embedding is promoted from out-of-scope to a supported path, via a local CUDA GPU. Stage one is fastembed + CUDA only.

**Device selection via env var.** A new env var `CODE_INDEX_DEVICE` selects where the model runs. Values and semantics:

- `auto` (default): use CUDA if the ONNX runtime offers `CUDAExecutionProvider`, else CPU. Silent — no warning.
- `cuda`: explicit request. If the CUDA provider is unavailable at runtime (no GPU/driver, or a CPU-only onnxruntime build is installed), warn on stderr and fall back to CPU.
- `cpu`: force CPU even on a GPU box.

Device is machine-local and is not a TOML key — see [config](config.md) for the env-var-vs-TOML policy and the reasoning (committed config must stay portable across teammates).

**Device is not index identity.** `backend.name` (e.g. `"fastembed:jina-code-v2"`) carries the model, not the device. fastembed-CPU and fastembed-CUDA produce the same `backend.name`, the same dim, and the same vectors modulo ~4th-decimal float noise. Therefore `verify_index_compat` is unchanged, and a cross-device read (index built on CUDA, queried on CPU, or vice versa) is silently valid by construction — no new warning, no gate. This is deliberately better than warning: it avoids a stderr warning on every cross-device search. The device an index was built on is recorded for display only as `meta.embed_device` (see [storage](storage.md)).

**Packaging: CPU stays default, GPU is a documented manual swap.** `fastembed` (CPU) and `fastembed-gpu` are mutually-exclusive PyPI distributions: they share the same `fastembed` import namespace and pull mutually-exclusive onnxruntime builds (`onnxruntime` CPU vs `onnxruntime-gpu`). You install one or the other, never both. An additive `[gpu]` install extra therefore does not work cleanly. The base install keeps `fastembed` (CPU) as the default hard dependency, preserving the zero-config, offline CPU default. GPU users perform a documented manual swap: `uv pip install fastembed-gpu` (replacing `fastembed`), then set `CODE_INDEX_DEVICE=cuda`. The env var only selects a provider; whether CUDA is actually available depends on which onnxruntime build is installed. These compose: `CODE_INDEX_DEVICE=cuda` on a box with only the base `fastembed` means the CUDA provider is not registered, which is exactly the "requested cuda unavailable → warn + CPU fallback" path.

**Implementation note.** `FastembedBackend` passes `cuda=True` / `providers=[...]` to fastembed's `TextEmbedding` constructor based on the resolved device, and probes `onnxruntime.get_available_providers()` at construction both to implement `auto` and to emit the clean stderr warning when `cuda` was requested but unavailable — instead of relying on ONNX's noisy low-level fallback warning.

**Rejected alternatives.**

- **DirectML.** fastembed does not bless a DirectML build; using it means hand-installing `onnxruntime-directml` (a third mutually-exclusive onnxruntime) and passing `DmlExecutionProvider` against fastembed's own onnxruntime pin — fragile and unsupported. CUDA-only for stage one.
- **Device as a TOML key.** Committing a per-machine device value breaks portability across teammates; `auto` default plus env override is the portable mechanism.

Forward note: env-selectable *backend* (not device) from a TOML-permitted set is a roadmap item, not stage one — see [roadmap](roadmap.md).
