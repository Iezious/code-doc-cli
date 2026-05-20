"""Language plugin package for code_index.

Exposes the shared ``Chunk`` / ``Symbol`` / ``Edge`` dataclasses, the
runtime-checkable ``Language`` Protocol, and the ``LanguageRegistry`` plus
its helpers. The seven per-language plugin modules (``python.py``,
``csharp.py``, ...) sit alongside this file; step 001 ships them as
placeholders, steps 002-008 replace each one with a real implementation.
"""

from .protocol import Chunk, Edge, Language, Symbol
from .registry import LanguageRegistry, active_plugins, load_extra_language

__all__ = [
    "Chunk",
    "Symbol",
    "Edge",
    "Language",
    "LanguageRegistry",
    "load_extra_language",
    "active_plugins",
]
