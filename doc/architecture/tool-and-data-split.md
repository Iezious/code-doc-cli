# Tool vs data split

## Decision

The **engine** is a globally installed CLI. The **index data and per-project configuration** live inside each consumed project, under `docs/.helpers/`. The engine has no global state outside its install location.

```
~/ (or wherever uv tools land)
  bin/codedoc                          # global engine, on PATH
  share/codedoc/                       # engine internals (Python package)

<project>/
  docs/
    .helpers/
      config.toml                      # per-project config, committed
      index.sqlite                     # per-project index, gitignored
      .gitignore                       # ignores the index file
    architecture/                      # human-facing docs (output)
    ...
```

## Rationale

- **Reuse without coupling.** One install serves every project. Engine improvements land everywhere on upgrade; per-project tuning stays local.
- **No global state leakage.** Behavior is fully determined by the project's config — no hidden `~/.codedoc/` caching that affects results.
- **Indices are build artifacts.** They belong with the project but not in the project's git history.
- **Config travels with the project.** A team member who checks out the repo gets the indexing parameters without copying anything.

## Rejected alternatives

- **Per-project tool install.** Wasteful, drifts across projects, complicates upgrades.
- **Global index storage (`~/.codedoc/projects/...`).** Loses portability (project move/clone breaks the link); creates implicit coupling between unrelated projects sharing the host.
- **No config, all flags.** Forces every CLI invocation to repeat language list, roots, embedding choice — fragile and verbose for agents.

## What lives where

| Concern | Location | Committed? |
|---|---|---|
| CLI binary + engine code | global install | n/a |
| Language plugins (built-in) | global install | n/a |
| Project config (`config.toml`) | `docs/.helpers/` | yes |
| Index file (`index.sqlite`) | `docs/.helpers/` | no (gitignored) |
| Custom language plugins | project (path referenced from config) | yes |
| Generated docs (architecture, per-project, cross-language) | `docs/` (outside `.helpers/`) | yes |

## Versioning across the split

- `pyproject.toml` carries the engine version.
- `config.toml` carries a **tool version pin** (`codedoc.version = ">=0.3,<0.5"`).
- `meta.schema_version` inside the index records the schema the index was built with.

On every invocation, the CLI checks:
1. Engine version satisfies the project's pin → otherwise error with the required range.
2. Engine schema version matches the index's `meta.schema_version` → otherwise error and prompt to migrate or rebuild.

Loud failures, never silent drift.

## Custom language plugins

A project may declare extra language modules:

```toml
[codedoc]
extra_languages = ["./.helpers/lang_mydsl.py"]
```

These are loaded as ordinary Python modules and registered into the same plugin registry. The interface is identical to the built-ins. This keeps the engine general and lets projects with exotic languages extend without forking.

## Install workflow

1. Clone or check out the engine repo.
2. `uv tool install --editable .` from the engine repo.
3. In each target project: `codedoc init` to scaffold `docs/.helpers/`.
4. Tune `config.toml` per project (languages, roots, ignores, embed model).
5. `codedoc index build` once, `codedoc index sync` on subsequent runs.

## Onboarding a teammate

- They install the engine themselves (editable from a clone, or eventually `uv tool install` from a private package index).
- They checkout the target project; `docs/.helpers/config.toml` is already there.
- They run `codedoc index build` once locally to populate the gitignored index.

There is no shared index distribution mechanism. Indices are cheap to rebuild and stale-bias is a real cost we are not paying to share them.

## Implications

- Engine and project evolve on independent schedules, gated by the version pin.
- A breaking engine change without a schema bump is a bug — the index check protects us.
- Per-project customization is bounded by what `config.toml` exposes; engine code stays free of per-project conditionals.

## Open questions

- Whether to publish the engine to a private package index. Defaults to editable-install for now; revisit when more than one consumer needs it.
- Whether to support a workspace-level config (e.g., `_Utils/codedoc.workspace.toml`) that defaults values across sibling projects. Plausible; deferred until a clear need shows up.
