# Outcome — fast/002.follow-symlinks

Architecture doc deltas the architect applies during finalization. The coder does not edit `docs/architecture/`.

## `docs/architecture/architecture.md` — "Symlink policy" section (currently lines 96-101)

**Reason for change.** The user has overridden the prior policy: the walker must now follow directory symlinks too, on both Windows and Linux. Because the old "no loops possible" guarantee is gone, the walker now keeps a visited-set keyed by resolved canonical path.

**Replace the current bullet list with:**

```
### Symlink policy

- Symlinks **to files** are followed.
- Symlinks **to directories** are also followed. Cycle detection is performed via a visited-set keyed by `Path.resolve()`; on revisit the walker warns on stderr (`walker: skipping symlink cycle at <path>`) and skips.
- Symlinks resolving outside the configured roots are followed; the visited-set is sufficient to terminate.
- If a symlink target is missing, the walker warns on stderr and skips.
- The implementation uses Python stdlib only (`Path.is_symlink()`, `Path.resolve()`); no platform-conditional branching.
```

## `docs/architecture/architecture.md` — "Rejected alternatives" bullet (currently line 106)

**Reason for change.** The rejected-alternative bullet directly contradicts the new policy and must be retracted. Replace the existing bullet with a retraction note pointing at the new policy.

**Remove the bullet:**

```
- **Following directory symlinks with loop detection.** Most projects do not need it, and the failure mode (silently indexing an unrelated tree) is worse than the inconvenience of adding a `roots` entry by hand.
```

**Replace with (or simply drop, at the architect's discretion):**

```
- **Skipping directory symlinks outright.** Previously chosen on the argument that loops were not possible without dir-symlink traversal. Retracted: real projects (vendored deps, monorepo cross-links, OS-installed package trees) often rely on directory symlinks, and the inconvenience of hand-maintained `roots` outweighed the modest cost of a visited-set guard. See the [Symlink policy](#symlink-policy) section above.
```

The architect may prefer to keep the retraction explicit (the second option) rather than silently delete the bullet, since the rejected-alternatives section is meant to record decisions, not erase them.

## Observations

- The plan and `outcome.md` describe `visited` as a flat "already entered" set. Implementation needs it to be a recursion-stack (entries popped on the way back out via `try/finally`); otherwise two sibling directory symlinks pointing at the same real tree silently skip the second, which is exactly what the plan's `test_directory_symlink_to_sibling_tree_is_followed` test asserts must not happen. Possible impact: when applying the `architecture.md` "Symlink policy" delta, the architect may want to clarify the visited-set is "ancestors on the current traversal" rather than "every directory ever visited", so a future maintainer does not regress this.
- The user-facing doc the plan calls `docs/usage/index-build.md` actually lives at `src/code_index/usage/index-build.md` (it ships inside the package). Possible impact: a follow-up plan or `architecture/quick-reference.md` could note the shipped-doc path so future plans cite it correctly.
