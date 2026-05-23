"""Per-project config loader.

Parses ``docs/.helpers/config.toml`` (or the path given via ``--config``),
validates against the schema in ``docs/architecture/config.md``, applies
defaults, and returns a resolved :class:`CodeIndexConfig`. Every documented
validation failure is raised as a :class:`CodeIndexError` carrying the
matching ``code`` / ``kind`` from the Config section of
``docs/architecture/errors-and-exit-codes.md``.

Phase-1 approximations recorded here, replaced in later phases:

* The "registered language names" set is ``DEFAULT_LANGUAGES`` plus the
  basenames (file stem) of ``extra_languages`` entries. The real plugin
  registry from Phase 3 will own this surface.
* ``embed_model``/backend compatibility is accepted as long as the value is
  a non-empty string; only the per-backend default is asserted by tests.
  The real compatibility check belongs to Phase 2 backends.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any, Literal

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, ConfigDict

from code_index.errors import EXIT_CONFIG, CodeIndexError, Kinds, write_log_stderr

EmbedBackend = Literal["fastembed", "voyage"]

DEFAULT_LANGUAGES: tuple[str, ...] = (
    "fsharp",
    "csharp",
    "javascript",
    "typescript",
    "go",
    "python",
    "lsl",
)

ALLOWED_BACKENDS: tuple[str, ...] = ("fastembed", "voyage")

BACKEND_DEFAULT_MODEL: dict[str, str] = {
    "fastembed": "jinaai/jina-embeddings-v2-base-code",
    "voyage": "voyage-code-3",
}


class CodeIndexConfig(BaseModel):
    """Resolved per-project configuration.

    Field defaults match the table in ``docs/architecture/config.md``.
    ``embed_model`` is filled in by :func:`load_config` from
    :data:`BACKEND_DEFAULT_MODEL` based on the resolved ``embed_backend`` so
    the per-backend default is applied without having to special-case it
    here.
    """

    model_config = ConfigDict(extra="ignore")

    version: str
    project: str
    roots: list[str]
    ignores: list[str]
    languages: list[str]
    extra_languages: list[str]
    embed_backend: EmbedBackend
    embed_model: str
    embed_batch_size: int


# Keys recognized inside ``[code_index]``. Anything else triggers a warning.
_KNOWN_KEYS: frozenset[str] = frozenset(
    {
        "version",
        "project",
        "roots",
        "ignores",
        "languages",
        "extra_languages",
        "embed_backend",
        "embed_model",
        "embed_batch_size",
    }
)


def _engine_version_default() -> str:
    """Read the running engine version from ``code_index.__version__``.

    Done lazily so tests can override via ``engine_version=`` and the module
    import is cheap.
    """
    from code_index import __version__ as engine_version

    return engine_version


def discover_config_path(start: Path) -> Path:
    """Walk upward from ``start`` looking for ``docs/.helpers/config.toml``.

    Returns the resolved path on the first ancestor that contains it. Raises
    :class:`CodeIndexError` with ``code = EXIT_CONFIG`` and
    ``kind = Kinds.CONFIG_PARSE_ERROR`` when no config file is found — the
    final mapping for "no config discovered" is settled in step 005's
    context; this loader's tests do not exercise this branch.
    """
    start = start.resolve()
    candidates: list[Path] = [start, *start.parents]
    for parent in candidates:
        candidate = parent / "docs" / ".helpers" / "config.toml"
        if candidate.is_file():
            return candidate.resolve()
    raise CodeIndexError(
        code=EXIT_CONFIG,
        kind=Kinds.CONFIG_PARSE_ERROR,
        message=f"no docs/.helpers/config.toml found walking up from {start}",
        detail={"start": str(start)},
    )


def load_config(
    config_path: Path,
    *,
    project_root: Path | None = None,
    engine_version: str | None = None,
) -> CodeIndexConfig:
    """Parse, validate, and resolve the config at ``config_path``.

    ``project_root`` is the directory containing ``docs/.helpers/``. When
    omitted it is derived from ``config_path`` as
    ``config_path.parent.parent.parent`` (``config.toml`` -> ``.helpers`` ->
    ``docs`` -> project root).

    ``engine_version`` defaults to ``code_index.__version__``; injectable so
    tests can pin the value and exercise the version-pin check.

    Raises :class:`CodeIndexError` for every documented failure mode in
    ``docs/architecture/errors-and-exit-codes.md`` "Config" section. Unknown
    keys under ``[code_index]`` only emit a stderr warning via
    :func:`errors.write_log_stderr` — they never raise.

    Phase-1 note: ``languages`` is validated against ``DEFAULT_LANGUAGES``
    plus the file stems of ``extra_languages`` entries. The real plugin
    registry from Phase 3 supersedes this approximation.
    """
    config_path = Path(config_path)
    resolved_project_root: Path = (
        Path(project_root)
        if project_root is not None
        else config_path.parent.parent.parent
    )
    resolved_engine_version: str = (
        engine_version if engine_version is not None else _engine_version_default()
    )

    # 1. Read the file.
    try:
        raw_bytes: bytes = config_path.read_bytes()
    except FileNotFoundError as exc:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_PARSE_ERROR,
            message=f"config file not found: {config_path}",
            detail={"path": str(config_path)},
        ) from exc
    except OSError as exc:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_PARSE_ERROR,
            message=f"could not read config file: {config_path}: {exc}",
            detail={"path": str(config_path)},
        ) from exc

    # 2. Parse TOML.
    try:
        parsed: dict[str, Any] = tomllib.loads(raw_bytes.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_PARSE_ERROR,
            message=f"malformed TOML in {config_path}: {exc}",
            detail={"path": str(config_path)},
        ) from exc

    # 3. Extract [code_index] table and required keys.
    table_obj: Any = parsed.get("code_index")
    if not isinstance(table_obj, dict):
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_MISSING_KEY,
            message=f"missing [code_index] table in {config_path}",
            detail={"path": str(config_path), "key": "code_index"},
        )
    table: dict[str, Any] = {str(k): v for k, v in table_obj.items()}  # type: ignore[reportUnknownVariableType]

    if "version" not in table:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_MISSING_KEY,
            message=f"missing required key 'version' in [code_index] ({config_path})",
            detail={"path": str(config_path), "key": "version"},
        )

    # 4. Warn on unknown keys (never raise).
    for key in table:
        if key not in _KNOWN_KEYS:
            write_log_stderr(
                f"warning: unknown key '{key}' under [code_index] in {config_path}"
            )

    # 5. Embed backend check — needs to happen before model defaulting.
    embed_backend_value: Any = table.get("embed_backend", "fastembed")
    if not isinstance(embed_backend_value, str) or embed_backend_value not in ALLOWED_BACKENDS:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_BAD_ENUM,
            message=(
                f"invalid embed_backend {embed_backend_value!r}; "
                f"allowed: {list(ALLOWED_BACKENDS)}"
            ),
            detail={
                "key": "embed_backend",
                "value": embed_backend_value,
                "allowed": list(ALLOWED_BACKENDS),
            },
        )

    # 6. Default embed_model from backend if missing.
    embed_model_value: Any = table.get(
        "embed_model", BACKEND_DEFAULT_MODEL[embed_backend_value]
    )
    if not isinstance(embed_model_value, str) or not embed_model_value:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_MODEL_BACKEND_MISMATCH,
            message=(
                f"embed_model must be a non-empty string for backend "
                f"{embed_backend_value!r}"
            ),
            detail={
                "key": "embed_model",
                "value": embed_model_value,
                "backend": embed_backend_value,
            },
        )

    # 7. Default project to project_root.name when missing.
    project_value: Any = table.get("project", resolved_project_root.name)
    if not isinstance(project_value, str) or not project_value:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_PARSE_ERROR,
            message="'project' must be a non-empty string when set",
            detail={"key": "project", "value": project_value},
        )

    # 8. Coerce list-of-string fields with type guards.
    roots_value: list[str] = _as_str_list(table.get("roots", ["."]), key="roots")
    ignores_value: list[str] = _as_str_list(table.get("ignores", []), key="ignores")
    languages_value: list[str] = _as_str_list(
        table.get("languages", list(DEFAULT_LANGUAGES)), key="languages"
    )
    extra_languages_value: list[str] = _as_str_list(
        table.get("extra_languages", []), key="extra_languages"
    )

    embed_batch_size_value: Any = table.get("embed_batch_size", 16)
    if not isinstance(embed_batch_size_value, int) or isinstance(
        embed_batch_size_value, bool
    ) or embed_batch_size_value <= 0:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_PARSE_ERROR,
            message="embed_batch_size must be a positive integer",
            detail={"key": "embed_batch_size", "value": embed_batch_size_value},
        )

    version_value: Any = table["version"]
    if not isinstance(version_value, str) or not version_value:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_MISSING_KEY,
            message="'version' must be a non-empty string",
            detail={"key": "version", "value": version_value},
        )

    # 9. Version pin: parse specifier, check engine satisfies it.
    try:
        specifier_set: SpecifierSet = SpecifierSet(version_value)
    except InvalidSpecifier as exc:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_VERSION_MISMATCH,
            message=(
                f"invalid PEP 440 version specifier {version_value!r} "
                f"for 'version': {exc}"
            ),
            detail={"pin": version_value},
        ) from exc

    try:
        parsed_engine_version: Version = Version(resolved_engine_version)
    except InvalidVersion as exc:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_VERSION_MISMATCH,
            message=(
                f"engine version {resolved_engine_version!r} is not a valid "
                f"PEP 440 version: {exc}"
            ),
            detail={
                "pin": version_value,
                "engine_version": resolved_engine_version,
            },
        ) from exc

    if parsed_engine_version not in specifier_set:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_VERSION_MISMATCH,
            message=(
                f"engine {resolved_engine_version} does not satisfy pin "
                f"{version_value!r} in {config_path}"
            ),
            detail={
                "pin": version_value,
                "engine_version": resolved_engine_version,
            },
        )

    # 10. Validate roots exist under project root.
    for root_str in roots_value:
        candidate: Path = (resolved_project_root / root_str).resolve()
        if not candidate.exists():
            raise CodeIndexError(
                code=EXIT_CONFIG,
                kind=Kinds.CONFIG_BAD_PATH,
                message=(
                    f"roots entry {root_str!r} does not exist under project "
                    f"root {resolved_project_root}"
                ),
                detail={
                    "key": "roots",
                    "value": root_str,
                    "resolved": str(candidate),
                    "project_root": str(resolved_project_root),
                },
            )

    # 11. Validate extra_languages exist and are readable.
    for lang_path_str in extra_languages_value:
        candidate = (resolved_project_root / lang_path_str).resolve()
        if not candidate.is_file():
            raise CodeIndexError(
                code=EXIT_CONFIG,
                kind=Kinds.CONFIG_BAD_PATH,
                message=(
                    f"extra_languages entry {lang_path_str!r} is not a "
                    f"readable file under {resolved_project_root}"
                ),
                detail={
                    "key": "extra_languages",
                    "value": lang_path_str,
                    "resolved": str(candidate),
                    "project_root": str(resolved_project_root),
                },
            )

    # 12. Validate languages against the Phase-1 approximation registry.
    extra_lang_names: set[str] = {
        Path(p).stem for p in extra_languages_value
    }
    registered: set[str] = set(DEFAULT_LANGUAGES) | extra_lang_names
    for lang_name in languages_value:
        if lang_name not in registered:
            raise CodeIndexError(
                code=EXIT_CONFIG,
                kind=Kinds.CONFIG_UNKNOWN_LANGUAGE,
                message=(
                    f"languages entry {lang_name!r} is not a registered "
                    f"language; known: {sorted(registered)}"
                ),
                detail={
                    "key": "languages",
                    "value": lang_name,
                    "known": sorted(registered),
                },
            )

    # 13. Build the resolved model.
    return CodeIndexConfig(
        version=version_value,
        project=project_value,
        roots=roots_value,
        ignores=ignores_value,
        languages=languages_value,
        extra_languages=extra_languages_value,
        embed_backend=embed_backend_value,  # type: ignore[arg-type]
        embed_model=embed_model_value,
        embed_batch_size=embed_batch_size_value,
    )


def _as_str_list(value: Any, *, key: str) -> list[str]:
    """Coerce a TOML value to ``list[str]``, raising on type mismatch.

    Used for ``roots``, ``ignores``, ``languages``, ``extra_languages``. Type
    failures map to ``config.parse_error`` because they indicate the TOML
    does not match the documented schema shape.
    """
    if not isinstance(value, list):
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_PARSE_ERROR,
            message=f"'{key}' must be a list of strings",
            detail={"key": key, "value": value},
        )
    result: list[str] = []
    for entry in value:  # type: ignore[reportUnknownVariableType]
        if not isinstance(entry, str):
            raise CodeIndexError(
                code=EXIT_CONFIG,
                kind=Kinds.CONFIG_PARSE_ERROR,
                message=f"'{key}' must be a list of strings",
                detail={"key": key, "value": value},
            )
        result.append(entry)
    return result
