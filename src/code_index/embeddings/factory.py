"""Factory dispatching a resolved config to a concrete embedding backend.

`from_config` is the single entry point used by the indexer (Phase 4) and any
future consumer that needs an :class:`EmbeddingBackend` instance built from a
:class:`~code_index.config.CodeIndexConfig`. It reads only
``embed_backend`` / ``embed_model`` / ``embed_batch_size`` off the config; the
caller is responsible for having produced a validated config in the first
place.

For ``embed_backend == "voyage"`` the factory raises
:class:`~code_index.errors.CodeIndexError` with ``kind`` set to
:attr:`Kinds.CLI_NOT_IMPLEMENTED`. Phase 7 replaces this branch with the real
Voyage backend; the kind reuse is documented in this feature's ``outcome.md``.
"""

from __future__ import annotations

from code_index.config import CodeIndexConfig
from code_index.errors import EXIT_BACKEND, EXIT_USAGE, CodeIndexError, Kinds

from .device import requested_device
from .fastembed import FastembedBackend
from .protocol import EmbeddingBackend


def from_config(config: CodeIndexConfig) -> EmbeddingBackend:
    """Instantiate the embedding backend specified by ``config``.

    Reads ``config.embed_backend``, ``config.embed_model``,
    ``config.embed_batch_size``.

    Returns:
        :class:`FastembedBackend` when ``embed_backend == "fastembed"``.

    Raises:
        CodeIndexError: with ``code = EXIT_USAGE`` and
            ``kind = Kinds.CLI_NOT_IMPLEMENTED`` when
            ``embed_backend == "voyage"``. Phase 7 replaces this raise with
            the real Voyage backend.
    """
    backend = config.embed_backend
    if backend == "fastembed":
        try:
            # Read CODE_INDEX_DEVICE here (the env read is centralized in the
            # factory; the backend stays a pure resolver of what it is handed).
            return FastembedBackend(
                model=config.embed_model,
                batch_size=config.embed_batch_size,
                device=requested_device(),
            )
        except CodeIndexError:
            raise
        except Exception as exc:
            raise CodeIndexError(
                code=EXIT_BACKEND,
                kind=Kinds.BACKEND_MODEL_DOWNLOAD_FAILED,
                message=(f"fastembed model {config.embed_model!r} failed to load: {exc}"),
                detail={
                    "model": config.embed_model,
                    "cause": str(exc),
                    "type": type(exc).__name__,
                },
            ) from exc
    # `embed_backend` is `Literal["fastembed", "voyage"]`, so the only remaining
    # value is "voyage". Phase 7 replaces this raise with the real Voyage
    # backend.
    raise CodeIndexError(
        code=EXIT_USAGE,
        kind=Kinds.CLI_NOT_IMPLEMENTED,
        message=("voyage backend not available in this build (lands in Phase 7)"),
        detail={"embed_backend": backend},
    )
