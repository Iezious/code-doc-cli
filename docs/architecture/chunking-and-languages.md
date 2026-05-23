# Chunking and language plugins

## Decision

Chunking is **AST-aware** wherever a usable parser exists, and **regex-based** where it does not. Each language is a self-contained plugin module implementing one interface; the chunker dispatches to plugins by file extension.

Supported languages at MVP: **F#, C#, JavaScript, TypeScript, Go, Python, LSL.**

## Rationale

- AST-aware chunking preserves function/class/state boundaries — critical for both retrieval (chunks that mean something) and for the symbols/graph tables.
- Naive character-window chunking loses scope, imports, and signature context. It is the single biggest quality lever and we are not cutting it.
- A plugin interface keeps language-specific quirks out of the engine. Adding language number 8 is one module, no engine change.

## Plugin interface

```python
class Language(Protocol):
    name: str                       # "fsharp", "csharp", "javascript", ...
    extensions: tuple[str, ...]     # (".fs", ".fsi", ".fsx")

    def chunk(self, path: Path, content: str) -> list[Chunk]: ...
    def symbols(self, path: Path, content: str) -> list[Symbol]: ...
    def imports(self, path: Path, content: str) -> list[Edge]: ...
```

Shared types:

```python
@dataclass
class Chunk:
    start_line: int
    end_line: int
    kind: str        # "function" | "type" | "module" | "class" | "state" | "event" | ...
    name: str | None
    scope: str | None  # enclosing scope, e.g. "MyModule.SubModule" or "default" (LSL state)
    text: str

@dataclass
class Symbol:
    name: str
    kind: str        # "def" | "ref"
    line: int

@dataclass
class Edge:
    target: str      # symbol name or external identifier
    kind: str        # "import" | "call" | "listen" | "link_message" | "http" | ...
    line: int
    meta: dict | None
```

A plugin returning empty lists is valid (e.g., LSL has no imports in the traditional sense).

## Chunk sizing guidance

- One chunk per meaningful named scope (function, type definition, class member, event handler). Smaller is fine; larger means the chunk should be split or summarized at the boundary.
- Chunks include leading docstring/comment lines belonging to the declaration.
- File-level "prelude" (imports, namespace declarations) is its own chunk of kind `module`.
- Chunks should not exceed ~200 lines; if a function is genuinely larger, the plugin emits multiple chunks with a continuation marker in `scope`.
- **Backend safety net.** The embedding backend enforces a hard per-text truncation at 1024 tokens (see [embeddings](embeddings.md), "Batching and throughput"). Chunks that exceed this cap are silently truncated at embed time — symbols, BM25 content, and offsets remain whole, but the dense vector represents only the chunk's prefix. Plugins targeting the ~200-line guidance above stay well clear of this cap; the cap exists to bound padded-attention memory for pathological inputs (e.g. minified single-line files), not as the primary sizing knob.

## Per-language plugins

### F# (`languages/fsharp.py`)

- **Parsing strategy:** regex / hand-rolled. Tree-sitter F# coverage is uneven; not worth the dependency drama.
- **Chunk on:** `let` / `let rec` at module scope, `member`, `type`, `module`, `namespace`. Computation expression definitions get their own chunk.
- **Important detail:** F# file order matters semantically (forward references are illegal). The plugin reads `.fsproj` when available and records each file's compile-order index. The shipped storage form is a `|fsproj=<N>` suffix appended to `Chunk.scope` (no new field on the `Chunk` dataclass — for a method on `Geometry.Point` listed third in `.fsproj`, the resulting scope string is `"Geometry.Point|fsproj=3"`). Consumers parsing scope strings must accept this suffix shape. `Symbol.name` is composed from the *undecorated* scope, so qualified symbol names never carry the marker — the suffix is chunk metadata, not part of symbol identity. Without a `.fsproj`, the suffix is absent and symbol resolution may be degraded (see Implications below).
- **Symbols:** module-qualified names. Discriminated union cases are emitted as separate symbols.

### C# (`languages/csharp.py`)

- **Parsing strategy:** tree-sitter via `tree-sitter-language-pack`.
- **Chunk on:** `class`, `struct`, `record`, `interface`, `enum`, methods (including local functions), top-level statements.
- **Symbols:** fully-qualified name including namespace.
- **Imports:** `using` directives → edges of kind `import`.

### JavaScript (`languages/javascript.py`)

- **Parsing strategy:** tree-sitter.
- **Chunk on:** function declarations, arrow functions assigned at module scope, class declarations and methods, exported objects.
- **Symbols:** export names; default exports recorded under a deterministic synthetic name (e.g., `default::filename`).
- **Imports:** `import`, `require()`.

