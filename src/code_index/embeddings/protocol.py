"""Structural interface for embedding backends.

`EmbeddingBackend` carries the contract every backend (fastembed, voyage, ...)
must satisfy: a stable `name`, a vector `dim`, and an `encode` that returns a
2-D ``numpy`` array of shape ``(len(texts), dim)``.

The protocol is ``@runtime_checkable`` so ``isinstance(obj, EmbeddingBackend)``
works in tests and ad-hoc debugging. Pyright remains the source of truth for
structural compatibility — ``runtime_checkable`` only checks attribute
presence, not call signatures.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class EmbeddingBackend(Protocol):
    """Structural protocol for embedding backends."""

    name: str
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray:
        """Return embeddings of shape ``(len(texts), dim)``."""
        ...
