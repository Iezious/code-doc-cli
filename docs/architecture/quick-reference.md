# `docs/architecture/` — quick reference

One-line index of every architecture decision doc in this directory. Update this file whenever you add, rename, or retire a doc.

## Files

- `overview.md` — what `code_index` is and who uses it
- `architecture.md` — components and data flow
- `storage.md` — SQLite + sqlite-vec + FTS5 index design
- `embeddings.md` — embedding backend choice and swap interface
- `retrieval.md` — hybrid BM25 + dense retrieval with RRF fusion
- `chunking-and-languages.md` — language plugin interface and per-language notes
- `cli.md` — command surface
- `tool-and-data-split.md` — global engine vs per-project config and data
- `docs-generation-pipeline.md` — how `code_index` is used by the doc-gen pipeline
- `mvp-scope.md` — single source of truth for what ships in the MVP and what is cut
- `config.md` — full `config.toml` schema, defaults, and validation rules
- `errors-and-exit-codes.md` — CLI failure-mode contract (exit codes, `kind` strings, JSON envelope)
- `roadmap.md` — v1.1+ items demoted from architecture open-question lists, with pointers back to source docs
- `mvp-phases.md` — seven-phase implementation delivery sequence for the MVP, with per-phase Definitions of Done

## Conventions

- Prefer a new file over a section in an existing doc — files are easier to link to and easier to deprecate.
- Per-file shape and write rules live in [`CLAUDE.md`](CLAUDE.md).
