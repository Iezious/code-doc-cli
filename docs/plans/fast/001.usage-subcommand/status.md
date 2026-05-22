# Fast feature 001 — usage-subcommand

| Status | Verifier | Date       |
|--------|----------|------------|
| done   | PASS     | 2026-05-22 |

## Files Changed

- `src/code_index/usage/USAGE.md` — moved from repo-root `USAGE.md`; sibling links rewritten, architecture refs prefixed `../../../`.
- `src/code_index/usage/init.md` — moved from `docs/usage/init.md`; architecture ref rewritten.
- `src/code_index/usage/index-build.md` — moved from `docs/usage/index-build.md`; no link rewrites needed.
- `src/code_index/usage/index-sync.md` — moved from `docs/usage/index-sync.md`; no link rewrites needed.
- `src/code_index/usage/index-rebuild.md` — moved from `docs/usage/index-rebuild.md`; no link rewrites needed.
- `src/code_index/usage/search.md` — moved from `docs/usage/search.md`; no link rewrites needed.
- `src/code_index/usage/symbols.md` — moved from `docs/usage/symbols.md`; architecture ref rewritten.
- `src/code_index/usage/graph.md` — moved from `docs/usage/graph.md`; no link rewrites needed.
- `src/code_index/usage/config-show.md` — moved from `docs/usage/config-show.md`; no link rewrites needed.
- `USAGE.md` — new thin pointer at repo root replacing the moved file.
- `src/code_index/cli.py` — added `USAGE_TOPICS` catalog, `_load_usage_topic` helper, and `@app.command("usage")` implementing text/JSON output with `cli.bad_enum` failure path.
- `pyproject.toml` — bumped version to `0.2.0`; added `[tool.hatch.build.targets.wheel.force-include]` mapping `src/code_index/usage` to `code_index/usage`.
- `tests/test_usage_cli.py` — new; 16 cases covering no-arg / per-topic text + json success, unknown-topic json envelope, unknown-topic text stderr summary, and packaged-resource readability.

## Bug Fixes

_populated by fast-fixer if a post-delivery bug fix lands here_

## Notes & Issues

- `tests/test_json_roundtrip_dod.py` extension was skipped: the file is organized into one dedicated test function per subcommand, not a parametric data list, so adding entries would exceed the "1-2 lines, matches the existing parametric pattern" gate the plan set. The DoD envelope shape for `usage` is already exercised by `test_usage_unknown_topic_json` in the new test module. Recorded in `outcome.md` per plan.
- `uv build --wheel` succeeds and the wheel ships `code_index/usage/*.md`, but hatchling currently picks up `.md` resources via the `packages = ["src/code_index"]` directive *as well as* the explicit `force-include` rule the plan mandates, producing duplicate entries in the built wheel and `UserWarning: Duplicate name:` lines from `zipfile`. The wheel is functional; this is a packaging hygiene observation surfaced in `outcome.md`.
