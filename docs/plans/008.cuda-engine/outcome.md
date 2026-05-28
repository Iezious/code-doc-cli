# Outcome — Feature 008 cuda-engine

## Planner note: architecture authored ahead of implementation

The architecture for this feature was written BEFORE implementation, as the
"Update 2026-05-28" sections across [embeddings.md](../../architecture/embeddings.md),
[config.md](../../architecture/config.md), [storage.md](../../architecture/storage.md),
and [cli.md](../../architecture/cli.md), plus the forward note in
[roadmap.md](../../architecture/roadmap.md). This feature IMPLEMENTS those existing
decisions; it does not introduce new ones.

Therefore **no committed architecture deltas are expected from this feature.** The
architect's finalization task is to VERIFY that the shipped code matches the already-written
decisions, not to apply new prose. Specifically confirm:

- `CODE_INDEX_DEVICE` is read only via the new `device.py` helper; it is not a TOML key and
  not in `CodeIndexConfig` (matches config.md "Update 2026-05-28").
- `verify_index_compat` is unchanged and does not consult `embed_device`; `backend.name`
  does not encode the device (matches embeddings.md / storage.md).
- `meta.embed_device` is stamped at build, cleared on rebuild, and used only for display
  (matches storage.md "Update 2026-05-28").
- `config show` reports `index.embed_device`, `requested_device` (raw, no probe), and
  `effective_device` (resolved, quiet probe) as specified, and never fails on a broken probe
  (matches cli.md `config show`).
- `pyproject.toml` is unchanged; GPU is README-documented only (matches embeddings.md
  "Packaging").

## Candidate observations (NOT committed deltas)

These are places where implementation reality may justify a small doc tweak. The coder should
record any that materialize under `## Observations` below; the architect decides whether to
apply.

- **stderr warning wording.** embeddings.md describes the warn+CPU-fallback path but does not
  pin the exact warning text. If the shipped wording is worth canonizing, note it as a
  candidate addition to embeddings.md "Update 2026-05-28: GPU acceleration".
- **Device helper public signature.** The exact public surface of `device.py`
  (`requested_device`, `resolve_device`, `available_providers`, `cuda_available`) is an
  implementation choice. If a consumer relationship is worth documenting (e.g. that
  `config show` uses the quiet `warn=False` path), it could be a one-line note in cli.md or
  embeddings.md.
- **fastembed CUDA kwarg.** embeddings.md says `cuda=True` / `providers=[...]`. If the
  installed fastembed-gpu accepts only one of these, note the actual kwarg used so the doc's
  "Implementation note" can be made precise.
- **`embed_device` null vs "" rendering.** cli.md's JSON contract shows `index.embed_device`
  as `null` for pre-feature indices. If the existing index-block convention renders absent
  meta as `""` (string) and step 004 follows that for sibling consistency, note the
  discrepancy so cli.md can be reconciled to whichever the code actually does.

## Observations

_populated by the coder as steps complete_

- Step 002: fastembed CUDA kwarg. The installed (CPU) fastembed's `TextEmbedding.__init__`
  signature is `(model_name, cache_dir, threads, providers, cuda=Device.AUTO, device_ids,
  lazy_load, **kwargs)`. `FastembedBackend` passes `providers=[CUDA_PROVIDER,
  "CPUExecutionProvider"]` on the resolved-`cuda` path and `providers=None` (fastembed's
  default — behaviorally identical to the prior no-kwarg CPU construction) otherwise. It does
  NOT pass `cuda=True`. `providers=[...]` alone is sufficient and version-tolerant; the doc's
  `cuda=True` / `providers=[...]` wording in embeddings.md "Implementation note" could be made
  precise to "passes `providers=[CUDAExecutionProvider, CPUExecutionProvider]`".
- Step 004: `embed_device` null vs "" rendering. The existing `index` block convention renders
  present-but-absent meta rows as `""` (string), not `null` — `_read_index_meta` coerces every
  missing `meta` row via `get_meta(conn, key) or ""`, so a pre-feature index with no
  `embed_device` row shows `index.embed_device == ""` (the JSON `null` is reserved for the
  whole-`index`-block-absent case, where the db file does not exist). Step 004 followed the
  sibling-key convention for consistency (`embed_device` joins `schema_version`/`embed_model`/
  etc., all of which render `""` when absent). cli.md's JSON contract describes
  `index.embed_device` as `null` for pre-feature indices; this diverges from the actual
  per-key rendering. Possible impact: reconcile cli.md's wording to "`""` when the index is
  built but predates the feature; the whole `index` block is `null` only when no index exists"
  — or, if `null` per-key is genuinely wanted, that is a behavior change spanning all index
  keys and out of scope for this step.
