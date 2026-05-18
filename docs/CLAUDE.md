# `docs/` layout

This directory is the project's documentation. It has two subtrees, each with a distinct purpose:

```
docs/
  architecture/   # design decisions, one file per concern
  plans/          # work plans, one file per task
```

## `docs/architecture/`

Captures **decisions**, not implementation details. Each file owns a single concern and follows a consistent shape:

- **Decision** — what was chosen, in one or two sentences
- **Rationale** — why, briefly
- **Rejected alternatives** — what we considered and ruled out, with the reason
- **Implications** — non-obvious consequences for code, ops, or other components
- **Open questions** — anything explicitly deferred (use `TBD` sparingly and only with a note on what it depends on)

Cross-link between files where decisions interact. Treat the architecture docs as the source of truth; if code disagrees, the doc wins until it's updated.

### Current files

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

When adding a new architecture concern, prefer a new file over a section in an existing one — files are easier to link to and easier to deprecate.

## `docs/plans/`

One file per work plan. Filename format: `YYYY-MM-DD.short-name.md` (e.g. `2026-05-13.initial-mvp.md`).

A plan contains:

- **Goal** — what this plan delivers
- **Scope** — what's in, what's explicitly out
- **Steps** — ordered, concrete, each with an owner and a definition of done
- **Open questions** — blockers requiring decisions
- **Status** — pending / in-progress / done / abandoned, with date

Plans are append-only once started — don't rewrite history. If scope changes, add a note dated with the change.

## Conventions

- Markdown only. No HTML.
- Code fences use triple backticks with a language tag where it helps the reader.
- Decisions reference each other by relative link: `[storage](storage.md)`, not absolute paths.
- Keep each file focused: if a doc is exceeding ~200 lines, it's probably two concerns.
- No emojis.
