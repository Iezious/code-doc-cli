"""File walker for the indexer pipeline.

Implements the rules pinned by ``docs/architecture/architecture.md``'s
"Indexer walking" section: built-in default excludes, ``.gitignore`` (only
when a ``.git/`` marker is present at the root) parsed via ``pathspec`` with
``GitWildMatchPattern``, ``config.ignores`` (additive), an extension filter
derived from the active plugin registry, a 1 MiB max-file-size cap, a NUL
byte binary probe over the first 8 KiB, the symlink policy (files followed,
directories skipped, missing targets warned), and UTF-8 decoding with a
``replace`` fallback on ``UnicodeDecodeError``.

The walker does not raise on per-file problems in Phase 4: every failure
becomes a stderr warning via :func:`code_index.errors.write_log_stderr` and
the file is skipped.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pathspec

from code_index.errors import write_log_stderr
from code_index.languages import active_plugins

#: Type alias for the pattern-set returned by ``pathspec.PathSpec.from_lines``.
#: ``pathspec.PathSpec`` is generic in v1.x; ``from_lines`` returns the
#: parameterization over the base ``Pattern`` type, so we pin the alias to
#: match what callers actually receive.
_Spec = pathspec.PathSpec[pathspec.Pattern]

if TYPE_CHECKING:
    from code_index.config import CodeIndexConfig


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Hard 1 MiB cap; files larger are skipped with a stderr warning.
MAX_FILE_SIZE: int = 1024 * 1024

#: Size of the binary-probe read; first NUL byte within these bytes makes the
#: walker treat the file as binary and skip it.
BINARY_PROBE_BYTES: int = 8 * 1024

#: Built-in default excludes, always applied regardless of ``.gitignore``.
#: Patterns use gitwildmatch syntax (trailing slash = directory-only). Kept
#: in sync with ``docs/architecture/architecture.md`` "Built-in default
#: excludes". The ``docs/.helpers/`` entry exists so the walker never
#: re-indexes its own index storage.
DEFAULT_EXCLUDES: tuple[str, ...] = (
    ".git/",
    ".hg/",
    ".svn/",
    "node_modules/",
    "bower_components/",
    ".venv/",
    "venv/",
    "__pycache__/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    "*.egg-info/",
    "dist/",
    "build/",
    "out/",
    "target/",
    "bin/",
    "obj/",
    ".idea/",
    ".vscode/",
    "docs/.helpers/",
)


# ---------------------------------------------------------------------------
# Output record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WalkedFile:
    """A single file the walker decided to surface to the chunker.

    * ``path`` — absolute filesystem path. For a file symlink this is the
      link's own path, not the resolved target.
    * ``rel_path`` — same file expressed relative to the walk root the
      caller supplied.
    * ``content`` — UTF-8 decoded text. When the file's bytes were not
      strict UTF-8, the decoder ran a second pass with ``errors="replace"``
      and ``decode_warning`` is ``True``.
    * ``extension`` — ``Path.suffix`` of the file path, lowercased to match
      plugin registration. Includes the leading dot, e.g. ``".py"``.
    * ``decode_warning`` — set when the replace-fallback was used.
    """

    path: Path
    rel_path: Path
    content: str
    extension: str
    decode_warning: bool


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def walk(root: Path, config: CodeIndexConfig) -> Iterator[WalkedFile]:
    """Yield :class:`WalkedFile` records for every indexable file under ``root``.

    Honors every rule documented in ``architecture.md``'s "Indexer walking"
    section: built-in excludes, ``.gitignore`` when ``.git/`` is present
    (matched against paths relative to each ``.gitignore``'s own directory,
    using ``pathspec`` with ``GitWildMatchPattern``), additive
    ``config.ignores`` patterns, plugin-registered extension filter, 1 MiB
    cap, NUL byte binary probe, symlink policy (files followed, directories
    skipped, missing targets warned), UTF-8 with ``replace`` fallback.

    Per-file failures (oversize, binary, decode, missing symlink target,
    OS errors) are reported with a stderr warning and the file is skipped;
    the walker never raises on those.
    """
    root_abs: Path = Path(root).resolve()

    registry = active_plugins(config)
    gitignore_active: bool = (root_abs / ".git").is_dir()
    default_spec = _spec_for_patterns(list(DEFAULT_EXCLUDES))
    ignores_spec = _spec_for_patterns(list(config.ignores))

    # Lazily built map from a directory containing a ``.gitignore`` to the
    # parsed PathSpec for that file. Only populated when gitignore_active.
    gitignore_specs: dict[Path, _Spec] = {}

    yield from _walk_dir(
        root_abs,
        root_abs,
        registry,
        default_spec,
        ignores_spec,
        gitignore_specs,
        gitignore_active,
    )


# ---------------------------------------------------------------------------
# Directory traversal
# ---------------------------------------------------------------------------


def _walk_dir(
    current: Path,
    root: Path,
    registry: object,
    default_spec: _Spec,
    ignores_spec: _Spec,
    gitignore_specs: dict[Path, _Spec],
    gitignore_active: bool,
) -> Iterator[WalkedFile]:
    """Recursive helper: iterate entries in ``current`` and recurse into directories.

    Walks the tree depth-first. Order between entries is undefined beyond
    what ``iterdir`` provides — tests assert membership, not order.

    ``registry`` is the resolved :class:`code_index.languages.LanguageRegistry`;
    typed as ``object`` here to avoid a public import cycle with the
    ``languages`` package.
    """
    # Load a `.gitignore` from this directory if applicable.
    if gitignore_active:
        candidate = current / ".gitignore"
        if candidate.is_file() and current not in gitignore_specs:
            try:
                lines = candidate.read_text(encoding="utf-8").splitlines()
                gitignore_specs[current] = _Spec.from_lines(
                    "gitwildmatch", lines
                )
            except OSError as exc:
                write_log_stderr(
                    f"walker: could not read .gitignore at {candidate}: {exc}"
                )

    try:
        entries = list(current.iterdir())
    except OSError as exc:
        write_log_stderr(f"walker: could not list directory {current}: {exc}")
        return

    for entry in entries:
        rel = entry.relative_to(root)

        # Symlink policy is checked up front because it changes the meaning of
        # `is_dir()` / `is_file()` below (Path.is_dir resolves the link).
        is_symlink: bool = entry.is_symlink()
        if is_symlink:
            try:
                target_exists: bool = entry.exists()
            except OSError as exc:
                write_log_stderr(
                    f"walker: could not stat symlink {entry}: {exc}"
                )
                continue
            if not target_exists:
                write_log_stderr(
                    f"walker: skipping broken symlink {entry}"
                )
                continue
            if entry.is_dir():
                # Symlinks to directories are not followed — documented policy.
                continue
            # Symlink to file: fall through into the file branch, yielding the
            # link path (not the resolved target).

        # Apply exclude/ignore filters using the *rel-from-root* path. For
        # directories pass a trailing slash so `pathspec` treats `foo/`
        # rules as matching the directory itself.
        rel_posix = rel.as_posix()
        is_dir = entry.is_dir() and not is_symlink  # symlink-to-file handled above

        if _excluded(
            rel_posix,
            is_dir,
            current,
            root,
            default_spec,
            ignores_spec,
            gitignore_specs,
            gitignore_active,
        ):
            continue

        if is_dir:
            yield from _walk_dir(
                entry,
                root,
                registry,
                default_spec,
                ignores_spec,
                gitignore_specs,
                gitignore_active,
            )
            continue

        # File branch (regular file or file-symlink that survived the
        # symlink-policy block above).
        result = _consider_file(entry, root, registry)
        if result is not None:
            yield result


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def _spec_for_patterns(patterns: list[str]) -> _Spec:
    """Build a :class:`_Spec` from a list of gitwildmatch patterns.

    Centralized so the syntax (``"gitwildmatch"``) stays consistent between
    built-in excludes, ``config.ignores``, and ``.gitignore`` files — the
    user-facing contract from ``001.context.md``.
    """
    return _Spec.from_lines("gitwildmatch", patterns)


def _excluded(
    rel_posix: str,
    is_dir: bool,
    current: Path,
    root: Path,
    default_spec: _Spec,
    ignores_spec: _Spec,
    gitignore_specs: dict[Path, _Spec],
    gitignore_active: bool,
) -> bool:
    """Return ``True`` when any active ignore source matches the entry.

    The first match wins for short-circuiting; the order is the one
    recommended by ``001.context.md`` (defaults, then ``.gitignore``, then
    ``config.ignores``). There is no negation/override between sources;
    exclusion always wins.
    """
    # `pathspec` honors trailing-slash semantics when the *match target* ends
    # with `/`. Pass the slashed form for directories so `foo/` patterns hit.
    match_target = rel_posix + "/" if is_dir else rel_posix

    if default_spec.match_file(match_target):
        return True

    if gitignore_active:
        # Walk from the root down to `current` checking each `.gitignore`
        # along the way. Each PathSpec matches against paths relative to its
        # own directory.
        for ancestor in _ancestors_inclusive(current, root):
            spec = gitignore_specs.get(ancestor)
            if spec is None:
                continue
            try:
                rel_from_spec = Path(current, rel_posix).resolve().relative_to(ancestor)
            except (ValueError, OSError):
                continue
            target = rel_from_spec.as_posix()
            if is_dir:
                target = target + "/"
            if spec.match_file(target):
                return True

    return bool(ignores_spec.match_file(match_target))


def _ancestors_inclusive(current: Path, root: Path) -> list[Path]:
    """Return [root, ..., current] — every directory between root and current.

    Order matters for nested-``.gitignore`` evaluation: the outermost
    ``.gitignore`` runs first so an inner rule sees the same path the user
    sees in their editor.
    """
    out: list[Path] = []
    cur = current
    while True:
        out.append(cur)
        if cur == root:
            break
        parent = cur.parent
        if parent == cur:  # filesystem root reached without hitting `root`
            break
        cur = parent
    out.reverse()
    return out


# ---------------------------------------------------------------------------
# Per-file handling
# ---------------------------------------------------------------------------


def _consider_file(path: Path, root: Path, registry: object) -> WalkedFile | None:
    """Apply file-level filters and decode; return the record or ``None``.

    Order: extension filter (cheap) -> stat size check -> NUL probe ->
    full read + UTF-8 decode with replace-fallback. Each failure logs a
    single stderr warning and returns ``None``; the walker never raises on
    a per-file problem in Phase 4.
    """
    extension: str = path.suffix.lower()

    # `registry` is a LanguageRegistry; using `for_extension` keeps the public
    # surface narrow and avoids reaching into `_plugins`.
    plugin = registry.for_extension(extension)  # type: ignore[attr-defined]
    if plugin is None:
        return None

    try:
        size: int = path.stat().st_size
    except OSError as exc:
        write_log_stderr(f"walker: could not stat {path}: {exc}")
        return None

    if size > MAX_FILE_SIZE:
        write_log_stderr(
            f"walker: skipping oversize file {path} ({size} bytes > {MAX_FILE_SIZE})"
        )
        return None

    # Binary probe — read the first 8 KiB and look for a NUL byte. Done in a
    # separate open so we do not have to seek; the probe is pre-decode.
    try:
        with path.open("rb") as handle:
            probe: bytes = handle.read(BINARY_PROBE_BYTES)
    except OSError as exc:
        write_log_stderr(f"walker: could not read {path}: {exc}")
        return None

    if b"\x00" in probe:
        write_log_stderr(f"walker: skipping binary file {path} (NUL byte in first 8 KiB)")
        return None

    # Full read + decode. UTF-8 strict first; on failure, replace-fallback +
    # warn.
    try:
        raw: bytes = path.read_bytes()
    except OSError as exc:
        write_log_stderr(f"walker: could not read {path}: {exc}")
        return None

    decode_warning: bool = False
    try:
        content: str = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("utf-8", errors="replace")
        decode_warning = True
        write_log_stderr(
            f"walker: non-UTF-8 bytes in {path}; decoded with replacement characters"
        )

    rel_path: Path = path.relative_to(root)
    return WalkedFile(
        path=path,
        rel_path=rel_path,
        content=content,
        extension=extension,
        decode_warning=decode_warning,
    )
