# `docs/plans/` — plan layout and lifecycle

Authoritative for plan folder structure, status vocabulary, and the multi-step vs fast distinction. Read this before authoring or modifying any plan.

## Layouts

Two layouts are supported. The planner picks one up-front; do not mix them within a single plan.

### Multi-step — `docs/plans/<NNN>.<feature>/`

Used for any feature with more than one logical change. Contents:

- `context.md` — shared briefing for all steps: feature goal, scope, architecture inputs, harvested context from the codebase, constraints, and anything every step needs to know.
- `<SSS>.<short-name>.md` — the task file for one step. `<SSS>` is a zero-padded 3-digit index within the feature (`001`, `002`, …). Stays focused on the canonical sections below; no narrative, no rationale, no implementation notes — those belong in the sibling `<SSS>.context.md`. Sections:
  - **Goal** — one sentence stating what this step delivers.
  - **Files** — paths to add or edit.
  - **Signatures** — function or class signatures introduced or changed (when applicable).
  - **Tests** — what proves the step works.
  - **Definition of done** — observable criteria; what the verifier checks.
  - **Dependencies** — other steps this step depends on, referenced by `<SSS>`.
- `<SSS>.context.md` — the step's narrow context, sibling to the task file. Holds clarifications too specific for the shared `context.md`, implementation-style notes the coder needs but that don't fit the task file's canonical sections, sequencing notes, fixture-sharing or cross-step coordination, and any inline planner-resolved ambiguities relevant only to this step. The task file may reference its context file by relative path (e.g. `See [\`001.context.md\`](001.context.md) for sequencing notes.`). Linked from the task file when useful; never silently load-bearing — the task file's Definition of done remains the contract.
- `outcome.md` — the architecture deltas this feature implies. Filled by the planner; applied by the architect during finalization. The coder may append a `## Observations` section while implementing.
- `status.md` — table tracking each step's lifecycle and verifier result.

### Fast — `docs/plans/fast/<NNN>.<name>/`

Used for a single logical change, roughly 50–300 LoC, deliverable in one coder pass. Contents:

- `context.md` — same role as the multi-step `context.md`, scoped to one change.
- `plan.md` — single-pass plan in one file, replacing the per-step files.
- `outcome.md` — same role as in multi-step.
- `status.md` — single-row tracking table.

Fast is also used for large bug fixes against already-completed plans.

## Numbering

Multi-step and fast each have their own `NNN` namespace.

- Multi-step: next free 3-digit number listed under `docs/plans/` (ignoring the `fast/` subfolder).
- Fast: next free 3-digit number listed under `docs/plans/fast/`.

Do not reuse retired numbers. Numbers are allocated in order of plan creation, not in order of completion.

## Status vocabulary

Step (or fast row) status:

- `pending` — not started.
- `wip` — in progress.
- `blocked` — cannot proceed; reason recorded in `status.md`.
- `done` — coder finished and handed back.

Verifier result:

- `pending` — not yet verified.
- `PASS` — verifier accepted the step.
- `FAIL` — verifier rejected the step; failure recorded.

`status.md` is append-only at the row level. Older rows are not rewritten when state changes; the row's status and verifier fields are updated in place, and notes are appended below the table if context is needed. Do not delete rows.

## When to use fast vs multi-step

- **Multi-step**: a feature with two or more logical changes, multiple files needing coordinated work, or non-trivial review surface. The MVP phases in [`../architecture/mvp-phases.md`](../architecture/mvp-phases.md) are all multi-step.
- **Fast**: a single logical change of roughly 50–300 LoC, no inter-step dependencies, deliverable in one coder pass. Also used for large bug fixes against already-completed plans.

If a fast plan grows beyond one logical change while being written, the planner promotes it to multi-step rather than splitting it inside `fast/`.

## Lifecycle

1. `/planner` (or `/fast-feature`) creates the folder and seeds `context.md`, the step file(s) or `plan.md`, `outcome.md`, and `status.md`.
2. `/coder` (or `/fast-coder`) implements one step at a time. The verifier emits `PASS` or `FAIL` into `status.md`.
3. `/bug-fixer` may add a `## Bug Fixes` section to `status.md` after the plan is `done`. These entries are delivery history, not new scope.
4. `/architect` finalizes by applying `outcome.md` to `docs/architecture/*.md` and appending an `Applied YYYY-MM-DD` footer to `outcome.md`. Finalization only runs after every step is `done` with verifier `PASS`.

## Conventions

- Append-only mindset. Once a step is `done`, do not rewrite its file. Record changes in a new step, in `outcome.md` observations, or via a follow-up plan.
- Architecture changes go through `/architect` and `docs/architecture/`. Do not smuggle architecture decisions into a step file.
- Cross-references between docs use relative paths.
- Markdown only. No HTML, no emojis.