### TypeScript (`languages/typescript.py`)

- **Parsing strategy:** tree-sitter (TS grammar, separate from JS).
- **Chunk on:** as JavaScript plus `interface`, `type`, `enum`, `namespace`, generic type aliases.
- **Symbols:** include type-only exports.
- **Imports:** including `import type`. Type-only imports tagged in edge meta.

### Go (`languages/golang.py`)

- **Parsing strategy:** tree-sitter.
- **Chunk on:** function declarations, methods, type declarations, top-level var/const blocks.
- **Symbols:** package-qualified names. Receiver type recorded in scope for methods.
- **Imports:** `import` blocks → edges.

### Python (`languages/python.py`)

- **Parsing strategy:** **stdlib `ast`**, not tree-sitter. The standard library parser is reliable, zero-dep, and covers everything we need.
- **Chunk on:** `def`, `async def`, `class`. Module-level statements not in a def/class form a `module_body` chunk.
- **Symbols:** dotted scope (`Class.method`, `module.func`).
- **Imports:** `import`, `from ... import ...` → edges.

### LSL (`languages/lsl.py`)

- **Parsing strategy:** regex / hand-rolled state machine. No mature tree-sitter grammar.
- **Chunk on:** **events within states** (LSL is event-driven; events are the real API). Globals and user functions are also chunks. State declarations themselves are a chunk of kind `state`.
- **Scope:** state name for events, otherwise `global`.
- **Symbols:** `llXxx` function references emitted as `ref` symbols, helps lexical search.
- **Edges:** `listen` channels, `link_message` channels, `llHTTPRequest` endpoints, `llEmail` recipients — all as edges of distinct kinds.
- **OpenSim / OSSL:** deferred to v1.x. The Phase 3 LSL plugin recognizes pure LSL only — no `osXxx` recognition in any code path. Enabling `osXxx` recognition will require a per-plugin config sub-table (e.g. `[code_index.languages.lsl]`) that does not yet exist in the schema; see [config](config.md) "Open questions" for the linked question.
- **Event-payload schema extraction is out of scope.** Attempting to infer what `link_message` integer/string parameters *mean* would require per-project conventions the engine cannot assume; the plugin emits the channel and edge kind, and leaves interpretation to consumers.

## Dispatch and registry

- Plugin discovery is by module-level export, not decorator or `register()` call. Each plugin module — built-in or extra — exposes either a top-level `LANGUAGE: Language` (single plugin) or `LANGUAGES: tuple[Language, ...]` (multiple). The registry collects these exports.
- The chunker resolves an extension to a plugin via this registry; unknown extensions are skipped silently unless `--strict` is set.
- A project's `config.toml` selects which language plugins are active; disabled languages are not even imported.

## Symbol identity

Plugins emit symbol `name` strings using their own language-idiomatic form; storage records them verbatim. The plugin contract is pure per-file — plugins receive `(path, content)` and emit data; they do not read other files. Any identity that would require filesystem traversal (Python's `__init__.py` walk, TypeScript's `tsconfig.json` path mapping) is therefore inaccessible to plugins by design and is not part of `name`. There is no engine-level normalization — no case-folding, no namespace-stripping, no language-prefixing. The `symbols` table is the global lookup; uniqueness is not enforced (two languages may legitimately share a `name`), and `--lang` is the disambiguator at query time. See [cli](cli.md) for the matching contract.

