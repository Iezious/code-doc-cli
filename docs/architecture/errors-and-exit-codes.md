# Errors and exit codes

## Decision

Exit codes are part of the CLI contract and are stable across minor versions. They are how agents calling `code_index` over Bash discriminate failure kinds programmatically.

- **stderr** carries the human-readable failure message (one line summary, optional detail lines).
- **stdout** stays empty on failure for human-format callers.
- **`--format json` callers** additionally get a structured error envelope on stdout, so a single JSON read covers both success and failure shapes.

`code_index doctor` is **not in MVP** (see [mvp-scope](mvp-scope.md), deferred to v1.1). Until it ships, each subcommand emits its own categorized failure inline using the codes and `kind` strings defined here.

## Rationale

- Agents need to react differently to "config is broken" vs "model is wrong" vs "the API is down." A single non-zero exit code is not enough information.
- Numeric categories with **gaps** (10, 11, 12 in one band; 20, 21, 22 in another) leave room for adding new failures in a category without renumbering.
- A stable `kind` dotted string in the JSON envelope outlasts the numeric code — minor versions can add new kinds within an existing category without breaking older agents that only key on the category.
- Pinning the contract now, before `doctor` exists, means `doctor` can be built on top of the same surface rather than re-deriving it.

## Rejected alternatives

- **One generic non-zero code.** Agents would have to grep stderr to dispatch. Brittle and locale-sensitive.
- **HTTP-style three-digit codes.** Overkill for a CLI; exit codes are conventionally <128.
- **JSON-only error reporting.** Breaks human use of the tool; stderr must remain readable.

## Exit code table

| Code | Category | Meaning |
|---|---|---|
| `0` | success | Command completed; zero results is not a failure. |
| `1` | usage | Argument parsing or usage error. |
| `2` | config | Malformed TOML, schema mismatch, missing required key, version-pin unsatisfied. |
| `10` | index/schema | `meta.schema_version` mismatch with the running engine. |
| `11` | index/model | Stored `embed_dim` or `embed_model` does not match the configured backend. |
| `12` | index/missing | No `docs/.helpers/` discovered when one was required. |
| `20` | backend | Generic embedding backend failure (model download failed, encode crashed). |
| `21` | backend/auth | Reserved for future API-backend authentication failures (e.g., missing or rejected credentials). No producer in MVP. |
| `22` | backend/rate-limit | Reserved for future API-backend rate-limit failures (e.g., HTTP 429 after retries exhausted). No producer in MVP. |
| `30` | parsing/plugin | A language plugin raised on a file. In default mode the file is skipped and the command still succeeds; this code is emitted only under `--strict`. |
| `40` | io | Read permission denied, or encoding decode failure with no fallback. |
| `41` | io/oversize | File exceeds the max-file-size limit, in `--strict` mode. |
| `99` | unknown | Any unhandled exception. Indicates a bug. |

Code numbers in each category are spaced so that new failure kinds can be inserted without renumbering existing ones. New categories should pick the next unused decade.

## JSON error envelope

Under `--format json`, failures are written to stdout as:

```json
{
  "error": {
    "code": 2,
    "kind": "config.version_mismatch",
    "message": "engine 0.5.1 does not satisfy pin '>=0.3,<0.5' in docs/.helpers/config.toml",
    "detail": {
      "pin": ">=0.3,<0.5",
      "engine_version": "0.5.1"
    }
  }
}
```

- `code` mirrors the process exit code.
- `kind` is a stable dotted string of the form `category.subcategory`. Once published, a `kind` is not renamed within a major version.
- `message` is a single-line human summary; the same text (possibly expanded) is on stderr.
- `detail` is freeform per `kind`. Agents that recognize the `kind` may read it; others ignore it safely.

## Enumerated failure surface

Failures below are grouped by category. Each entry names the failure mode, the exit code, and the `kind` string. The list is the **MVP contract**; new entries can be added in minor versions, existing entries do not change `kind` or `code`.

### CLI scaffolding (code 1)

- Unimplemented subcommand stub → `cli.not_implemented` (code 1). The `detail` payload includes `subcommand` (the dotted invocation, e.g. `"index build"`) and `phase` (the MVP phase number that lands the real implementation), so agents can dispatch on either.
- The embeddings factory raises `cli.not_implemented` when `embed_backend = "voyage"`, until Phase 7 lands the real Voyage backend. The `detail` payload uses the same `subcommand`/`phase` keys for consistency, though `subcommand` here names the consuming surface (`"embeddings.from_config"`) rather than a CLI subcommand.

These entries are **transient**: each row is removed from this surface as Phases 4, 5, and 6 implement the corresponding subcommand. Once the MVP is complete, only the embeddings factory's voyage stub (see [embeddings](embeddings.md)) still raises this kind; that stub is itself removed when Phase 7 lands the Voyage backend.

### Config (code 2)

