# Fast feature 001 — usage-subcommand: outcome

Architecture deltas implied by this feature. Populated by the planner; applied by `/architect` during finalization.

## `docs/architecture/cli.md`

- **Section:** "Subcommands" — add a new entry.
- **Intended change:** Document `code_index usage [<topic>]` between `config show` and `doctor`. Note the fixed 9-name topic catalog (`usage`, `init`, `index-build`, `index-sync`, `index-rebuild`, `search`, `symbols`, `graph`, `config-show`), the default behavior of bare `code_index usage` (returns the `USAGE.md` index), and the JSON shape `{"topic", "content", "available"}`.
- **Reason:** New subcommand is part of the stable CLI surface and must appear in the source-of-truth doc. It is also the only subcommand whose primary output is markdown content rather than structured data.

## `docs/architecture/cli.md`

- **Section:** "Discovery and config location" or a new short subsection.
- **Intended change:** Note that `usage` is the third command (alongside `--help` and `config show --no-project`) that works without a discovered `docs/.helpers/config.toml`. It is project-independent — it reads packaged resources only.
- **Reason:** The discovery rule today says "Not found → most commands error with a pointer to `code_index init`." `usage` is a documented exception and should be listed.

## `docs/architecture/errors-and-exit-codes.md`

- **Section:** "CLI scaffolding (code 1)" — extend the `cli.bad_enum` entry.
- **Intended change:** Add `code_index usage <bad>` as a second producer of `cli.bad_enum`. The `detail` payload uses `flag = "<topic>"` (Typer argument name) rather than a `--flag` name; document this in the entry so agents know to expect the topic argument name, not a long-flag string.
- **Reason:** The current entry names only `search --mode <bad>` as a producer and only contemplates `--flag`-style names. Adding a positional-argument producer is a small clarification of the contract.

## Packaging note (for the architect to decide where it lives)

- **Section:** Probably a short note in `docs/architecture/cli.md` "Implications" or a dedicated mention in a packaging-related doc if one exists.
- **Intended change:** Record that non-Python resource files inside `src/code_index/` must be force-included via `[tool.hatch.build.targets.wheel.force-include]` to guarantee wheel inclusion. Future additions of packaged resources (templates, schemas, etc.) follow the same rule.
- **Reason:** This is the first packaged non-`.py` resource in the project; a quick line prevents future contributors from assuming hatch's default behavior covers it.

## Possible gap (if applicable)

- If the coder reports that extending `tests/test_json_roundtrip_dod.py` required more than a trivial 1-2 line addition, record it here for the architect: the cross-subcommand DoD roundtrip test does not currently cover commands whose primary output is a markdown blob rather than a structured document, and may need a small fixture refactor before the `usage` command participates.

## Observations

- The cross-subcommand DoD roundtrip test extension was skipped. `tests/test_json_roundtrip_dod.py` is organized as one dedicated test function per subcommand (no parametric data list), so adding `usage` success + failure entries would exceed the "1-2 lines, matches the existing parametric pattern" gate the plan set. The new `tests/test_usage_cli.py` already covers the envelope shape via `test_usage_unknown_topic_json`. Possible impact: planner should record (in the "Possible gap" note already drafted above) that the DoD roundtrip suite would benefit from a small fixture refactor before commands whose primary output is a markdown blob are added to it; alternatively, the architect may decide to add bespoke `usage` entries directly to `test_json_roundtrip_dod.py` as part of a future fast feature.
- Hatchling 1.x with `packages = ["src/code_index"]` already includes `*.md` resources inside the package by default. The `[tool.hatch.build.targets.wheel.force-include]` rule the plan mandates therefore causes each `usage/*.md` to be written into the wheel twice and emits `UserWarning: Duplicate name:` lines from `zipfile` during `uv build --wheel`. The wheel is functional and `importlib.resources` reads the resources correctly, but the duplicates roughly double the resource payload and add build-time noise. Possible impact: the architect's packaging note in `docs/architecture/cli.md` should either (a) drop the force-include recommendation now that hatchling auto-includes package resources, or (b) reframe it as a defensive belt-and-suspenders rule and call out the duplicate-emission tradeoff explicitly.

---
Status: Applied 2026-05-22
Applied items: 4
Rejected items: 1 (DoD roundtrip test gap — YAGNI until a second markdown-content subcommand appears; the envelope shape is already covered by `test_usage_unknown_topic_json`)

Notes:
- The planner's packaging item (originally targeted at `cli.md` "Implications") was reframed per the fast-coder's build observation and landed in `architecture.md` as a new "Packaging" subsection. Hatchling auto-includes in-package resources; `force-include` for them is harmful (duplicate wheel entries). The new section records the correct rule and cites the duplicate-warning lesson from this feature.
