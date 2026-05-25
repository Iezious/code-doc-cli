# Fast feature 002 — follow-symlinks

| Status | Verifier | Date       |
|--------|----------|------------|
| done   | PASS     | 2026-05-25 |

## Files Changed

- `src/code_index/walker.py` — invert dir-symlink branch, thread visited-set keyed by resolved canonical path, warn-and-skip on cycle, update module and function docstrings.
- `tests/test_walker.py` — invert `test_directory_symlink_is_not_followed` into `test_directory_symlink_is_followed`, add `test_symlink_cycle_is_detected_and_skipped` and `test_directory_symlink_to_sibling_tree_is_followed`.
- `src/code_index/usage/index-build.md` — update line 69 to reflect the new follow-with-cycle-detection policy.

## Notes & Issues

- The plan refers to `docs/usage/index-build.md`; the actual user-facing doc lives at `src/code_index/usage/index-build.md` (shipped inside the package; same line content). Edited the real path.
- The visited-set is implemented as a recursion-stack (entries are popped via `try/finally` after the recursive call returns), not a global "ever visited" set. This is required for the sibling-symlink test in the plan: two directory symlinks pointing at the same real tree both resolve to the same canonical path, and a global set would silently skip the second. Only ancestors on the current call chain count as a "cycle". The plan's "skip if resolved already in visited" phrasing is preserved at the gate — the stack discipline is in addition.
- `uv run ruff format --check` reports pre-existing project-wide format drift in 42 of 67 files (including `write_log_stderr(...)` calls in `walker.py` that were already multi-line before this change, and `test_broken_symlink_warns_and_skips`'s parameter list in `test_walker.py`). My newly written lines are format-clean; I did not reformat the unrelated pre-existing drift to stay in plan scope.
