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

A one-line index of the current decision files lives in [`architecture/quick-reference.md`](architecture/quick-reference.md). Agent-facing write rules for the architect role live in [`architecture/CLAUDE.md`](architecture/CLAUDE.md).

## `docs/plans/`

Layout and lifecycle for planning files live in [`docs/plans/CLAUDE.md`](plans/CLAUDE.md) — that file is authoritative for plan folder structure, status vocabulary, and the multi-step vs fast distinction. Read it before authoring or modifying any plan.

## Conventions

- Markdown only. No HTML.
- Code fences use triple backticks with a language tag where it helps the reader.
- Decisions reference each other by relative link: `[storage](storage.md)`, not absolute paths.
- Keep each file focused: if a doc is exceeding ~200 lines, it's probably two concerns.
- No emojis.
