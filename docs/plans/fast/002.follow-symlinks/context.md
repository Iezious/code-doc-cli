# Fast feature 002 — follow symlinks

## Goal in one paragraph

Reverse the walker's symlink policy so that directory symlinks are followed in addition to file symlinks, on both Windows and Linux, with cycle detection added because we can no longer rely on "we skip dir symlinks outright" as the loop guard. The change is small and self-contained: one branch in `_walk_dir`, a visited-set threaded through recursion, and the existing test that asserted the old behavior is inverted plus two new tests are added.

## Scope

In scope:

- `src/code_index/walker.py` — invert the dir-symlink branch, thread a visited set keyed by resolved canonical path, warn-and-skip on cycle.
- `tests/test_walker.py` — invert one existing test, add a cycle-detection test, and add a cross-directory chain test.
- `docs/usage/index-build.md` — update the user-facing note that currently says directory symlinks are not followed.
- `docs/architecture/architecture.md` — deltas recorded in `outcome.md` for the architect to apply at finalization (not edited by the coder).

Out of scope:

- No new config key, no new CLI flag.
- No change to `WalkedFile` shape or `rel_path` semantics.
- No change to file-symlink handling beyond what falls out of the visited-set threading.
- No change to broken-symlink behavior.

## User-confirmed decisions (apply as-is)

1. **Configuration.** Unconditional. Always follow file and directory symlinks. No new config key, no new CLI flag.
2. **Cycle policy.** Visited-set keyed by resolved canonical path (`Path.resolve()`). On revisit, warn on stderr (format: `walker: skipping symlink cycle at <path>`) and skip. Consistent with broken-symlink behavior. Cross-platform via Python stdlib.
3. **`rel_path` convention.** Unchanged. `rel_path` remains relative to the link as walked, not the resolved target. Matches existing file-symlink behavior at `walker.py:89-90`.
4. **Out-of-root symlinks.** Followed. Symlinks resolve wherever they point; the visited-set handles loops.

## Architecture link

The decision being reversed is in [`../../../architecture/architecture.md`](../../../architecture/architecture.md) under "Symlink policy" (lines 96-101) and the matching "Rejected alternatives" bullet (line 106). The new wording is staged in `outcome.md`.

## Harvest pointers

- Walker entry point: `src/code_index/walker.py` `walk()` line 113, recursion `_walk_dir()` line 155.
- Current symlink branch: `src/code_index/walker.py:196-217`.
- Dir gate that needs updating: `src/code_index/walker.py:222` — `is_dir = entry.is_dir() and not is_symlink`.
- Recursion call site: `src/code_index/walker.py:236-245`.
- Root resolved at: `src/code_index/walker.py:128` — `root_abs = Path(root).resolve()`.
- Initial `_walk_dir` call: `src/code_index/walker.py:139-147` (visited set must be seeded here with `root_abs`).
- Docstrings restating old policy: `src/code_index/walker.py:1-15` and `113-127`.
- `WalkedFile` definition: `src/code_index/walker.py:85-105` (no shape change).
- Tests file: `tests/test_walker.py`.
  - Skip helper: `_can_symlink(tmp_path)` lines 58-75 (in-test skip, not `pytest.mark.skipif`).
  - Keep as-is: `test_file_symlink_is_followed` (311-324) and `test_broken_symlink_warns_and_skips` (343-359).
  - Invert: `test_directory_symlink_is_not_followed` (327-340) becomes `test_directory_symlink_is_followed`.
  - On Windows, `os.symlink(target, link, target_is_directory=True)` is required for directory symlinks.

## Constraints

- Cross-platform: must work on both Windows (NTFS reparse points) and POSIX. The walker has no platform branching today and should not gain any; `Path.resolve()` / `Path.is_symlink()` / `Path.is_dir()` are sufficient.
- Cycle test must use the `_can_symlink` probe-and-skip pattern so it silently no-ops on Windows boxes without symlink privilege.
- Stderr warning format for cycles: `walker: skipping symlink cycle at <path>` — consistent with the existing `walker: skipping broken symlink <path>` style.

## Build & test commands

- Tests: `uv run pytest`
- Lint: `uv run ruff check`
- Format: `uv run ruff format`
- Typecheck: `uv run pyright`
