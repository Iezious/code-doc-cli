# code_index — usage reference for Claude agents

`code_index` is a CLI that builds a per-project SQLite index of a polyglot codebase (F#, C#, JavaScript, TypeScript, Go, Python, LSL) and exposes hybrid BM25 + dense retrieval. You invoke it over Bash to fetch chunks, symbols, and dep edges instead of re-reading source files on every doc pass.

## When to use it

- "Find code about X" — `code_index search "X"`.
- "Where is symbol Y defined / referenced?" — `code_index symbols defs|refs Y`.
- "What calls into Z?" / "What does file W import?" — `code_index graph callers|deps`.
- "What's in the resolved config / index meta?" — `code_index config show`.
- Index doesn't exist yet — `code_index init` then `code_index index build`.
- Files changed on disk — `code_index index sync`.
- Embedding model changed — `code_index index rebuild --yes`.

## Lifecycle

```
init  ->  index build  ->  (use: search / symbols / graph / config show)
                       ->  index sync (incremental, after edits)
                       ->  index rebuild --yes (full, after model change)
```

`init` writes `docs/.helpers/config.toml` and `.gitignore`. `index build` creates `docs/.helpers/index.sqlite`. Once built, `search`, `symbols`, `graph`, and `config show` work read-only against it. `index sync` updates the index after edits (mtime+size based, no git dependency). `index rebuild --yes` drops and rebuilds (required after embedding model changes).

## Universal flags

| Flag | Effect |
|---|---|
| `--config <path>` | Override config discovery; load this TOML file. |
| `--format text\|json` | Output mode. `json` is the agent-friendly path. Default `text`. |
| `--verbose` | Adds timings and candidate-pool sizes on stderr. |
| `--quiet` | Suppress stderr progress lines (does not change stdout shape). |

Under `--format json`, results go on stdout as one JSON document and failures go on stdout as one error envelope. Under `--format text`, results go on stdout in human form and failures go on stderr as plain text.

## Output streams

- **stdout** — command results only. Under `--format json`, exactly one JSON document per invocation (success or error envelope).
- **stderr** — human-readable logs, warnings, progress. Never carries command results.

## Error envelope

Every failure under `--format json` emits exactly:

```json
{
  "error": {
    "code": 0,
    "kind": "category.subcategory",
    "message": "<string>",
    "detail": {}
  }
}
```

`error.code` mirrors the process exit code. `kind` is the stable dispatch key — branch on this. `message` is human-readable; do not regex-match it. `detail` is freeform per `kind`; safe to ignore if you do not recognize the `kind`.

## Exit codes

| Code | Category | Common kinds |
|---|---|---|
| 0 | success | (zero results is not a failure) |
| 1 | usage | `usage.confirmation_required`, `cli.bad_enum`, `cli.not_implemented` |
| 2 | config | `config.parse_error`, `config.bad_enum`, `config.version_mismatch`, `config.bad_path`, `config.unknown_language` |
| 10 | index/schema | `index.schema_mismatch`, `index.unreadable`, `index.vec_extension_unavailable`, `index.fts5_unavailable` |
| 11 | index/model | `index.embed_model_mismatch`, `index.embed_dim_mismatch` |
| 12 | index/missing | `index.missing` |
| 20 | backend | `backend.model_download_failed`, `backend.encode_failed` |
| 21, 22 | backend (reserved) | API auth, rate-limit — no MVP producer |
| 30 | parsing (strict mode only) | `parsing.plugin_error` |
| 40, 41 | IO | `io.permission_denied`, `io.decode_error`, `io.oversize` |
| 99 | unknown | `unknown` — indicates a bug |

Codes within a decade leave room for additive kinds. Always dispatch on `kind`, never on `message`.

## Subcommands

| Subcommand | Purpose | Detail |
|---|---|---|
| `init` | Scaffold `docs/.helpers/config.toml` + `.gitignore`. | [docs/usage/init.md](docs/usage/init.md) |
| `index build` | Full build of the SQLite index from the configured roots. | [docs/usage/index-build.md](docs/usage/index-build.md) |
| `index sync` | Incremental update via mtime + size. | [docs/usage/index-sync.md](docs/usage/index-sync.md) |
| `index rebuild` | Drop and rebuild; required after embedding model changes. | [docs/usage/index-rebuild.md](docs/usage/index-rebuild.md) |
| `search` | Hybrid BM25 + dense retrieval over chunks. | [docs/usage/search.md](docs/usage/search.md) |
| `symbols defs\|refs` | Symbol lookup over the stored symbols table. | [docs/usage/symbols.md](docs/usage/symbols.md) |
| `graph callers\|deps` | Edges lookup: who calls X / what does file Y depend on. | [docs/usage/graph.md](docs/usage/graph.md) |
| `config show` | Print resolved config + index meta. Diagnostic; never gates on drift. | [docs/usage/config-show.md](docs/usage/config-show.md) |

## Common recovery patterns

- **`index.missing` (12)** — run `code_index init` (if no config) then `code_index index build`.
- **`index.schema_mismatch` (10)** — engine was upgraded; run `code_index index rebuild --yes`.
- **`index.embed_model_mismatch` / `index.embed_dim_mismatch` (11)** — model changed; run `code_index index rebuild --yes`.
- **`backend.model_download_failed` (20)** — network or disk issue on first run; retry, or check `embed_model` in config.
- **`usage.confirmation_required` (1)** — re-run with `--yes`.
- **`cli.bad_enum` (1)** — check `detail.expected` for the allowed values.
- **`config.*` (2)** — open `docs/.helpers/config.toml` and fix; see `docs/architecture/config.md`.

When in doubt about index state, run `code_index config show --format json` — it never raises on drift and reports both configured and stored values.

## Out of scope

- No daemon, no server, no live file watching.
- No cross-project federated search; each project has its own index.
- No LSP / code-intelligence platform; symbol queries are pure index lookups.
- No automatic re-embedding when the model changes — run `index rebuild --yes`.
- No git dependency for sync; mtime + size only.

## Languages

F#, C#, JavaScript, TypeScript, Go, Python, LSL. Add a language via `[code_index] extra_languages` (path to a Python module exposing `LANGUAGE` or `LANGUAGES`). Per-language symbol-name conventions live in `docs/architecture/chunking-and-languages.md`.

## See also

- `docs/architecture/` — design rationale (read when behavior surprises you).
- `docs/architecture/cli.md` — authoritative CLI contract.
- `docs/architecture/errors-and-exit-codes.md` — full enumerated failure surface.
- `CLAUDE.md` (root) — build/test/typecheck commands when working on `code_index` itself.