- **Case-sensitivity:** case-sensitive by default. Every MVP language (LSL included; F# included) is itself case-sensitive. A future `--ignore-case` flag is plausible but not in MVP.
- **Scope field:** a symbol's `scope` carries the enclosing context (module, class, state) when applicable. Queries that need to disambiguate two same-named symbols can additionally filter on `scope`.

### Recommended per-plugin conventions

These are conventions, not enforced rules — but consistency makes queries less surprising.

The rule across the table below: `name` carries only qualifiers the **source itself** declares — namespace, module, package, scope keywords. For languages where module identity lives on the filesystem and not in source (Python, JS, TS), the form is intra-file only. Cross-symbol disambiguation across the index is the `file_path` column's job.

- **F#:** `Module.SubModule.name`. Discriminated union cases as `Module.TypeName.CaseName`.
- **C#:** `Namespace.Type.Member`. Generic type parameters stripped from `name` but recorded in `scope` if useful.
- **Go:** `package.Name` for top-level; `package.Receiver.Method` for methods.
- **JS:** export name as written; default exports → `default::<filename-without-extension>`.
- **TS:** same as JS, plus type-only exports included.
- **Python:** intra-file dotted form. `Class.method` for methods, `Class.outer.inner` for nested functions, `Class` for class defs, bare name for module-level defs. No file-path or package-derived prefix; the file's project-relative path is recorded separately in `file_path` and is the disambiguator across the index.
- **LSL:** event handlers as `<state>.<event>`; user functions and globals by bare name.

## Implications

- The plugin interface is small and stable. Engine-wide changes do not require touching plugins.
- New language onboarding cost is bounded: one file, one test corpus, one registry entry.
- **F# is the documented exception to the "plugins are pure `(path, content) → data`" rule.** The F# plugin reads `.fsproj` to recover compile-order semantics; no other plugin performs filesystem I/O beyond its `(path, content)` inputs. The carve-out is for **chunk metadata** (the `|fsproj=<N>` suffix on `Chunk.scope` — see the F# section above), not for symbol identity: `Symbol.name` is composed from the undecorated scope and never depends on `.fsproj`. The 2026-05-19 "no I/O for symbol identity" rule (see "Symbol identity" above) and F#'s `.fsproj`-for-ordering carve-out live in different concerns and do not conflict at the symbol-name level.
- **F# discovery is hybrid.** Default `FSharpPlugin()` walks parent directories (depth-bounded) to locate a sibling or ancestor `*.fsproj`, parses it, and caches the compile order. A caller may override discovery by constructing `FSharpPlugin(fsproj_path=...)` — the plugin uses that specific `.fsproj` and skips walking; override mode also silences the per-directory "no .fsproj found" warning. Without any `.fsproj` (default mode, no override), F# indices may be missing compile-order context and the plugin warns loudly on stderr, once per starting directory; symbol resolution still produces chunks, but downstream ordering-dependent semantics may be wrong.
- **Whether to widen the Plugin Protocol with a meta channel (so callers can inject per-plugin data uniformly instead of per-plugin constructor args) is deferred** to Phase 4's call-site design. F# is the only Phase 3 consumer; the open question is recorded in [roadmap](roadmap.md) or left for the architect to lift if and when a second consumer appears.

## Open questions

None pinned here. Generated-code chunk-kind tagging and Markdown chunking were demoted to [roadmap](roadmap.md); LSL event-payload schema extraction is recorded as out-of-scope in the LSL plugin section above.

### Update 2026-05-19 — Python symbol identity: intra-file form, language-idiomatic rule made explicit

**What reversed.** The prior Python row in "Recommended per-plugin conventions" read "dotted from the module root within the project — `module.Class.method`". It is replaced with an intra-file dotted form (`Class.method`, `Class.outer.inner`, `Class`, or bare name). The cross-language rule that drives this — `name` carries only source-declared qualifiers — is now stated as a preamble to the per-plugin table.

**Why.**

- The plugin contract is `(path, content) → data` with no I/O. Computing the project-relative Python dotted name (`code_index.languages.python.PythonPlugin.chunk`) requires walking the filesystem for `__init__.py` markers and resolving `pyproject.toml` src-layout — none of which the plugin can access. The doc was asking for output the plugin cannot produce.
- LLM-search use case: agents search for `Class.method` or bare names, not project-relative dotted paths. The original prefix was noise for substring search and redundant with `file_path`.
- JS and TS are structurally identical (file = module, but module identity is filesystem-derived). Locking the rule once forestalls the same conversation in feature-003 steps 004 and 005.
- F#, C#, Go declare their module / namespace / package **in source**, so the rule keeps their existing prefixed form unchanged.

**Rejected alternatives.**

- **File stem prefix only** (`python.C.m`): adds nothing — `__init__.py` collapses to a meaningless marker, stems collide across packages, and the `--lang python` filter already does the per-language slice better.
- **Project-relative dotted path computed inside the plugin** (`code_index.languages.python.C.m`): forbidden by the plugin contract; would require parent-directory I/O.
- **Engine post-pass prepending path-derived module identity**: not rejected outright but deferred — the `file_path` column already disambiguates, so this is a future query-layer convenience, not a Phase 3 plugin concern.

**What this changed in the docs.**

- This file: rewrote the Python row in "Recommended per-plugin conventions"; added a preamble paragraph stating the underlying rule; extended "Symbol identity" with an explicit statement of the plugin no-I/O contract and its identity consequences.
- No other architecture docs required changes: `storage.md` keeps `symbols.name TEXT` format-agnostic; `cli.md` already defers to this file for symbol identity; `config.md` and `errors-and-exit-codes.md` carry no Python-specific symbol claims.
