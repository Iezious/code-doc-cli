# MVP scope

## Decision

This document is the single source of truth for what ships in the MVP of `codedoc`. The phrase "MVP" appears as an inline qualifier across other architecture docs; when they disagree with this file, this file wins until updated.

If a feature is not listed in either column below, treat it as **implicitly out of MVP** until a decision is added here.

## Rationale

A pinned cut line keeps the first round of plans under `doc/plans/` honest. Without it, scope drifts feature by feature and "MVP" becomes a moving target. Naming what is cut, and why, is just as load-bearing as naming what is in — it prevents accidental re-litigation in every plan.

## In scope for MVP

### Languages

All seven languages on day one: F#, C#, JavaScript, TypeScript, Go, Python, LSL. See [chunking-and-languages](chunking-and-languages.md). Cutting any of them would change the engine's reason to exist — the polyglot story is the point.

### Embedding backends

- Default: `fastembed` with Jina v2 base code (768-dim, CPU, offline-capable).
- Opt-in extra: Voyage `code-3`, installed via the `[voyage]` install extra and gated by `VOYAGE_API_KEY`.

See [embeddings](embeddings.md).

### Storage

- Single SQLite file per project at `docs/.helpers/index.sqlite`.
- `sqlite-vec` extension for dense vectors.
- FTS5 for BM25.
- WAL mode at connection setup.
- Schema versioning with loud failure on mismatch.

See [storage](storage.md).

### CLI subcommands

`init`, `index build`, `index sync`, `index rebuild`, `search`, `symbols defs|refs`, `graph callers|deps`, `config show`. See [cli](cli.md).

### Retrieval

Hybrid BM25 + dense with RRF fusion (`k = 60`). Filters: `--lang`, `--kind`, `--path`, `--k`, `--bm25-k`, `--dense-k`. Mode flag `--mode bm25|dense|hybrid` is in MVP (cheap to add, useful for debugging). See [retrieval](retrieval.md).

### Output format

`--format json` is available on every subcommand that returns structured results (`search`, `symbols`, `graph`, `config show`). The JSON shape is part of the CLI contract.

### Edges

Edges are written at index time with `dst_name` as a string and **resolved lazily at query time** by joining against the `symbols` table. No resolution pass during indexing.

### Indexer walking

The walker honors `.gitignore` plus a built-in set of default excludes. The exact default-excludes list is pinned in a later pass; for the MVP gate it is enough that both mechanisms apply.

## Cut from MVP

Each item below is named, dated to "after MVP," and given the reason it was cut. Anything not on either list is implicitly out-of-MVP.

### `codedoc doctor` — deferred to v1.1

Pipelines will rely on the inline error messages emitted by each subcommand (see [errors-and-exit-codes](errors-and-exit-codes.md)) until the real failure-mode surface has shaken out under use. Building a unified `doctor` before we know which checks matter risks codifying the wrong set.

### Embedding cache (content-hash skip on re-embed) — deferred to v1.1

MVP `index sync` always re-embeds changed files. The `chunks.content_hash` column is **not present in the MVP schema** — it lands together with the cache feature via a schema bump, not as a dormant column. The [storage](storage.md) schema sketch reflects this.

### `codedoc watch` daemon mode — deferred

Already called out as not-in-scope in [architecture](architecture.md) and [cli](cli.md). Restated here for completeness.

### `codedoc search --explain` — deferred

Already an open question in [retrieval](retrieval.md) and [cli](cli.md). Cheap to add later; not on the MVP critical path.

### Benchmark harness — deferred

Already an open question in [embeddings](embeddings.md). Useful for comparing backends on a project corpus; not required to ship.

### Markdown chunking — v1.1+

Already an open question in [chunking-and-languages](chunking-and-languages.md). MVP indexes code only.

### Generated-code chunk-kind tagging — deferred

Already an open question in [chunking-and-languages](chunking-and-languages.md). Retrieval de-emphasis of generated code is a quality knob, not a correctness one.

### LSL event-payload schema extraction — out of scope

Already stated in [chunking-and-languages](chunking-and-languages.md). Requires per-project conventions the engine cannot assume.

### Cross-language graph pass and `codedoc seams` subcommand — deferred

The **seam pass itself** is consumer pipeline work and is documented in [docs-generation-pipeline](docs-generation-pipeline.md). The **engine subcommand** that would return producer/consumer pairs directly is open in that same doc and lands in v1.x at the earliest, once the seam pass has been run end-to-end and revealed its actual shape.

### Workspace-level config — deferred

Already an open question in [tool-and-data-split](tool-and-data-split.md). MVP is per-project config only.

### Private package publishing — deferred

Already an open question in [overview](overview.md) and [tool-and-data-split](tool-and-data-split.md). Editable installs are the supported MVP path.

### Vacuum scheduling — deferred

Already an open question in [storage](storage.md). MVP performs no automatic vacuum.

### Separate `files` table — deferred

Already an open question in [storage](storage.md). MVP derives the file list via `SELECT DISTINCT path FROM chunks` and lives with the cost until measurements say otherwise.

### Ripgrep fallback for `symbols` — cut (not deferred)

Symbol queries are **index-only** in MVP and beyond, for determinism. Falling back to ripgrep for live queries means the same `symbols` call can return different results depending on what is on disk vs what is indexed, which breaks the deterministic-retrieval guarantee the docs-generation pipeline depends on (see [docs-generation-pipeline](docs-generation-pipeline.md)). [architecture](architecture.md) previously mentioned the fallback as a possibility; the bullet has since been removed. This entry remains as the canonical record of the decision.

### "Re-embed only" subcommand — deferred

Already noted as a future enhancement in [embeddings](embeddings.md). MVP uses `index rebuild` whenever the embedding model changes.

## Rejected alternatives

- **No pinned MVP scope, decide per-feature.** Each plan would re-litigate the cut line. Drift is inevitable; we pay the doc cost up front instead.

## Implications

- The first planner pass under `doc/plans/` reads this file before anything else.
- Any later doc that says "MVP X" must not contradict the lists above. If it would, this file is the one to update — the contradiction is the bug.
- Cuts that name a v1.1 target are commitments to revisit, not promises to ship.

## Open questions

None for the cut line itself. Items deferred above carry their own open questions in their owning docs and will be triaged in a later open-questions sweep.
