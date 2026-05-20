"""Embedding backends for code_index.

Exports the structural `EmbeddingBackend` protocol and the
`FastembedBackend` implementation. Additional backends (Voyage, ...) land in
later phases and are added to ``__all__`` as they ship.
"""

from .factory import from_config
from .fastembed import FastembedBackend
from .protocol import EmbeddingBackend

__all__ = ["EmbeddingBackend", "FastembedBackend", "from_config"]
