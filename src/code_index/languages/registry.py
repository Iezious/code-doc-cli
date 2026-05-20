"""Plugin registry and extra-language loader.

The registry collects ``LANGUAGE`` / ``LANGUAGES`` exports from the seven
built-in plugin modules and from any ``extra_languages`` paths in config.
Extension dispatch is a flat dict lookup; name filtering returns a new
registry; ordering is built-ins first (in the hard-coded ``from_builtins``
order) then extras in config order.

Module loading for extras uses ``importlib.util.spec_from_file_location`` —
no ``sys.path`` mutation. The step 001 placeholder shape lives in
``_placeholder.py`` and is consumed by every built-in plugin stub.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from code_index.errors import EXIT_CONFIG, CodeIndexError, Kinds

from .protocol import Language

if TYPE_CHECKING:
    from code_index.config import CodeIndexConfig


# Hard-coded built-in plugin module names, in canonical registration order.
# `from_builtins` imports each one and harvests its LANGUAGE / LANGUAGES
# export. Steps 002-008 replace each module's placeholder with a real plugin.
_BUILTIN_MODULES: tuple[str, ...] = (
    "code_index.languages.python",
    "code_index.languages.csharp",
    "code_index.languages.javascript",
    "code_index.languages.typescript",
    "code_index.languages.golang",
    "code_index.languages.fsharp",
    "code_index.languages.lsl",
)


def _harvest_exports(module: object, source: str) -> list[Language]:
    """Pull ``LANGUAGE`` and/or ``LANGUAGES`` off ``module`` as a flat list.

    Accepts either or both. Raises :class:`CodeIndexError` with
    ``CONFIG_UNKNOWN_LANGUAGE`` when the module exposes neither. ``source``
    is the human-readable origin (module name or filesystem path) used in
    the error message and detail.
    """
    plugins: list[Language] = []
    single = getattr(module, "LANGUAGE", None)
    if single is not None:
        plugins.append(single)
    multi = getattr(module, "LANGUAGES", None)
    if multi is not None:
        plugins.extend(multi)
    if not plugins:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_UNKNOWN_LANGUAGE,
            message=(
                f"extra-language module {source!r} exposes neither "
                "LANGUAGE nor LANGUAGES"
            ),
            detail={"source": source},
        )
    return plugins


class LanguageRegistry:
    """Maps extensions to plugins and filters by configured language names."""

    def __init__(self, plugins: list[Language]) -> None:
        self._plugins: list[Language] = list(plugins)
        self._by_extension: dict[str, Language] = {}
        for plugin in self._plugins:
            for ext in plugin.extensions:
                # Last write wins; in practice built-ins and extras must not
                # collide on extension. Collision policy is Phase 4's call.
                self._by_extension[ext] = plugin

    def for_extension(self, ext: str) -> Language | None:
        """Resolve a file extension (``".py"``, ``".cs"``...) to a plugin."""
        return self._by_extension.get(ext)

    def names(self) -> list[str]:
        """Return the ``name`` of every registered plugin, in registration order."""
        return [plugin.name for plugin in self._plugins]

    @classmethod
    def from_builtins(cls) -> LanguageRegistry:
        """Import every built-in plugin module and collect its exports."""
        plugins: list[Language] = []
        for module_name in _BUILTIN_MODULES:
            module = importlib.import_module(module_name)
            plugins.extend(_harvest_exports(module, module_name))
        return cls(plugins)

    def with_extras(self, paths: list[Path]) -> LanguageRegistry:
        """Return a new registry augmented with plugins from extra paths."""
        extras: list[Language] = []
        for path in paths:
            extras.extend(load_extra_language(path))
        return LanguageRegistry(self._plugins + extras)

    def filter_active(self, language_names: list[str] | None) -> LanguageRegistry:
        """Return a new registry with only the named plugins (order preserved).

        ``None`` means no filtering — returns ``self`` unchanged.
        """
        if language_names is None:
            return self
        allowed: set[str] = set(language_names)
        kept: list[Language] = [p for p in self._plugins if p.name in allowed]
        return LanguageRegistry(kept)


def load_extra_language(path: Path) -> list[Language]:
    """Load an extra-language module from ``path`` and return its plugins.

    Uses ``importlib.util.spec_from_file_location`` + ``module_from_spec`` +
    ``loader.exec_module`` so the module is executed in isolation without
    mutating ``sys.path``. The module is registered in ``sys.modules`` under
    a synthetic name so ``dataclasses`` and pickling helpers still work.

    Raises:
        CodeIndexError(EXIT_CONFIG, CONFIG_BAD_PATH, ...) when the file does
            not exist or importlib cannot build a loader for it.
        CodeIndexError(EXIT_CONFIG, CONFIG_UNKNOWN_LANGUAGE, ...) when the
            module exposes neither ``LANGUAGE`` nor ``LANGUAGES``.

    Exceptions raised inside ``exec_module`` propagate untranslated; Phase 4
    is the layer that catches and labels them.
    """
    resolved: Path = Path(path)
    if not resolved.is_file():
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_BAD_PATH,
            message=f"extra-language module not found: {resolved}",
            detail={"path": str(resolved)},
        )

    module_name: str = f"code_index._extra_languages.{resolved.stem}"
    spec = importlib.util.spec_from_file_location(module_name, resolved)
    if spec is None or spec.loader is None:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_BAD_PATH,
            message=f"could not build import spec for {resolved}",
            detail={"path": str(resolved)},
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        # If execution fails, drop the half-built module so a retry sees a
        # clean slate. The exception itself propagates untranslated per the
        # error-mapping note in 001.context.md.
        sys.modules.pop(module_name, None)
        raise

    return _harvest_exports(module, str(resolved))


def active_plugins(config: CodeIndexConfig) -> LanguageRegistry:
    """Build the registry the indexer should use, from a resolved config.

    Order: built-ins (hard-coded ``from_builtins`` order) first, then
    ``extra_languages`` in the order they appear in config. After that the
    registry is filtered by ``config.languages``; ``None`` (in the field
    type) is treated as no filtering, but Phase 1's loader always materializes
    a list, so in practice the filter list is always concrete.
    """
    extra_paths: list[Path] = [Path(p) for p in config.extra_languages]
    registry: LanguageRegistry = LanguageRegistry.from_builtins().with_extras(extra_paths)
    return registry.filter_active(list(config.languages))
