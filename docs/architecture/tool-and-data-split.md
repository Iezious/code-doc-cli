# Tool vs data split

## Decision

The **engine** is a globally installed CLI. The **index data and per-project configuration** live inside each consumed project, under `docs/.helpers/`. The engine has no global state outside its install location.

```
~/ (or wherever uv tools land)
  bin/code_index                       # global engine, on PATH
  share/code_index/                    # engine internals (Python package)

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
- **No global state leakage.** Behavior is fully determined by the project's config — no hidden `~/.code_index/` caching that affects results.
- **Indices are build artifacts.** They belong with the project but not in the project's git history.
- **Config travels with the project.** A team member who checks out the repo gets the indexing parameters without copying anything.

## Rejected alternatives

- **Per-project tool install.** Wasteful, drifts across projects, complicates upgrades.
- **Global index storage (`~/.code_index/projects/...`).** Loses portability (project move/clone breaks the link); creates implicit coupling between unrelated projects sharing the host.
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
- `config.toml` carries a **tool version pin** (`code_index.version = ">=0.3,<0.5"`).
- `meta.schema_version` inside the index records the schema the index was built with.

On every invocation, the CLI checks:
1. Engine version satisfies the project's pin → otherwise error with the required range.
2. Engine schema version matches the index's `meta.schema_version` → otherwise error and prompt to migrate or rebuild.

Loud failures, never silent drift.

When teams install the engine pinned to a git tag (e.g. `...code_index.git@v0.1.0`), the `version` field in `config.toml` can be aligned with that tag so the version pin and the installed artifact agree.

## Custom language plugins

A project may declare extra language modules:

```toml
[code_index]
extra_languages = ["./.helpers/lang_mydsl.py"]
```

These are loaded as ordinary Python modules and registered into the same plugin registry. The interface is identical to the built-ins. This keeps the engine general and lets projects with exotic languages extend without forking.

## Install workflow

### End-user install

1. `uv tool install git+https://github.com/Iezious/code_index.git` — installs the global CLI.
2. In each target project: `code_index init` to scaffold `docs/.helpers/`.
3. Tune `config.toml` per project (languages, roots, ignores, embed model).
4. `code_index index build` once, `code_index index sync` on subsequent runs.

### Engine development

1. Clone the engine repo.
2. `uv tool install --editable .` from the engine repo.

This path is for working on `code_index` itself, not for consuming projects.

## Onboarding a teammate

- They install the engine themselves via `uv tool install git+https://github.com/Iezious/code_index.git`.
- They checkout the target project; `docs/.helpers/config.toml` is already there.
- They run `code_index index build` once locally to populate the gitignored index.

There is no shared index distribution mechanism. Indices are cheap to rebuild and stale-bias is a real cost we are not paying to share them.

## Implications

- Engine and project evolve on independent schedules, gated by the version pin.
- A breaking engine change without a schema bump is a bug — the index check protects us.
- Per-project customization is bounded by what `config.toml` exposes; engine code stays free of per-project conditionals.

## Open questions

None pinned here. Private-package-index publishing and workspace-level config were demoted to [roadmap](roadmap.md).
