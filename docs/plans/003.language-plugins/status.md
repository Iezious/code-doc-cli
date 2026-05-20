# Feature 003 — language plugins

| Step | File                              | Status  | Verifier | Date |
|------|-----------------------------------|---------|----------|------|
| 001  | `001.interface-and-registry.md`   | done    | PASS     | 2026-05-19 |
| 002  | `002.python-plugin.md`            | done    | PASS     | 2026-05-20 |
| 003  | `003.csharp-plugin.md`            | done    | PASS     | 2026-05-20 |
| 004  | `004.javascript-plugin.md`        | done    | PASS     | 2026-05-20 |
| 005  | `005.typescript-plugin.md`        | done    | PASS     | 2026-05-20 |
| 006  | `006.go-plugin.md`                | done    | PASS     | 2026-05-20 |
| 007  | `007.fsharp-plugin.md`            | done    | PASS     | 2026-05-20 |
| 008  | `008.lsl-plugin.md`               | done    | PASS     | 2026-05-20 |

## Files Changed

### Step 001 — Plugin interface and registry
- `src/code_index/languages/__init__.py` — package surface re-exporting protocol types, registry, helpers
- `src/code_index/languages/protocol.py` — `Chunk` / `Symbol` / `Edge` dataclasses + runtime-checkable `Language` Protocol
- `src/code_index/languages/registry.py` — `LanguageRegistry`, `load_extra_language`, `active_plugins`, built-in module list
- `src/code_index/languages/_placeholder.py` — `PlaceholderPlugin` shape consumed by step 001 plugin stubs
- `src/code_index/languages/python.py` — placeholder plugin stub (replaced by step 002)
- `src/code_index/languages/csharp.py` — placeholder plugin stub (replaced by step 003)
- `src/code_index/languages/javascript.py` — placeholder plugin stub (replaced by step 004)
- `src/code_index/languages/typescript.py` — placeholder plugin stub (replaced by step 005)
- `src/code_index/languages/golang.py` — placeholder plugin stub (replaced by step 006)
- `src/code_index/languages/fsharp.py` — placeholder plugin stub (replaced by step 007)
- `src/code_index/languages/lsl.py` — placeholder plugin stub (replaced by step 008)
- `pyproject.toml` — add `syrupy>=4` to `[project.optional-dependencies].dev`
- `tests/test_languages_registry.py` — 19 tests covering extension dispatch, runtime-checkable Protocol, extras loader, filter, end-to-end `active_plugins`
- `tests/fixtures/languages/extra/synthetic_lang.py` — minimal extra-language module exposing `LANGUAGE`
- `tests/fixtures/languages/extra/config_with_extra.toml` — fixture config listing the synthetic plugin under `extra_languages`

### Step 002 — Python plugin
- `src/code_index/languages/python.py` — replace placeholder with real `PythonPlugin` (ast-based chunker / symbols / imports) and `LANGUAGE` export
- `tests/test_python_plugin.py` — surface, snapshot, and malformed-input tests against the fixture
- `tests/fixtures/languages/python/sample.py` — canonical Python fixture exercising every chunk / symbol / import branch
- `tests/__snapshots__/test_python_plugin.ambr` — committed syrupy snapshots for chunk / symbol / import outputs

### Step 003 — C# plugin
- `src/code_index/languages/csharp.py` — replace placeholder with real `CSharpPlugin` (tree-sitter-language-pack chunker / symbols / imports) and `LANGUAGE` export
- `tests/test_csharp_plugin.py` — surface, snapshot, and malformed-input tests against the fixture
- `tests/fixtures/languages/csharp/sample.cs` — canonical C# fixture exercising every chunk kind, the documented `using` forms, and a local function nested inside a method
- `tests/__snapshots__/test_csharp_plugin.ambr` — committed syrupy snapshots for chunk / symbol / import outputs

