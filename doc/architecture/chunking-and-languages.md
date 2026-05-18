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

## Per-language plugins

### F# (`languages/fsharp.py`)

- **Parsing strategy:** regex / hand-rolled. Tree-sitter F# coverage is uneven; not worth the dependency drama.
- **Chunk on:** `let` / `let rec` at module scope, `member`, `type`, `module`, `namespace`. Computation expression definitions get their own chunk.
- **Important detail:** F# file order matters semantically (forward references are illegal). Plugin reads `.fsproj` when available and records each file's position; this becomes `meta.fsproj_order` per chunk. Without it, symbol resolution can be wrong.
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
- **OpenSim / OSSL:** an opt-in flag in plugin config enables `osXxx` recognition. Default is pure LSL.
- **Event-payload schema extraction is out of scope.** Attempting to infer what `link_message` integer/string parameters *mean* would require per-project conventions the engine cannot assume; the plugin emits the channel and edge kind, and leaves interpretation to consumers.

## Dispatch and registry

- Plugins register themselves by extension at import time.
- The chunker resolves an extension to a plugin via a static registry; unknown extensions are skipped silently unless `--strict` is set.
- A project's `config.toml` selects which language plugins are active; disabled languages are not even imported.

## Symbol identity

Plugins emit symbol `name` strings using their own language-idiomatic form; storage records them verbatim. There is no engine-level normalization — no case-folding, no namespace-stripping, no language-prefixing. The `symbols` table is the global lookup; uniqueness is not enforced (two languages may legitimately share a `name`), and `--lang` is the disambiguator at query time. See [cli](cli.md) for the matching contract.

- **Case-sensitivity:** case-sensitive by default. Every MVP language (LSL included; F# included) is itself case-sensitive. A future `--ignore-case` flag is plausible but not in MVP.
- **Scope field:** a symbol's `scope` carries the enclosing context (module, class, state) when applicable. Queries that need to disambiguate two same-named symbols can additionally filter on `scope`.

### Recommended per-plugin conventions

These are conventions, not enforced rules — but consistency makes queries less surprising.

- **F#:** `Module.SubModule.name`. Discriminated union cases as `Module.TypeName.CaseName`.
- **C#:** `Namespace.Type.Member`. Generic type parameters stripped from `name` but recorded in `scope` if useful.
- **Go:** `package.Name` for top-level; `package.Receiver.Method` for methods.
- **JS:** export name as written; default exports → `default::<filename-without-extension>`.
- **TS:** same as JS, plus type-only exports included.
- **Python:** dotted from the module root within the project — `module.Class.method`.
- **LSL:** event handlers as `<state>.<event>`; user functions and globals by bare name.

## Implications

- The plugin interface is small and stable. Engine-wide changes do not require touching plugins.
- New language onboarding cost is bounded: one file, one test corpus, one registry entry.
- F# correctness depends on reading `.fsproj`. Without it, F# indices may be missing scope context. The plugin should warn loudly when no `.fsproj` is found in the root.

## Open questions

None pinned here. Generated-code chunk-kind tagging and Markdown chunking were demoted to [roadmap](roadmap.md); LSL event-payload schema extraction is recorded as out-of-scope in the LSL plugin section above.
