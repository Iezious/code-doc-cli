# Docs-generation pipeline

## Decision

`codedoc` is the **retrieval layer** for a multi-agent documentation pipeline. It is not the pipeline itself — the pipeline lives in the consuming project's agent setup. This document captures the **shape of the pipeline that motivated `codedoc`'s design**, so future engine changes stay aligned with the consumer.

## Rationale

The pipeline shape is the reason every engine decision exists. Without it, several choices look arbitrary. With it, they fall out naturally:

- Determinism → orchestrator can trust the retrieval layer.
- Hybrid retrieval → handles both conceptual and symbol queries an agent emits.
- Per-project indices → match the pipeline's per-project orchestration.
- Cheap incremental sync → re-runs after code change cost minutes, not hours.

## Pipeline shape

```
Meta-orchestrator (Opus, very thin)
  |
  +-- build/sync codedoc index (per project)
  |
  +-- Per-project pipeline:
  |     +-- planner-explorer (Opus, bounded loop)
  |     |     +-- queries `codedoc search`, `symbols`, `graph` via CLI
  |     |     +-- iterates: outline ↔ targeted scrapes
  |     |     +-- emits outline + provenance digest
  |     +-- writers (Sonnet, parallel)
  |           +-- each section gets outline slot + retrieval digest
  |           +-- writers cite via codedoc-returned file:line
  |
  +-- Cross-language seam pass:
  |     +-- dedicated Opus pass over code_doc_cli.graph + code_doc_cli.symbols
  |     +-- documents producer/consumer pairs across F#/TS/LSL boundaries
  |
  +-- Stitch + review (Opus)
        +-- consistency, cross-references, tone
```

## Role of `codedoc` in each phase

| Phase | What codedoc does |
|---|---|
| Map | `codedoc symbols defs` + `codedoc config show` produce the cheap top-level map without LLM tokens. |
| Plan / explore | `codedoc search` is the primary tool for "give me chunks about X." Bounded loop in the planner-explorer reduces to "another search query," not "another subagent dispatch." |
| Write | Writers consume retrieval digests prepared by the planner — they do not call `codedoc` themselves (keeps writer prompts short and cacheable). |
| Cross-language seam | `codedoc graph` queries identify the integration points; per-side context fetched with `codedoc search` and `codedoc symbols refs`. |
| Stitch / review | No direct codedoc call; orchestrator works from agent outputs. |

## Why retrieval-first beats subagent-first

- An Opus subagent re-reading a 20-file module costs ~minutes and ~10k+ tokens. A `codedoc search` call costs ~100ms and ~0 tokens of LLM.
- Subagent results are non-reproducible. CLI results are deterministic — the same query returns the same chunks until the index changes.
- The planner-explorer loop's iteration budget mostly evaporates: replacing "dispatch another scraper" with "issue another query" removes the cost rationale for capping iterations tightly.

## What codedoc does *not* do for the pipeline

- It does not summarize. Summarization stays with the LLM; codedoc returns raw chunks with `file:line`.
- It does not enforce doc style or structure. The pipeline owns voice, audience, format.
- It does not orchestrate. Multi-agent coordination is the consumer's concern.
- It does not produce documentation. The output of codedoc is *retrieval results*; the output of the pipeline is *docs*.

## Iteration budgets (recommended for consumers)

These belong to the pipeline, not the engine, but are recorded here so consumers don't need to re-derive them:

- **Per-project planner-explorer:** max 3 rescrape rounds, max ~15 files per round.
- **Cross-language seam pass:** max 5 rescrape rounds (the hardest pass, deserves the loosest budget).
- **Hard per-project token cap** so one runaway loop cannot burn the whole budget.

## Prompt-caching alignment

The pipeline benefits from prompt caching when codedoc returns *stable* results across iterations. Two implications for engine design:

- Search results should be **deterministic** for a given index state and query. Avoid hidden randomness (e.g., embedding model nondeterminism between runs).
- Result formatting should be **stable**. `--format json` exists precisely so agents can cache on a stable shape.

## Implications

- Engine features that change retrieval semantics (new fusion method, default `k` change) are user-visible to the pipeline and need a config knob, not a silent default swap.
- `codedoc doctor` exists in part so the pipeline can fail fast if the index is stale or mismatched before spending tokens.
- The seam-pass design depends on the `edges` table being meaningful per language. This is enforced by the language plugins — see `chunking-and-languages.md`.

## Open questions

None pinned here. A `codedoc seams` engine subcommand was demoted to [roadmap](roadmap.md); the `codedoc search --explain` item is tracked in the same place under [cli](cli.md).
