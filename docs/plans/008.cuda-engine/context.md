# Feature 008 — cuda-engine

Shared briefing for all steps. Step-specific facts live in the sibling `<SSS>.context.md` files.

## Goal

Implement local CUDA GPU acceleration for the fastembed embedding backend, selected by a new `CODE_INDEX_DEVICE` env var. Record the resolved device as informational index provenance and surface device state in `config show`. The architecture decision is already finalized — this feature implements it without redesigning it.

## Scope

In scope:

- A device-resolution helper module reading and validating `CODE_INDEX_DEVICE`, probing onnxruntime providers, and resolving to `cpu`/`cuda` with a clean stderr warning on the requested-cuda-unavailable path.
- Wiring the resolved device into `FastembedBackend` construction (passes provider/`cuda` flag to fastembed's `TextEmbedding`) and exposing the resolved device on the backend.
- Stamping `meta.embed_device` at index build and clearing it on auto-rebuild.
- Surfacing device state in `config show`: `index.embed_device` from meta, plus two new top-level siblings `requested_device` and `effective_device`.
- README documentation of the GPU manual-swap install path.

Out of scope (do NOT plan):

- Env-selectable *backend* from a TOML-permitted set — roadmap item (see [roadmap.md](../../architecture/roadmap.md), "Env-selectable backend from a TOML-permitted set"). This feature selects the *device*, not the backend.
- DirectML support — rejected (see [embeddings.md](../../architecture/embeddings.md)).
- Any `[gpu]` install extra in `pyproject.toml` — cannot work cleanly; pyproject is unchanged.

## Authoritative architecture

These docs are ground truth. Do not contradict them.

- [embeddings.md](../../architecture/embeddings.md) — "### Update 2026-05-28: GPU acceleration".
- [config.md](../../architecture/config.md) — "### Update 2026-05-28: machine-local execution tuning via env".
- [storage.md](../../architecture/storage.md) — "### Update 2026-05-28: device provenance and unknown-engine detection".
- [cli.md](../../architecture/cli.md) — `code_index config show` section (reports `index.embed_device`, plus top-level `requested_device` and `effective_device`).

## Pinned semantics (do not deviate)

- **Env var.** `CODE_INDEX_DEVICE = auto | cpu | cuda`, default `auto`. This is the FIRST env var the codebase reads — no precedent exists. It is NOT a TOML/config key, NOT added to the config schema, NOT added to `CodeIndexConfig`.
- **Resolution.**
  - `auto`: use CUDA if onnxruntime offers `CUDAExecutionProvider`, else CPU. Silent — no warning.
  - `cuda`: explicit. If the CUDA provider is unavailable at runtime, warn on stderr and fall back to CPU.
  - `cpu`: force CPU even on a GPU box.
- **Device is NOT index identity.** `backend.name` carries the model only, not the device. fastembed-CPU and fastembed-CUDA produce the same `name`, same `dim`, same vectors (modulo float noise). Therefore `verify_index_compat` is UNCHANGED — do NOT add a device check to it, do NOT encode device into `backend.name`. A cross-device read is silently valid by construction.
- **`meta.embed_device`** records the resolved device the index was built on (`cpu`/`cuda`). INFORMATIONAL ONLY — never gates reads. Absent on pre-feature indices → renders as null/"".
- **Packaging.** Base install keeps `fastembed` (CPU) as the hard dependency. GPU is a DOCUMENTED MANUAL SWAP (`uv pip install fastembed-gpu`, replacing `fastembed`), then set `CODE_INDEX_DEVICE=cuda`. `fastembed` and `fastembed-gpu` are mutually-exclusive PyPI dists sharing the `fastembed` import namespace and pulling mutually-exclusive onnxruntime builds. NO `[gpu]` install extra. `pyproject.toml` does NOT change; this is README-only.
- **`config show`** reports `index.embed_device` (from meta, "" / null if absent), plus two NEW top-level siblings `requested_device` (raw `CODE_INDEX_DEVICE`, NO probe) and `effective_device` (resolved cpu/cuda; resolving `auto` requires the probe). `config show` is the FIRST command to instantiate a provider probe — today it touches no backend/onnxruntime. It must NOT FAIL on a broken/missing provider — diagnostic stance.

## Resolved planning decision: Protocol `device` attribute

Add `device: str` to the `EmbeddingBackend` Protocol in `protocol.py` as an informational attribute. Rationale: it is set by `FastembedBackend`, read by the indexer for meta stamping, and gives a typed contract; adding it does not break the `@runtime_checkable` protocol or any consumer (the existing implementation already satisfies the broader shape once `self.device` is set). This is a deliberate explicit call, not left implicit.

## Files touched across steps

- `src/code_index/embeddings/device.py` — new (step 001).
- `src/code_index/embeddings/protocol.py` — add `device` attribute (step 002).
- `src/code_index/embeddings/fastembed.py` — device wiring (step 002).
- `src/code_index/embeddings/factory.py` — pass device through (step 002).
- `src/code_index/indexer.py` — stamp + clear `embed_device` meta (step 003).
- `src/code_index/cli.py` — `config show` device fields (step 004).
- `README.md` — GPU install docs (step 005).

## Cross-cutting constraints

- Engine is global, data is per-project; device is machine-local and never enters committed config.
- Schema versioning is mandatory, but `meta.embed_device` is an additive KV row in the existing generic `meta(key, value)` table — it does NOT require a `schema_version` bump (the `meta` KV store is schema-stable; a new optional key is forward-compatible and pre-feature indices simply lack the row). Do not bump `schema_version` for this feature.
- stdout carries results only; warnings go to stderr (see [cli.md](../../architecture/cli.md), "Output streams and logging").
- Tests must not require a real GPU; monkeypatch `onnxruntime.get_available_providers()` and fastembed's `TextEmbedding` (see existing harnesses named per step).

## Build / test / typecheck commands

Run from repo root `D:/GitRoot/_Utils/utils.codedoc`. Paths: forward slashes, uppercase Windows drive letter, quote paths with spaces.

- Install (dev): `uv sync --extra dev`
- Tests: `uv run pytest`
- Lint: `uv run ruff check`
- Format: `uv run ruff format`
- Typecheck: `uv run pyright`
- Run scripts as `.venv/Scripts/python`.
