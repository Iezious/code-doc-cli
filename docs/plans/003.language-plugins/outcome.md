# Outcome — feature 003 language plugins

Architecture deltas this feature implies. Applied by `/architect` at finalization.

## Planner section

### `docs/architecture/chunking-and-languages.md`

- **Target section:** "Dispatch and registry".
- **Change:** add one sentence pinning the discovery mechanism: each plugin module — built-in or extra — exposes a top-level `LANGUAGE: Language` (single plugin) or `LANGUAGES: tuple[Language, ...]` (multiple). The registry collects these exports; there are no decorator-based registrations and no module-level `register(...)` calls.
- **Reason:** the section currently says plugins "register themselves by extension at import time" without saying how. Phase 3 pins the exact mechanism. Removes the only remaining ambiguity for anyone adding language number eight.

### `docs/architecture/chunking-and-languages.md` (LSL subsection)

- **Target section:** "LSL (`languages/lsl.py`)" — "OpenSim / OSSL" bullet.
- **Change:** record that the Phase 3 LSL plugin recognizes pure LSL only — no `osXxx` recognition. The architect-callable question: OSSL recognition requires per-plugin config schema (e.g. a `[code_index.languages.lsl]` sub-table) that does not yet exist in `config.md`'s schema, and no schema for plugin-level config is committed. Options for the architect: (a) commit the per-plugin sub-table schema before someone files an OSSL bug, (b) accept OSSL is out-of-scope until v1.x and update the LSL section to say so, or (c) ship an env-var override as a stopgap (rejected for behavior overrides in `config.md`'s rationale; surfaced here for completeness).
- **Reason:** the doc currently implies OSSL recognition is opt-in but ready. Phase 3 ships without it. The doc should match shipped behavior and either commit to a plugin-config schema or downgrade the OSSL line to "deferred".

### `docs/architecture/config.md`

- **Target section:** "Open questions" or "Implications" (architect picks).
- **Change:** note the open question: per-plugin config sub-tables (`[code_index.languages.lsl]`, etc.) are anticipated by the existing prose ("flat enough to scan and structured enough that future sections (`[code_index.languages.fsharp]`, etc.) can be added without breaking existing keys") but no concrete schema exists. OSSL is the first concrete consumer that would need it. Decide before Phase 4+ or before a Phase 3 bug report.
- **Reason:** surfacing the open question now keeps it from being re-litigated in a later plan. Either commit a schema or commit "deferred — `code_index.languages.<lang>` sub-tables land in v1.x".

### `docs/architecture/errors-and-exit-codes.md`

- **Target section:** "Config (code 2)".
- **Change:** confirm that `config.unknown_language` and `config.bad_path` are reused by the registry's `load_extra_language` for `extra_languages` module-loading failures (missing file, missing `LANGUAGE` / `LANGUAGES` export). No new kinds added.
- **Reason:** the loader is a second consumer of these kinds beyond the config validator. The doc should record that the kind surface is uniform across consumers so agents do not encounter the same `kind` from two different code paths and assume they are different failure modes.

### `docs/architecture/chunking-and-languages.md` (F# subsection — optional)

- **Target section:** "F# (`languages/fsharp.py`)" — "Important detail" bullet.
- **Change:** if Phase 3 records `fsproj_order` on `Chunk.scope` (Option A from [`007.context.md`](007.context.md)), document the chosen storage form here so consumers know the format. Skip if the architect prefers the doc stay implementation-neutral.
- **Reason:** records the concrete storage form; non-load-bearing if the architect prefers neutrality. Coder updates this entry with the actual chosen form once Step 007 lands.

### `docs/architecture/mvp-phases.md`

- **No change.** Phase 3's DoD is met as stated by this plan.

## Scope summary (for the architect's record)

Phase 3 ships the `code_index.languages` package: shared `Chunk` / `Symbol` / `Edge` dataclasses, the runtime-checkable `Language` Protocol, a `LanguageRegistry` with extension dispatch + `extra_languages` loading + `config.languages` filtering, and seven built-in plugins (Python via stdlib `ast`; C# / JS / TS / Go via tree-sitter; F# and LSL hand-rolled). Each plugin has a syrupy snapshot test against a fixture source file exercising every chunk kind, symbol kind, and edge kind it emits. OSSL is deferred — the LSL plugin recognizes pure LSL only.

Phase 3 DoD per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md):