- Malformed TOML → `config.parse_error`.
- Missing required key (`version`) → `config.missing_key`.
- Version pin unsatisfied by running engine → `config.version_mismatch`.
- Unknown key under `[code_index]` → **warning only, exit 0**, surfaced on stderr.
- `embed_backend` not in allowed values → `config.bad_enum`.
- `embed_model` incompatible with selected backend → `config.model_backend_mismatch`.
- `roots` path missing or unresolvable → `config.bad_path`.
- `extra_languages` path missing or unreadable → `config.bad_path`.
- `languages` references a name not registered → `config.unknown_language`.

Both `config.bad_path` and `config.unknown_language` are also emitted by the language registry's `load_extra_language` at module-load time — `config.bad_path` when an `extra_languages` path cannot be loaded by `importlib` (race condition between config validation and load, or in-test direct invocation), and `config.unknown_language` when a loaded module exposes neither `LANGUAGE` nor `LANGUAGES`. The `kind` surface is intentionally uniform: an agent observing either kind treats config-validator failures and loader failures as the same class of failure mode.

See [config](config.md) for the schema these checks enforce.

### Index/storage (codes 10, 12)

- `sqlite-vec` extension fails to load → `index.vec_extension_unavailable` (code 10).
- FTS5 unavailable in the linked SQLite → `index.fts5_unavailable` (code 10).
- `meta.schema_version` mismatch with engine's expected version → `index.schema_mismatch` (code 10).
- Index file missing where one is required → `index.missing` (code 12).
- Index file present but unreadable (corruption, permission) → `index.unreadable` (code 10).

See [storage](storage.md) for schema versioning and the loud-failure stance.

### Index/model (code 11)

- Stored `meta.embed_dim` differs from the active backend's reported dim → `index.embed_dim_mismatch`. Engine refuses queries and prompts for `code_index index rebuild`.
- Stored `meta.embed_model` differs from `config.embed_model` → `index.embed_model_mismatch`. Same disposition.

See [embeddings](embeddings.md) and [storage](storage.md).

### Embedding backend (codes 20, 21, 22)

- fastembed model download failed → `backend.model_download_failed` (code 20).
- Backend `encode` raised → `backend.encode_failed` (code 20).
- Reserved for future API-backend authentication failures → `backend.auth_failed` (code 21). MVP has no producer for this kind; the contract is reserved so future paid backends can adopt this code without renumbering.
- Reserved for future API-backend rate-limit failures → `backend.rate_limited` (code 22). MVP has no producer for this kind; the contract is reserved so future paid backends can adopt this code without renumbering.

See [embeddings](embeddings.md) for backend behavior.

### Parsing (code 30)

- Language plugin raised on a file → **skip + warn on stderr** in default mode; under `--strict`, exit `30` with `kind = "parsing.plugin_error"`. `detail` includes the offending path and the plugin name.
- Missing `.fsproj` on an F# root → **warn loud, exit 0**. F# scope resolution may be degraded; this is documented behavior, not a failure. See [chunking-and-languages](chunking-and-languages.md).

### IO (codes 40, 41)

- Read permission denied on a file → `io.permission_denied` (code 40).
- Non-UTF-8 file with no fallback decoder configured → `io.decode_error` (code 40).
- File exceeds max-file-size limit → **skip + warn** in default mode; under `--strict`, exit `41` with `kind = "io.oversize"`.

### Unknown (code 99)

- Any exception not mapped by a subcommand's boundary handler → `kind = "unknown"` (code 99). The catch-all kind is `"unknown"`, not `"unknown.exception"` — the dotted-category convention is relaxed here because the kind has no subcategories. `detail` is omitted (the failure is by definition not categorized). Code 99 indicates a bug; it must never be relied on as a normal failure path.

## Default vs `--strict` mode

For parsing and IO categories, default behavior is **skip the offending file, warn on stderr, continue, exit 0**. `--strict` upgrades the skip into a failure with the documented code. Strict mode is intended for CI gates; default mode is intended for interactive and pipeline use, where one bad file should not block an index build.

## Cross-references

- The `--format json` envelope on success and the per-subcommand JSON shapes: [cli](cli.md).
- Schema-version and model-mismatch checks that raise codes `10` and `11`: [storage](storage.md).
- Config validation rules that raise code `2`: [config](config.md).
- The deferral of `code_index doctor` and the rationale for waiting on the inline-error surface to settle: [mvp-scope](mvp-scope.md).

## Implications

- Adding a new failure mode is additive — new `kind`, new entry on the table, possibly a new exit code in the relevant decade. No existing agent breaks.
- Renaming a `kind` is a major-version break and should be avoided.
- Because `--format json` writes the error envelope to stdout, JSON-mode callers should always parse stdout first and only fall back to stderr text on a parse failure.
- The contract intentionally does not promise message text stability — only `code` and `kind`. Agents must not regex-match `message`.

## Open questions

- Whether `cli.not_implemented` should be renamed (e.g. `feature.not_implemented`) or split into surface-specific kinds (`cli.not_implemented` + `backend.not_implemented`) before Phase 7. The kind was introduced as CLI-only in Phase 1; Phase 2 added a second consumer (the embeddings factory's voyage stub) outside the CLI surface, making the current name a slight category abuse. The rename, if it happens, must land before any further consumers are added. Defer the call to Phase 7's planning, when the Voyage backend either obsoletes the stub or motivates `backend.not_implemented`.
