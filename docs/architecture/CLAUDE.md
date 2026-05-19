# `docs/architecture/` — architect rules

Agent-facing rules for the architect role on this project. Keep this file short and prescriptive.

## What lives here

Architecture decisions, one concern per file. Not how-to guides, not tutorials, not API reference.

These docs are the source of truth for design. If code disagrees with a doc, the doc wins until the doc is updated. Code changes that contradict a decision must update the relevant doc in the same change (or, for non-trivial revisions, route through `/architect`).

## Per-file shape

Every file follows the same skeleton: Decision / Rationale / Rejected alternatives / Implications / Open questions. The canonical wording and intent of each section is defined in [`../CLAUDE.md`](../CLAUDE.md) under `docs/architecture/`. Read it once and follow it; do not restate it here.

## Cross-linking

Reference other docs by relative path, e.g. `[storage](storage.md)`, not absolute paths or repo-root URLs. This keeps the tree portable and renders correctly in any markdown viewer.

## Length rule

A file exceeding roughly 200 lines is almost always two concerns. Split before it grows further. A long file is harder to link to, harder to revise, and harder to deprecate cleanly.

## New file vs extending an existing one

- **New file** — preferred for a new concern. Easier to link, easier to deprecate, makes the index in [`../CLAUDE.md`](../CLAUDE.md) self-describing.
- **Extend an existing file** — only when revising or refining a decision that already lives there. Append a dated note (`### Update YYYY-MM-DD`) rather than rewriting history silently.

When in doubt, start a new file. Merging is cheaper than untangling.

## Index of current files

The authoritative one-line index of architecture decision docs lives in [`quick-reference.md`](quick-reference.md). Update that file whenever you add, rename, or retire a doc — do not duplicate the listing elsewhere.

## Boundary of the architect role

- The architect **decides** and records decisions in `docs/architecture/*.md`.
- The planner and coder **execute**: turn decisions into plans and code.
- The architect does **not** write source code, step files, or plan folders.
- During finalization the architect applies an accepted `outcome.md` to the relevant architecture files and appends an `Applied YYYY-MM-DD` footer to that same `outcome.md`. That footer is the only write the architect makes outside `docs/architecture/`.

## Conventions

- Markdown only. No HTML, no emojis.
- Code fences use triple backticks with a language tag where it helps the reader.
- State the decision, name what was rejected, list implications. Avoid speculative future-scope writing — defer such items to [`roadmap.md`](roadmap.md) or to the `Open questions` section.