### Step 004 — JavaScript plugin
- `src/code_index/languages/javascript.py` — replace placeholder with real `JavaScriptPlugin` (tree-sitter-language-pack chunker / symbols / imports) and `LANGUAGE` export
- `tests/test_javascript_plugin.py` — surface, snapshot, default-export synthetic-name (named + anonymous arrow), and malformed-input tests against the fixture
- `tests/fixtures/languages/javascript/sample.js` — canonical JS fixture exercising every chunk kind (function, class, class method, arrow at module scope, module), every import form (`import`, `import * as`, side-effect, `require`), a named export, and an anonymous default export
- `tests/__snapshots__/test_javascript_plugin.ambr` — committed syrupy snapshots for chunk / symbol / import outputs

### Step 005 — TypeScript plugin
- `src/code_index/languages/typescript.py` — replace placeholder with real `TypeScriptPlugin` (tree-sitter-language-pack chunker / symbols / imports, dual-grammar dispatch by extension) and `LANGUAGE` export
- `tests/test_typescript_plugin.py` — surface, snapshot, type-only-import-tagged, and malformed-input tests against the fixture
- `tests/fixtures/languages/typescript/sample.ts` — canonical TS fixture exercising every JS chunk kind plus `interface`, `type` alias, `enum`, `namespace`, generic type parameters, `import type`, namespace-nested class and function
- `tests/__snapshots__/test_typescript_plugin.ambr` — committed syrupy snapshots for chunk / symbol / import outputs

### Step 006 — Go plugin
- `src/code_index/languages/golang.py` — replace placeholder with real `GoPlugin` (tree-sitter-language-pack chunker / symbols / imports, package-qualified symbol naming, receiver-typed method scope) and `LANGUAGE` export
- `tests/test_golang_plugin.py` — surface, snapshot, method-receiver-scope, and malformed-input tests against the fixture
- `tests/fixtures/languages/golang/sample.go` — canonical Go fixture exercising the `package` clause, single + grouped imports with every alias form (named, blank, dot), top-level `const`, grouped `var (...)` block, a struct `type`, a `type` alias, a top-level `func`, methods with both pointer and value receivers, and a second free function
- `tests/__snapshots__/test_golang_plugin.ambr` — committed syrupy snapshots for chunk / symbol / import outputs

### Step 007 — F# plugin
- `src/code_index/languages/fsharp.py` — replace placeholder with real `FSharpPlugin` (hand-rolled regex / indentation-aware scanner, optional `fsproj_path` constructor arg, `.fsproj`-derived `fsproj_order` recorded as a `|fsproj=<N>` suffix on `Chunk.scope`) and `LANGUAGE` export
- `tests/test_fsharp_plugin.py` — surface, snapshot, `fsproj_order`, missing-`.fsproj` warn, DU-cases-as-symbols, malformed-input, and hybrid-discovery constructor-override tests against the fixtures
- `tests/fixtures/languages/fsharp/sample.fs` — canonical F# fixture exercising `namespace`, `module`, `open`, record `type`, discriminated-union `type` with three cases, `let` and `let rec` at module scope, a computation-expression builder `type` with a `member`, and the builder binding
- `tests/fixtures/languages/fsharp/sample.fsproj` — minimal `.fsproj` listing `sample.fs` under `<Compile Include>`
- `tests/fixtures/languages/fsharp_no_proj/sample.fs` — minimal `.fs` file in a directory without any `.fsproj`, drives the warn-and-degrade and override-silences-warning tests
- `tests/__snapshots__/test_fsharp_plugin.ambr` — committed syrupy snapshots for chunk / symbol / import outputs

