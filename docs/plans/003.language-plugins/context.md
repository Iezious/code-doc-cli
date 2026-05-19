# Feature 003 — Language plugins

This folder plans **Phase 3 — Plugin interface and seven languages** from [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md). The deliverable is the `code_index.languages` package: the shared `Chunk`/`Symbol`/`Edge` dataclasses, the `Language` Protocol, a registry that dispatches by file extension and loads `extra_languages`, and one plugin per supported language (Python, C#, JavaScript, TypeScript, Go, F#, LSL).

## Goal

- Pin the `Language` interface and shared dataclasses per [`../../architecture/chunking-and-languages.md`](../../architecture/chunking-and-languages.md) "Plugin interface" section.
- Provide a `LanguageRegistry` that maps extension → plugin, applies `config.languages` filtering, and loads `config.extra_languages` modules via `importlib.util`.
- Ship all seven built-in plugins, each in its own module, each exposing a top-level `LANGUAGE` (single plugin) or `LANGUAGES` (tuple) export.
- For every plugin, lock behavior via a `syrupy` snapshot test against one canonical fixture source file exercising every chunk kind, symbol kind, and edge kind the plugin emits.

## Scope envelope

Strictly Phase 3's bullet list and DoD from `mvp-phases.md`. Out of scope here:

- The walker, indexer pipeline, `init`, `index build` (Phase 4).
- Search and retrieval (Phase 5).
- Sync / symbols / graph / rebuild (Phase 6).
- Voyage backend and `config show` index meta (Phase 7).
- OSSL (`osXxx`) recognition in the LSL plugin — deferred; recorded as an architect question in [`outcome.md`](outcome.md).
- Generated-code chunk-kind tagging, Markdown chunking, LSL event-payload schema extraction — all already cut from MVP per [`../../architecture/mvp-scope.md`](../../architecture/mvp-scope.md).
- Any changes to Phase 1 modules (`errors.py`, `config.py`, `storage/`, `cli.py`) and Phase 2 modules (`embeddings/`). Phase 3 strictly adds the `languages/` package and one dev-dep (`syrupy`) to `pyproject.toml`.

## Architecture inputs (authoritative)

- [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md) — Phase 3 section; bullet list + DoD.
- [`../../architecture/chunking-and-languages.md`](../../architecture/chunking-and-languages.md) — the load-bearing design doc: `Language` Protocol, shared dataclasses, per-plugin parsing strategy, chunk-sizing guidance, symbol-identity conventions, dispatch and registry rules.
- [`../../architecture/config.md`](../../architecture/config.md) — `languages` and `extra_languages` schema keys and validation rules.
- [`../../architecture/mvp-scope.md`](../../architecture/mvp-scope.md) — all seven languages ship at MVP; no per-plugin config schema yet.
- [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md) — `parsing.plugin_error` (code 30) for plugin raises under `--strict`; default behavior is skip + warn. `config.unknown_language` and `config.bad_path` (code 2) for `extra_languages` loader failures.
- [`../001.foundations/context.md`](../001.foundations/context.md) — Phase 1 framing, shared vocabulary, dependency direction.
- [`../001.foundations/002.errors.md`](../001.foundations/002.errors.md) — `CodeIndexError`, `Kinds`, `EXIT_CONFIG`, `write_log_stderr`.
- [`../001.foundations/003.config.md`](../001.foundations/003.config.md) — `CodeIndexConfig` shape including `languages: list[str] | None` and `extra_languages: list[Path]`.
- [`../002.embedding-backend/context.md`](../002.embedding-backend/context.md) — confirms the "package from day one" layout convention this phase follows.
- Root `CLAUDE.md` — Build & Test Commands (verifier reads from here).
- `docs/CLAUDE.md` — markdown conventions; no emojis, no HTML.

## User-confirmed decisions

1. **Snapshot tests via `syrupy`.** Added to `pyproject.toml` `[project.optional-dependencies].dev` as `syrupy>=4` in step 001. Per-plugin snapshot files live alongside the test file as `tests/__snapshots__/test_<lang>_plugin.ambr` (syrupy's default location) and are produced via `pytest --snapshot-update` on first run. Snapshots are committed.
2. **`extra_languages` registration via top-level `LANGUAGE` constant.** Every plugin module (built-in or extra) exposes either:
   - `LANGUAGE: Language` — a single plugin instance, OR
   - `LANGUAGES: tuple[Language, ...]` — multiple plugin instances.
   The loader does `importlib.util.spec_from_file_location` for `extra_languages` paths, executes the module, then reads `LANGUAGE` / `LANGUAGES`. Built-in plugins use the same shape for consistency: `src/code_index/languages/python.py` exposes `LANGUAGE = PythonPlugin()`, etc. The registry collects exports rather than relying on import side effects (no decorator magic, no module-level `register(...)` calls).
3. **OSSL deferred.** The Phase 3 LSL plugin recognizes pure LSL only — no `osXxx` recognition. OSSL is flagged in [`outcome.md`](outcome.md) as an architect question (it needs per-plugin config schema, e.g. a `[code_index.languages.lsl]` sub-table; that schema does not yet exist). Phase 3 does NOT extend Phase 1's config schema.

## Files touched across steps

| Area | Path | Step(s) |
|---|---|---|
| package init | `src/code_index/languages/__init__.py` | 001 |
| shared types + protocol | `src/code_index/languages/protocol.py` | 001 |
| registry + loader | `src/code_index/languages/registry.py` | 001 |
| python plugin | `src/code_index/languages/python.py` | 002 |
| C# plugin | `src/code_index/languages/csharp.py` | 003 |
| JS plugin | `src/code_index/languages/javascript.py` | 004 |
| TS plugin | `src/code_index/languages/typescript.py` | 005 |
| Go plugin | `src/code_index/languages/golang.py` | 006 |
| F# plugin | `src/code_index/languages/fsharp.py` | 007 |
| LSL plugin | `src/code_index/languages/lsl.py` | 008 |
| dev deps | `pyproject.toml` (`syrupy>=4`) | 001 |
| registry tests | `tests/test_languages_registry.py` | 001 |
| plugin tests | `tests/test_<lang>_plugin.py` | 002–008 |
| fixture sources | `tests/fixtures/languages/<lang>/sample.<ext>` | 002–008 |
| extra-lang fixture | `tests/fixtures/languages/extra/synthetic_lang.py` | 001 |
| extra-lang fixture config | `tests/fixtures/languages/extra/config_with_extra.toml` | 001 |
| F# .fsproj fixture | `tests/fixtures/languages/fsharp/sample.fsproj` | 007 |
| snapshot files | `tests/__snapshots__/test_<lang>_plugin.ambr` | 002–008 |

## Cross-cutting constraints

- **One plugin = one module = one `LANGUAGE` export.** No registry side effects on import beyond defining `LANGUAGE`. The registry's `from_builtins()` does the importing and harvesting.
- **`Language` is a `@runtime_checkable` Protocol.** Every plugin must satisfy `isinstance(plugin, Language)`.
- **Plugin `name` and `extensions` match `chunking-and-languages.md`'s "Per-language plugins" section verbatim.** Names: `"python"`, `"csharp"`, `"javascript"`, `"typescript"`, `"go"` (note: module is `golang.py`, plugin name is `"go"`), `"fsharp"`, `"lsl"`. Extensions: as documented per plugin.
- **Plugins never call I/O.** `chunk`, `symbols`, `imports` receive `(path, content)`. The F# plugin reads `.fsproj` only if its caller passes its location — see step 007 context for the exact call shape.
- **Plugins never raise on malformed input in the default path.** Errors are converted to the plugin returning sensible empty results; raising is reserved for genuinely undecidable cases (Phase 4 will catch and apply skip-or-strict per [`../../architecture/errors-and-exit-codes.md`](../../architecture/errors-and-exit-codes.md), code 30). Phase 3 does not implement skip/strict at the call site — only the plugins' own error-tolerance.
- **No engine code changes outside `src/code_index/languages/`** and the single `pyproject.toml` edit. In particular, `config.py` is not modified — `extra_languages` validation already exists from Phase 1 (resolves paths, raises `config.bad_path`); the registry layer consumes the resolved list.
- **Steps 002–008 are independent.** They each depend only on step 001. They can be coded in parallel.
- **Snapshot files are committed.** Treat snapshot diffs in PRs as semantic changes to plugin output and review accordingly.
- **No emojis, no HTML; forward slashes** in any path strings in tests or docs.

## Shared vocabulary

- **Plugin** — an object satisfying the `Language` Protocol.
- **Built-in plugins** — the seven modules under `src/code_index/languages/` whose `LANGUAGE` exports are collected by `LanguageRegistry.from_builtins()`.
- **Extra language** — a plugin loaded at config time from a path in `config.extra_languages`, via `importlib.util`.
- **Registry** — a `LanguageRegistry` instance: extension → plugin map plus the name-filter helper.
- **Active plugins** — registry after `filter_active(config.languages)` is applied; unlisted built-ins are dropped, extras are kept.
- **Snapshot** — a syrupy `.ambr` file capturing the exact list of `Chunk` / `Symbol` / `Edge` dataclass instances produced by a plugin for one fixture file.

## Dependency direction

```
001 interface-and-registry
   |
   +-- 002 python-plugin
   +-- 003 csharp-plugin
   +-- 004 javascript-plugin
   +-- 005 typescript-plugin
   +-- 006 go-plugin
   +-- 007 fsharp-plugin
   +-- 008 lsl-plugin
```

001 is foundational. 002–008 are independent of each other and may be coded in parallel. Each plugin step depends only on the interface + registry from 001 (so its module can be discovered by `from_builtins()`) and on Phase 1's errors module (only for the F# warn path that uses `write_log_stderr`).

## Phase 3 DoD (the contract)

Per [`../../architecture/mvp-phases.md`](../../architecture/mvp-phases.md):

- `uv sync --extra dev` succeeds (new dev dep: `syrupy>=4`).
- `uv run pytest` passes — every per-plugin snapshot test plus the registry tests.
- `uv run ruff check` passes.
- `uv run pyright` passes — every plugin satisfies the `Language` Protocol structurally.
- For each of the seven languages, the snapshot under `tests/__snapshots__/test_<lang>_plugin.ambr` reflects the expected chunk/symbol/edge output for its fixture source.
- The registry resolves every documented extension to the correct plugin.
- `extra_languages` from `tests/fixtures/languages/extra/config_with_extra.toml` loads `synthetic_lang.py` and registers it without engine code changes.
- LSL plugin handles pure LSL only — `osXxx` calls are not recorded as `ref` symbols or as edges. (OSSL deferred to a later feature; see [`outcome.md`](outcome.md).)
