# Roadmap

## Purpose

This file is the home for v1.1+ items demoted from the `Open questions` sections of the architecture docs. It is **not** a decision doc — it does not follow the canonical Decision / Rationale / Rejected / Implications / Open shape. Entries here are *not* commitments; they are deferred work captured with enough context that whoever picks one up does not have to re-derive the motivation. Each entry points back to the originating doc(s) so the original framing is one click away.

In-scope MVP items do **not** belong here, even if they were once open questions. The roadmap is strictly v1.1+. Items that were rejected outright (rather than deferred) also do not belong here — those live as "Rejected alternatives" in their owning docs.

## Index storage and maintenance

### Separate `files` table

- Source: [storage](storage.md).
- Why deferred: MVP derives the file list via `SELECT DISTINCT path FROM chunks` and lives with the cost; a separate table is likely needed once graph/symbol indices grow large enough for the distinct scan to matter.
- What unlocks it: measurements showing the distinct-scan cost is a real bottleneck on a representative index.

### Vacuum scheduling

- Source: [storage](storage.md).
- Why deferred: MVP performs no automatic vacuum; whether to vacuum on a schedule or after sync above a delete threshold is an operational tuning question.
- What unlocks it: observed index bloat after enough sync cycles to characterize the delete-to-bloat ratio.

### Embedding cache (content-hash skip) and `chunks.content_hash` column

- Source: [embeddings](embeddings.md), [storage](storage.md), [mvp-scope](mvp-scope.md).
- Why deferred: MVP `index sync` always re-embeds changed files; the cache and the supporting column land together via a schema bump, not as a dormant column in MVP.
- What unlocks it: a corpus with high duplicate-chunk rate (or expensive paid embedding) where the re-embed cost is the dominant sync cost.

### "Re-embed only" subcommand

- Source: [embeddings](embeddings.md).
- Why deferred: MVP uses `code_index index rebuild` whenever the embedding model changes; a dedicated re-embed path preserves chunk rows and only rewrites the vec table.
- What unlocks it: large indices where dropping and re-chunking on every model swap becomes painful enough to justify the extra subcommand.

## CLI surface additions

### `code_index watch` daemon mode

- Source: [cli](cli.md), [architecture](architecture.md).
- Why deferred: live file watching is plausible but not part of MVP — explicit `index sync` covers the use case at lower implementation cost.
- What unlocks it: a workflow where the latency between save and queryable index is a real productivity hit.

### `code_index search --explain`

- Source: [cli](cli.md), [docs-generation-pipeline](docs-generation-pipeline.md).
- Why deferred: cheap to add but not critical for MVP; useful for diagnosing which retrieval source (BM25 vs dense) contributed which chunk.
- What unlocks it: first time a pipeline debug session needs per-source contributions to explain a surprising result.

### `code_index doctor`

- Source: [cli](cli.md), [mvp-scope](mvp-scope.md).
- Why deferred: building a unified diagnostic before the inline-failure surface has shaken out risks codifying the wrong set of checks. Tracked here for visibility; the canonical deferral note lives in [mvp-scope](mvp-scope.md).
- What unlocks it: enough real failures observed in pipeline use to know which checks are worth bundling.

### `code_index graph --depth` (transitive callers/deps)

- Source: [cli](cli.md).
- Why deferred: depth > 1 requires iterative re-resolution against the symbols table at query time (see [storage](storage.md)'s Edge resolution); the cost model is O(result_size x depth) joins and was not worth bundling into MVP before measurements show a need.
- What unlocks it: a real query pattern where a single-hop graph view leaves the consumer unable to answer their question without scripting around the CLI.

### `code_index seams` subcommand

- Source: [docs-generation-pipeline](docs-generation-pipeline.md).
- Why deferred: the seam *pass itself* is consumer pipeline work that composes `graph` + `symbols` + `search`; a dedicated engine subcommand should wait until the pass has run end-to-end and revealed its actual shape.
- What unlocks it: a stable seam-pass implementation that has converged on a producer/consumer query shape worth promoting into the engine.

## Embedding ecosystem

### Benchmark harness

- Source: [embeddings](embeddings.md).
- Why deferred: useful for comparing backends on a project's own corpus but not required to ship; the default Jina-code-v2 choice is well-supported without it.
- What unlocks it: a second user with a corpus where the default model underperforms and a backend swap needs evidence.

## Content coverage

### Markdown chunking

- Source: [chunking-and-languages](chunking-and-languages.md), [mvp-scope](mvp-scope.md).
- Why deferred: MVP indexes code only; chunking READMEs and design notes alongside code is plausibly useful but expands the chunk-kind taxonomy.
- What unlocks it: pipeline runs where missing Markdown context demonstrably hurts retrieval quality.

### Generated-code chunk-kind tagging

- Source: [chunking-and-languages](chunking-and-languages.md), [mvp-scope](mvp-scope.md).
- Why deferred: retrieval de-emphasis of generated code is a quality knob, not a correctness one; MVP treats generated code like any other code.
- What unlocks it: a corpus where generated files dominate retrieval results and crowd out hand-written code.

### Cross-language graph pass

- Source: [overview](overview.md).
- Why deferred: cross-language semantic linking (e.g., HTTP endpoint defined in F#, called from TS) is explicitly out of MVP; it is a candidate for v1.x follow-on.
- What unlocks it: the seam pass having run end-to-end against the per-language `edges` tables and revealed which cross-language joins are worth the engine investment.

## Packaging and distribution

### Private package index publishing

- Source: [overview](overview.md), [tool-and-data-split](tool-and-data-split.md).
- Why deferred: public GitHub install via `uv tool install git+...` satisfies the common end-user install need; a package index becomes valuable later for signed/cached artifacts or for private deployments.
- What unlocks it: a deployment context where pulling from GitHub at install time is unacceptable (offline CI, private mirrors, signed-artifact requirements).

### Workspace-level config

- Source: [tool-and-data-split](tool-and-data-split.md).
- Why deferred: MVP is per-project config only; a workspace-level config (e.g., `_Utils/code_index.workspace.toml`) that defaults values across sibling projects is plausible but speculative without a real driver.
- What unlocks it: a workspace with enough sibling projects that the per-project config files become substantially duplicated.
