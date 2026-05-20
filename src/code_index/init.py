"""Helper for ``code_index init``.

Writes the skeleton ``docs/.helpers/config.toml`` and
``docs/.helpers/.gitignore`` for a project root per the "What ``init``
writes" section of ``docs/architecture/config.md`` and the idempotency
rules in ``docs/plans/004.walker-and-build/002.context.md``.

Kept in a sibling module so :mod:`code_index.cli` stays a thin command
surface. The CLI handler owns stdout/stderr output and exit handling;
this module's only side effects are filesystem writes on the supplied
``project_root``.

Kind selection for the refuse-without-force path: per ``002.context.md``,
the appropriate exit code is the ``usage`` category (code 1). The only
``kind`` string registered in the Phase 1 errors module under that
category is :data:`Kinds.CLI_NOT_IMPLEMENTED`, which is a semantic
stretch but the closest existing fit. The step-level test pins this
choice so any later architectural addition (e.g. ``cli.refuse_clobber``)
will surface as a deliberate change.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from packaging.version import Version

from code_index.errors import EXIT_USAGE, CodeIndexError, Kinds

GITIGNORE_TEMPLATE: str = "index.sqlite\nindex.sqlite-wal\nindex.sqlite-shm\n"


def _engine_version_string() -> str:
    """Read the running engine version from package metadata."""
    try:
        return _pkg_version("code_index")
    except PackageNotFoundError:  # pragma: no cover - source checkout
        from code_index import __version__ as engine_version

        return engine_version


def compute_version_pin(engine_version: str) -> str:
    """Return the PEP 440 pin string for an engine version.

    Per ``002.context.md``: ``">={major}.{minor},<{major}.{minor+2}"``. For
    engine ``0.3.x`` this is ``">=0.3,<0.5"``; for ``0.4.x`` it is
    ``">=0.4,<0.6"``.
    """
    parsed: Version = Version(engine_version)
    major: int = parsed.major
    minor: int = parsed.minor
    return f">={major}.{minor},<{major}.{minor + 2}"


def _render_config(project_name: str, version_pin: str) -> str:
    """Render the skeleton ``config.toml`` body."""
    return (
        "[code_index]\n"
        f'version       = "{version_pin}"\n'
        f'project       = "{project_name}"\n'
        'roots         = ["."]\n'
        'embed_backend = "fastembed"\n'
        'embed_model   = "jinaai/jina-embeddings-v2-base-code"\n'
    )


def write_skeleton(
    project_root: Path,
    *,
    project_name: str | None,
    force: bool,
) -> tuple[Path, Path, bool]:
    """Write ``docs/.helpers/config.toml`` and ``.gitignore`` under ``project_root``.

    ``project_name`` defaults to the basename of ``project_root`` when
    ``None``. Refuses to overwrite an existing ``config.toml`` unless
    ``force`` is true. Re-writing a ``.gitignore`` that already matches
    the template is skipped to keep mtime stable.

    Returns ``(config_path, gitignore_path, gitignore_written)``. The
    boolean is ``False`` when the gitignore already matched the template
    and was not rewritten.
    """
    helpers_dir: Path = project_root / "docs" / ".helpers"
    config_path: Path = helpers_dir / "config.toml"
    gitignore_path: Path = helpers_dir / ".gitignore"

    if config_path.exists() and not force:
        raise CodeIndexError(
            code=EXIT_USAGE,
            kind=Kinds.CLI_NOT_IMPLEMENTED,
            message=(
                f"refusing to overwrite existing {config_path} without --force"
            ),
            detail={"path": str(config_path)},
        )

    helpers_dir.mkdir(parents=True, exist_ok=True)

    resolved_name: str = project_name if project_name else project_root.resolve().name
    version_pin: str = compute_version_pin(_engine_version_string())
    config_path.write_text(_render_config(resolved_name, version_pin), encoding="utf-8")

    gitignore_written: bool = False
    if gitignore_path.exists():
        existing: str = gitignore_path.read_text(encoding="utf-8")
        if existing != GITIGNORE_TEMPLATE:
            gitignore_path.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
            gitignore_written = True
    else:
        gitignore_path.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")
        gitignore_written = True

    return config_path, gitignore_path, gitignore_written