### Step 008 — LSL plugin
- `src/code_index/languages/lsl.py` — replace placeholder with real `LSLPlugin` (hand-rolled comment stripper + brace-balance scanner; emits `state` / `event` / `function` / `module` chunks, `def` + `ref` symbols, and four edge kinds `listen` / `link_message` / `http` / `email` through the Protocol's `imports()` method) and `LANGUAGE` export
- `tests/test_lsl_plugin.py` — surface, snapshot, OSSL-absence, per-edge-kind, event-handler-state-scope, function-global-scope, module-chunk, ref-per-occurrence, and malformed-input tests against the fixture
- `tests/fixtures/languages/lsl/sample.lsl` — canonical LSL fixture exercising global variable declarations, a user-defined typed function, a `default` state with two event handlers, a named `state idle` with its own event, all four edge-producing `llXxx` calls, a non-edge `llSay` reference, and an `osSetSpeed` call that must be ignored
- `tests/__snapshots__/test_lsl_plugin.ambr` — committed syrupy snapshots for chunk / symbol / import outputs

## Notes & Issues

- Step 001 promoted the placeholder helper from `_PlaceholderPlugin` (inside `registry.py`, per `001.context.md`) to `PlaceholderPlugin` in a sibling `_placeholder.py` module. Pyright's `reportPrivateUsage` rejected importing a leading-underscore class across modules; moving it to a leading-underscore module preserves the "internal" signal without tripping the lint. Class shape and behavior are unchanged. Steps 002-008 simply drop the `from ._placeholder import PlaceholderPlugin` line when they replace each stub.
- `test_active_plugins_end_to_end` constructs `CodeIndexConfig` directly instead of round-tripping the fixture TOML through `load_config`. The Phase 1 loader's language-name approximation derives the name from the extras file stem (`synthetic_lang`), which does not match the plugin's actual `name` (`synthetic`); the step task file explicitly permits either approach ("load... or build a `CodeIndexConfig` directly").
- Step 002: an in-flight implementation of `PythonPlugin` and its tests/fixture already existed in the working tree. Fixed a relative-import bug in `imports()`: for `from . import sibling` the previous code emitted `target="..sibling"` (double dot) because it always inserted a `.` separator between `prefix` and `alias.name`; the corrected code only inserts the separator when a module is present, so `from . import sibling` now produces `target=".sibling"` per `002.context.md`. Snapshot regenerated via `pytest --snapshot-update`.
- Step 002: architecture doc `chunking-and-languages.md` was updated on 2026-05-19 to match the step's intra-file dotted-scope convention (`Class.method`, no module-stem prefix in `Symbol.name` or `Chunk.scope`); no contract change for this step.
- Step 003: `tree-sitter-language-pack` 1.8.x exposes the `Parser` / `Tree` / `Node` API as Rust pyclasses where every accessor is a method (`root_node()`, `start_byte()`, `start_position()`, `kind()`, ...), not a property — different from the standard `py-tree-sitter` binding's attribute surface. The plugin imports `Node` and `get_parser` from the public top-level package and treats the API method-style throughout.
- Step 003: the C# fixture deliberately mixes top-level statements with a `namespace` block in one file (illegal in production C# but accepted by the tree-sitter grammar without error). One fixture then exercises every chunk kind required by the DoD, including the `"module"` chunk for top-level statements.
- Step 003: generic type parameters are stripped from `Chunk.name` and `Symbol.name` (the C# grammar already does this for free — its `name` field is the bare identifier, with `type_parameter_list` as a separate named child). The simpler "drop generics from `scope` too" approach is taken; the snapshot pins this behavior. No generic-bearing declaration appears in the canonical fixture, but the implementation is structurally generic-agnostic.
- Step 004: per `004.context.md` the coder picks whether to always emit `"form"` in import edge `meta` or only when it is `"require"`. Chose to omit `"form"` for ESM imports and include it only for `require`, keeping ESM `meta` to the single `"names"` key — minimal, and the ESM form is otherwise unambiguous in JS. Snapshot pins this.
- Step 004: even when an `export default` wraps a named declaration (`export default function foo() {}`), only the synthetic `default::<stem>` symbol is emitted — the `foo` identifier is the function's local binding, not the export name. The function still surfaces as a `"function"` chunk under its local name in the chunk output, consistent with the C# pattern of decoupling chunk-name from export-name.
- Step 004: a top-level `lexical_declaration` is fully consumed (excluded from the `"module"` chunk) only when every declarator is either an arrow function (becomes a function chunk) or a module-scope `require(...)` call (becomes an import edge). Mixed declarations (`const a = 1, b = () => 2;`) fall through to the module chunk in full — splitting one declaration across two chunk kinds would lose the source-range invariant and isn't worth the complexity. The fixture does not exercise this corner; the rule is documented here as a guarantee.
- Step 004: re-exports (`export { a } from "mod"`, `export * from "mod"`) are not specially handled — they emit symbols for their named bindings (per the named-export branch) and no edge is recorded. The canonical fixture does not exercise re-exports; `004.context.md` explicitly leaves this as a coder's choice with the snapshot as the contract.
- Step 005: chose to emit `"type_only": True` explicitly in import-edge `meta` only when the whole statement is type-only (`import type { ... } from "..."`); the key is omitted otherwise (matching the JS plugin's pattern of omitting fields whose absence consumers treat as the default). Per-specifier type-only (`import { type X, Y } from "..."`) is intentionally not disambiguated for Phase 3 per `005.context.md`; the resulting edge omits `type_only` and lists every binding under `meta["names"]` regardless of per-specifier `type` keywords. Snapshot pins both choices.
- Step 005: top-level `namespace Foo {}` parses as `expression_statement > internal_module` (TS-grammar quirk; `export namespace Foo {}` parses as `export_statement > internal_module` instead). The plugin recognises both shapes via a helper that unwraps either wrapper to the inner `internal_module` node.
- Step 005: mirrored the JS-plugin convention for symbol emission — only `export_statement` at the relevant scope produces symbols. The fixture's `namespace Geometry` is intentionally non-exported, so neither it nor its inner `export class Point` / `export function distance` appear in `symbols()`. Exported namespaces (e.g. `export namespace Foo { export class Bar {} }`) would emit `Foo` and `Foo.Bar` via the recursive `_emit_namespace_symbols` helper; that path is structurally tested by reading the implementation but not exercised by the canonical fixture.
- Step 005: generics are stripped from `Chunk.name` / `Symbol.name` "for free" — the TS grammar's `name` field on `type_alias_declaration` / `interface_declaration` / `class_declaration` returns the bare `type_identifier`, with `type_parameters` exposed as a sibling field. Same pattern as the C# plugin (step 003).
- Step 005: namespace-nested class methods chain through dotted scope (`Geometry.Point` for the `constructor` method), implemented by `_emit_class_chunk` joining `(scope, name)` when both are present. The snapshot pins this composition.
- Step 006: only `function`, `method`, and `type` declarations emit symbols — `var` / `const` blocks are chunked as `"module"` but their individual specs do not contribute `Symbol` entries. The step DoD only specifies symbol shapes for funcs/methods (`<pkg>.Name`, `<pkg>.Recv.Method`); `006.context.md`'s "Symbol naming examples" extends this to type declarations and is silent on var/const. The snapshot pins the chosen scope.
- Step 006: the Go grammar groups `var ( ... )` / `const ( ... )` as one `var_declaration` / `const_declaration` whose body is a `*_spec_list`; the plugin treats each declaration as a single `"module"` chunk regardless of whether it is grouped. Top-level single `var x = 1` therefore also yields one `"module"` chunk per declaration, matching the context-doc's "one `"module"` chunk per declaration" rule.
- Step 006: a missing `package` clause collapses the qualifier prefix to the empty string via `_qualify`, so `Symbol.name` falls back to the bare identifier (`Frobnicator` instead of `widgets.Frobnicator`); error tolerance is implemented by this fallback plus the parser's blanket `try`/`except` returning `[]`. The malformed-input test exercises the latter; the empty-package fallback is documented but not exercised by the canonical fixture.
- Step 006: receiver type extraction strips the pointer asterisk for both `(w *Widget)` and `(w Widget)` so pointer- and value-receiver methods share the same scope (`widgets.Frobnicator`). The fixture exercises both shapes and the snapshot pins the result.
- Step 007: chose storage form A (Option A from `007.context.md`) for the per-file compile order — appended to `Chunk.scope` as a `|fsproj=<N>` suffix. A chunk at the file root with no enclosing F# scope therefore carries `scope="|fsproj=0"` rather than `None`; consumers parsing the suffix must tolerate a leading `|`. The symbol layer reads the undecorated scope (the `|fsproj=` suffix is applied only inside `_chunk_impl`), so qualified symbol names never carry the marker.
- Step 007: the indentation-aware scope stack treats `namespace` frames as "immortal" — they are never popped by the sibling-indent rule. F#'s `namespace X` has no body delimiter and applies file-scope; a subsequent `module Y` at column 0 is its child, not its sibling. The fixture's `namespace MyCorp` followed by `module Geometry =` at the same indent verifies this — symbols emerge as `MyCorp.Geometry.*`, not bare `Geometry.*`.
- Step 007: end-of-chunk is computed by "next opener whose indent is <= ours, or EOF", with trailing blank lines trimmed. As a side-effect the `namespace MyCorp` chunk ends one line before the next `module Geometry =` opener even though they share indent 0 — this is the correct F# semantic (the namespace contains the module) but is worth pinning since the scanner does not "open a namespace body" the way C-family languages do.
- Step 007: the override path (`FSharpPlugin(fsproj_path=...)`) intentionally silences the missing-`.fsproj` warning when the parsed file is outside the override's `<Compile Include>` list — the caller chose explicitly, so staying silent is the right behavior. Files not listed simply lack the `|fsproj=` suffix. The default no-arg form retains the parent-walk + warn-once-per-directory behavior from `007.context.md`.
- Step 007: `_match_opener` checks `member` before `let` defensively — `static member` would not actually match the `let` regex (no `let` keyword present), but reordering is cheaper than reasoning about every future keyword combo. The `let` regex tolerates several modifier keywords (`rec`, `mutable`, `inline`, visibility) but is silent on more exotic F# bindings; those produce no chunk rather than a malformed one, matching the "best-effort or skip" tolerance rule.
- Step 008: the four LSL-specific edge kinds (`listen` / `link_message` / `http` / `email`) flow through the Protocol's `imports()` method. The step DoD line "`imports()` returns `[]` — LSL has no imports" reads literally as "always empty", but the architecture's `Language` Protocol exposes exactly one edge-returning method, and the test list explicitly checks edge output (`test_listen_edge` etc.) against a fixture that exercises all four kinds. The interpretation taken: the DoD line refers to the LSL semantic concept of imports (`open` / `using` / `require` — none exist in LSL), not to the Protocol method's return shape; `imports()` returns the empty list precisely when no edge-producing `llXxx` call appears. The snapshot pins the four edges for the canonical fixture.
- Step 008: step DoD specifies `llMessageLinked(link, number, str, key) → target=<number-arg-text>` (the 2nd argument), but `008.context.md`'s "Edges — argument extraction" rule says all four edge-producing calls use the **first** argument verbatim and its concrete example table shows `llMessageLinked(LINK_THIS, 1, "hi", "")` → `target="LINK_THIS"` (the 1st argument). The contradiction is internal to the step; followed `context.md`'s "first argument uniformly" rule plus its concrete example, which is internally consistent across the other three calls. `test_link_message_edge` and the snapshot both pin `target="LINK_THIS"`.
- Step 008: OSSL exclusion is enforced structurally by the regex `\bll[A-Z][A-Za-z0-9]*(?=\s*\()` — the leading `ll` is mandatory and there is no companion regex for `os` prefixes. Adding OSSL is a one-line regex change but is deferred per the feature-level `outcome.md` (it needs a per-plugin config schema, which Phase 1's config does not yet expose).
- Step 008: block comments are stripped newline-preservingly even though LSL Mono itself does not support `/* ... */`. Accepting them is the kinder behaviour for tooling that pre-processes scripts; the design-doc tolerance stance covers it. Line comments and string literals are handled in the same pass via a small hand-rolled tokenizer rather than regex, so `"//"` inside a string is not treated as a comment opener.
- Step 008: event handlers are recognized by an LSL-events whitelist (`_LSL_EVENTS`). Unknown event-shaped lines (e.g. a hypothetical future event added by a viewer) are silently skipped rather than mis-chunked as an event. A user-defined function inside a state body would also be ignored — the LSL grammar disallows it, so this is the right "best-effort" choice. The whitelist is module-level and easy to extend in a future bump.

## Bug Fixes

_populated post-completion by `/bug-fixer` if needed_
