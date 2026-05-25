# Plan — follow symlinks (fast/002)

## Goal

Make the walker follow directory symlinks in addition to file symlinks, on Windows and Linux, with a visited-set cycle guard keyed by resolved canonical path.

## Files to create or modify

- `src/code_index/walker.py` — invert the dir-symlink branch, thread a visited set through `_walk_dir`, warn-and-skip on cycle, update module and function docstrings.
- `tests/test_walker.py` — invert the existing dir-symlink test, add a cycle-detection test, add a cross-directory chain test.
- `docs/usage/index-build.md` — update the user-facing symlink note (line 69) to reflect the new policy.

(Architecture doc changes for `docs/architecture/architecture.md` are recorded in `outcome.md` and applied by the architect during finalization. The coder does not edit `docs/architecture/`.)

## Signatures

`_walk_dir` gains an explicit `visited` parameter; the rest of its signature is unchanged. New shape:

```python
def _walk_dir(
    current: Path,
    root: Path,
    registry: LanguageRegistry,
    default_spec: PathSpec,
    ignores_spec: PathSpec,
    gitignore_specs: list[tuple[Path, PathSpec]],
    gitignore_active: bool,
    visited: set[Path],
) -> Iterator[WalkedFile]: ...
```

The initial call inside `walk()` seeds `visited = {root_abs}`. Before recursing into any directory (real or symlinked), `_walk_dir` resolves the entry's canonical path, checks membership in `visited`, warns on stderr and skips on hit, otherwise adds it and recurses.

`walk()` public signature is unchanged. `WalkedFile` shape is unchanged.

## Tests

All in `tests/test_walker.py`, all gated by the existing `_can_symlink(tmp_path)` probe.

- Invert `test_directory_symlink_is_not_followed` -> `test_directory_symlink_is_followed`:
  - Create `real_dir/inside.py` and `link_dir -> real_dir` via `os.symlink(real_dir, link_dir, target_is_directory=True)`.
  - Assert both `real_dir/inside.py` and `link_dir/inside.py` are yielded with their respective walked `rel_path` values.
- New `test_symlink_cycle_is_detected_and_skipped`:
  - Create `a/file.py` and `a/loop -> ..` (or `a/loop -> a`) so descending into `loop` would revisit `a`.
  - Run `walk()` and confirm it terminates, that `a/file.py` is yielded exactly once, and that stderr contains `walker: skipping symlink cycle`.
- New `test_directory_symlink_to_sibling_tree_is_followed`:
  - Layout: `pkg_a/mod.py`, `pkg_b/link -> ../pkg_a` (directory symlink).
  - Assert both `pkg_a/mod.py` and `pkg_b/link/mod.py` are yielded, no duplicates, no cycle warning emitted.

Keep `test_file_symlink_is_followed` and `test_broken_symlink_warns_and_skips` unchanged.

## Definition of done

- `_walk_dir` accepts and threads a `visited: set[Path]` parameter; `walk()` seeds it with the resolved root path.
- Directory symlinks are followed: the dir-symlink early-return at the current `walker.py:212-214` is removed, and the `is_dir` computation at `walker.py:222` no longer excludes symlinks.
- Before recursing into any directory, the walker calls `Path.resolve()` on the entry and skips with a stderr warning if the resolved path is already in `visited`.
- The cycle-skip warning is emitted to stderr via `write_log_stderr` in the format `walker: skipping symlink cycle at <path>`.
- Module docstring (`walker.py:1-15`) and `walk()`/`_walk_dir` docstrings no longer say directory symlinks are skipped; they describe the new follow-with-cycle-detection behavior.
- `tests/test_walker.py` contains the inverted dir-symlink test and the two new tests; all three use the `_can_symlink` skip pattern. `test_file_symlink_is_followed` and `test_broken_symlink_warns_and_skips` still pass without changes.
- `docs/usage/index-build.md` line 69 no longer claims dir symlinks are not followed; it states the new policy and mentions cycle detection.
- `uv run pytest` passes on the developer's machine.
- `uv run ruff check`, `uv run ruff format --check`, and `uv run pyright` pass.
- No new config keys, no new CLI flags, no platform-conditional branches in `walker.py`.

## Out of scope

- Any user-controlled toggle (config key, CLI flag, env var) for symlink-following behavior.
- Changes to `WalkedFile`, `rel_path` semantics, or downstream consumers of the walker.
- Inode/device-based loop detection (we use resolved canonical path).
- Changes to broken-symlink, max-file-size, binary-detection, or encoding handling.
- Editing `docs/architecture/architecture.md` directly — that delta is recorded in `outcome.md` for the architect.
