# Claude session guide — utils.codedoc

`code_index` is a CLI tool that builds a per-project SQLite index of a polyglot codebase (F#, C#, JS, TS, Go, Python, LSL) with hybrid BM25 + dense retrieval. It exists to power documentation-generation pipelines run by Claude agents.

## Read first

- `docs/CLAUDE.md` — layout of the `docs/` tree and conventions
- `docs/architecture/overview.md` — what this tool is and why
- `docs/architecture/architecture.md` — components and data flow
- `docs/plans/` — current and past work plans, one file per task

The architecture docs are the source of truth for design decisions. Don't add code that contradicts them without updating the doc in the same change.

## Workflow expectations

- Implementation lives under `src/code_index/` once the build session begins. The tree is currently code-free by design.
- Use `uv` for everything Python: `uv tool install --editable .` for install, `uv sync` for dev, `.venv/Scripts/python` to run scripts.
- Path conventions: forward slashes, uppercase Windows drive letters, quoted paths with spaces.
- Don't introduce languages, embedding backends, or storage choices not covered in `docs/architecture/`. If you need to, write the decision doc first.

## Scope discipline

- Engine is global, data is per-project. Engine code lives in this repo; per-project config and index data live in the target project's `docs/.helpers/`.
- Schema versioning is mandatory — every persisted artifact carries the schema version it was built with.
- This repo does not store any indices; `.sqlite` files are gitignored.

## When working on this project

- Architecture decisions go in `docs/architecture/`. New decisions get a new file or extend an existing one with a dated note.
- Task plans go in `docs/plans/<YYYY-MM-DD>.<short-name>.md`.
- Keep architecture docs concise: state the decision, name what was rejected, list implications. Avoid speculative future-scope writing.

## Build & Test Commands

- Install (dev environment): `uv sync --extra dev`
- Install (editable CLI): `uv tool install --editable .`
- Tests: `uv run pytest`
- Lint: `uv run ruff check`
- Format: `uv run ruff format`
- Typecheck: `uv run pyright` — note: `pyright` is added to the `[dev]` extras as part of Phase 1 (see `docs/architecture/mvp-phases.md`); this command becomes available after Phase 1 ships.

Downstream agents (planner, coder, verifiers) read build/test/typecheck commands from this section.
