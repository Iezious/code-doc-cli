"""Fastembed-backed implementation of `EmbeddingBackend`.

Wraps :class:`fastembed.TextEmbedding` so callers see a simple
``encode(texts) -> np.ndarray`` surface. Batching is handled here rather than
delegated to fastembed's ``embed(batch_size=...)`` kwarg so the contract is
identical regardless of how fastembed chunks internally.

Native fastembed exceptions raised during ``__init__`` (unknown model,
download failure on the cold cache, ONNX runtime mismatch, etc.) are wrapped
in :class:`~code_index.errors.CodeIndexError` carrying
:attr:`Kinds.BACKEND_MODEL_DOWNLOAD_FAILED`. Native exceptions raised inside
``encode`` are wrapped in :class:`~code_index.errors.CodeIndexError` carrying
:attr:`Kinds.BACKEND_ENCODE_FAILED`. The wrappers special-case
``CodeIndexError`` so already-wrapped errors propagate unchanged (no
double-wrap).
"""

from __future__ import annotations

import numpy as np
from fastembed import TextEmbedding

from code_index.errors import EXIT_BACKEND, CodeIndexError, Kinds

# Mapping of fastembed model identifiers to stable short names used in
# `name` ("fastembed:<short-name>"). The architecture doc pins
# "jina-code-v2" for the default model; extra entries can be added here
# without changing call sites.
_SHORT_NAMES: dict[str, str] = {
    "jinaai/jina-embeddings-v2-base-code": "jina-code-v2",
}


def _short_name(model: str) -> str:
    """Map a fastembed model identifier to a short name for `name`.

    Falls back to ``<part-after-slash>`` with any leading ``embeddings-``
    stripped. The fallback is intentional and undocumented in user-facing
    docs — only the default model's mapping is tested.
    """
    if model in _SHORT_NAMES:
        return _SHORT_NAMES[model]
    tail = model.rsplit("/", 1)[-1]
    if tail.startswith("embeddings-"):
        tail = tail[len("embeddings-") :]
    return tail


class FastembedBackend:
    """`EmbeddingBackend` implementation over the ``fastembed`` library."""

    name: str
    dim: int

    def __init__(
        self,
        model: str,
        batch_size: int = 32,
        cache_dir: str | None = None,
    ) -> None:
        """Instantiate a fastembed text-embedding model.

        Parameters
        ----------
        model:
            Fastembed model identifier (e.g.
            ``"jinaai/jina-embeddings-v2-base-code"``).
        batch_size:
            How many texts to pass per ``encode`` call to fastembed.
        cache_dir:
            Where fastembed stores downloaded ONNX files. ``None`` uses
            fastembed's library default (under the user home).
        """
        try:
            self._model = TextEmbedding(model_name=model, cache_dir=cache_dir)
            self._batch_size = batch_size
            # Read dim once from the underlying model — do not hardcode.
            self.dim = int(TextEmbedding.get_embedding_size(model))
            self.name = f"fastembed:{_short_name(model)}"
        except CodeIndexError:
            raise
        except Exception as exc:
            raise CodeIndexError(
                code=EXIT_BACKEND,
                kind=Kinds.BACKEND_MODEL_DOWNLOAD_FAILED,
                message=f"fastembed model {model!r} failed to load: {exc}",
                detail={
                    "model": model,
                    "cause": str(exc),
                    "type": type(exc).__name__,
                },
            ) from exc

    def encode(self, texts: list[str]) -> np.ndarray:
        """Encode ``texts`` in batches of ``self._batch_size``.

        Returns an ndarray of shape ``(len(texts), self.dim)``. Empty input
        returns shape ``(0, self.dim)``.
        """
        if not texts:
            return np.empty((0, self.dim), dtype=np.float32)

        chunks: list[np.ndarray] = []
        bs = self._batch_size
        for start in range(0, len(texts), bs):
            batch = texts[start : start + bs]
            try:
                vectors = list(self._model.embed(batch))
            except CodeIndexError:
                raise
            except Exception as exc:
                raise CodeIndexError(
                    code=EXIT_BACKEND,
                    kind=Kinds.BACKEND_ENCODE_FAILED,
                    message=f"fastembed encode failed: {exc}",
                    detail={
                        "model": self.name,
                        "cause": str(exc),
                        "type": type(exc).__name__,
                        "batch_size": len(batch),
                    },
                ) from exc
            if not vectors:
                continue
            chunks.append(np.stack(vectors, axis=0))
        return np.concatenate(chunks, axis=0)
