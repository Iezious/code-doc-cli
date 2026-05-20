"""Tests for `code_index.embeddings.factory.from_config`.

All tests monkeypatch ``FastembedBackend`` inside the factory module so no
real model download is performed; real-download behavior is covered by
``tests/test_fastembed_backend.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from code_index.config import CodeIndexConfig
from code_index.embeddings import factory as factory_module
from code_index.embeddings import from_config as reexported_from_config
from code_index.embeddings.factory import from_config
from code_index.errors import EXIT_USAGE, CodeIndexError, Kinds


def _make_config(
    *,
    embed_backend: str,
    embed_model: str,
    embed_batch_size: int = 32,
) -> CodeIndexConfig:
    """Build a `CodeIndexConfig` directly, bypassing filesystem validation.

    Factory tests only care about the three embed_* fields; the rest are set
    to harmless placeholders. Pydantic still type-checks the values.
    """
    return CodeIndexConfig(
        version=">=0.1,<1",
        project="test-project",
        roots=["."],
        ignores=[],
        languages=[],
        extra_languages=[],
        embed_backend=embed_backend,  # type: ignore[arg-type]
        embed_model=embed_model,
        embed_batch_size=embed_batch_size,
    )


@pytest.fixture
def fastembed_spy(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace `factory.FastembedBackend` with a MagicMock spy.

    Returning the spy lets each test inspect call args. The spy's return value
    is the instance that `from_config` should return when dispatched to
    fastembed.
    """
    spy = MagicMock(name="FastembedBackend")
    monkeypatch.setattr(factory_module, "FastembedBackend", spy)
    return spy


def test_factory_dispatches_fastembed(fastembed_spy: MagicMock) -> None:
    config = _make_config(
        embed_backend="fastembed",
        embed_model="jinaai/jina-embeddings-v2-base-code",
        embed_batch_size=32,
    )

    result = from_config(config)

    fastembed_spy.assert_called_once_with(
        model="jinaai/jina-embeddings-v2-base-code",
        batch_size=32,
    )
    assert result is fastembed_spy.return_value


def test_factory_passes_batch_size(fastembed_spy: MagicMock) -> None:
    config = _make_config(
        embed_backend="fastembed",
        embed_model="jinaai/jina-embeddings-v2-base-code",
        embed_batch_size=64,
    )

    from_config(config)

    kwargs: Any = fastembed_spy.call_args.kwargs
    assert kwargs["batch_size"] == 64


def test_factory_passes_model(fastembed_spy: MagicMock) -> None:
    config = _make_config(
        embed_backend="fastembed",
        embed_model="some-other-fastembed-model",
        embed_batch_size=32,
    )

    from_config(config)

    kwargs: Any = fastembed_spy.call_args.kwargs
    assert kwargs["model"] == "some-other-fastembed-model"


def test_factory_raises_for_voyage(fastembed_spy: MagicMock) -> None:
    config = _make_config(
        embed_backend="voyage",
        embed_model="voyage-code-3",
    )

    with pytest.raises(CodeIndexError) as exc_info:
        from_config(config)

    err = exc_info.value
    assert err.code == EXIT_USAGE
    assert err.kind == Kinds.CLI_NOT_IMPLEMENTED
    assert "phase 7" in err.message.lower()
    # The fastembed branch must not have been taken.
    fastembed_spy.assert_not_called()


def test_factory_voyage_message_mentions_voyage(
    fastembed_spy: MagicMock,
) -> None:
    config = _make_config(
        embed_backend="voyage",
        embed_model="voyage-code-3",
    )

    with pytest.raises(CodeIndexError) as exc_info:
        from_config(config)

    assert "voyage" in exc_info.value.message.lower()
    fastembed_spy.assert_not_called()


def test_init_reexports_from_config() -> None:
    assert reexported_from_config is from_config