- `uv sync --extra dev` succeeds (new dev dep: `syrupy>=4`).
- `uv run pytest` / `uv run ruff check` / `uv run pyright` all pass.
- For each of seven languages, a fixture file produces the expected `Chunk` / `Symbol` / `Edge` lists via snapshot.
- Registry resolves an extension to the correct plugin; `extra_languages` from a fixture config loads and registers a synthetic plugin without engine changes.

## Observations

- Step 007: the F# plugin is the documented exception to the "plugins are pure `(path, content) -> data`" rule. It supports both discovery modes: a caller-supplied `.fsproj` path via `FSharpPlugin(fsproj_path=...)` (cleaner, Phase-4-friendly — the caller can resolve the project once and inject it), and self-discovery via a depth-bounded parent-walk (the pragmatic Phase-3 default; `LANGUAGE = FSharpPlugin()` uses this form). This tension is surfaced for the architect: at finalization, the architect can decide whether to (a) leave the F# carve-out as-is, (b) standardize on the caller-supplied form by adding a per-plugin meta channel to the `Language` Protocol in a later phase, or (c) record this as deferred to Phase 4's call-site design.
- Step 007: the `chunking-and-languages.md` preamble added on 2026-05-19 forbidding filesystem traversal for *symbol identity* purposes stays correct as written — F# does not use `.fsproj` for naming. The compile-order index lives only on `Chunk.scope` as a `|fsproj=<N>` suffix (chunk metadata, not symbol identity); `Symbol.name` is composed against the *undecorated* enclosing scope so qualified symbol names never carry the marker. The "no I/O for naming" rule and F#'s `.fsproj`-for-ordering carve-out live in different concerns and do not conflict at the symbol-name level.
- Step 007: chose storage form A (Option A from `007.context.md`) — the `fsproj_order` is appended to `Chunk.scope` as a `|fsproj=<N>` suffix, with no new fields on the `Chunk` dataclass. The architect may want to record this concrete choice in `chunking-and-languages.md`'s F# "Important detail" bullet (the planner-authored outcome section already lists this as an optional doc update); the alternative is to keep the architecture doc implementation-neutral and leave the format pinned only by the snapshot.

## Applied 2026-05-20

Finalized via `/architect`. The following items from "Planner section" and "Observations" were applied to `docs/architecture/`:

- Item 1 — `chunking-and-languages.md` "Dispatch and registry": `LANGUAGE` / `LANGUAGES` export mechanism pinned. Applied as written.
- Item 2 — `chunking-and-languages.md` LSL "OpenSim / OSSL": rewritten to record OSSL as deferred to v1.x; cross-links the config.md per-plugin sub-table open question. Applied with modification.
- Item 3 — `config.md` "Open questions": per-plugin sub-table schema question added. Applied as written.
- Item 4 — `errors-and-exit-codes.md` "Config (code 2)": clarifying paragraph added recording `config.bad_path` and `config.unknown_language` as having a second producer in the registry's `load_extra_language`. Applied with modification.
- Item 5 — `chunking-and-languages.md` F# "Important detail": shipped Option A storage form (`|fsproj=<N>` suffix on `Chunk.scope`) documented. Applied with modification.
- Observations 1 & 2 (folded together) — `chunking-and-languages.md` Implications F# bullet: rewritten to call out F# as the documented exception to the no-I/O rule, scope the exception to chunk metadata (not symbol identity), document the hybrid `fsproj_path=` discovery, and defer the Plugin Protocol meta-channel question to Phase 4. Applied with modification.

Items deliberately not applied:

- `mvp-phases.md` (Item 6 in planner section): no change required — Phase 3 DoD is met as stated.
- Observation 3 — `fsproj_order` storage form: subsumed into Item 5 (same content); not a separate doc change.
- `quick-reference.md`: no change — the one-line characterizations of the affected docs still hold.

Items deliberately not surfaced to architecture (not in outcome.md, recorded only in step verifier reports):

- Step 005 advisory: TS namespace-nested exports (when the outer namespace is not itself exported) do not surface in `symbols()`. Behavior pinned by snapshot; user chose to leave as-is during execution.
- Step 008 advisories: DoD-wording inconsistencies in `008.lsl-plugin.md` regarding `imports()` returning `[]` vs the four edge kinds, and `llMessageLinked` first-arg vs second-arg. These are planner-side step-file wording bugs; the architecture doc's Edge dataclass already documents `imports()` as returning all outbound edge kinds (not import-specific). Plans are append-only; not applied.
