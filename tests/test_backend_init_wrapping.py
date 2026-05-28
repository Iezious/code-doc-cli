"""Tests for Phase 7 step 003 — fastembed backend exception wrapping.

These tests stub out the native fastembed entry points so no model download
occurs. They specifically exercise the failure paths added by step 003:

* ``FastembedBackend.__init__`` exceptions wrap to
  ``Kinds.BACKEND_MODEL_DOWNLOAD_FAILED``.
* ``FastembedBackend.encode`` exceptions wrap to
  ``Kinds.BACKEND_ENCODE_FAILED``.
* ``from_config(...)`` wraps construction failures the same way.
* ``CodeIndexError`` raised from inside the wrapped region is re-raised
  unchanged (no double-wrap).
* ``raise ... from exc`` chaining is preserved.
* The wrapped envelope round-trips through ``json.loads``.

The encode-wrap tests bypass real construction by replacing
``FastembedBackend.__init__`` with a no-op that just installs the
attributes the wrap code reads (``_model``, ``_batch_size``, ``name``,
``dim``).
"""

from __future__ import annotations

import json

import numpy as np
import pytest

from code_index.config import CodeIndexConfig
from code_index.embeddings import device as device_module
from code_index.embeddings import factory as factory_module
from code_index.embeddings import fastembed as fastembed_module
from code_index.embeddings.device import CUDA_PROVIDER
from code_index.embeddings.factory import from_config
from code_index.embeddings.fastembed import FastembedBackend
from code_index.errors import EXIT_BACKEND, CodeIndexError, Kinds

_DEFAULT_MODEL = "jinaai/jina-embeddings-v2-base-code"


def _make_config(
    *,
    embed_backend: str = "fastembed",
    embed_model: str = _DEFAULT_MODEL,
    embed_batch_size: int = 32,
) -> CodeIndexConfig:
    """Build a ``CodeIndexConfig`` for factory tests bypassing TOML validation."""
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


class _StubModel:
    """Stand-in for ``fastembed.TextEmbedding`` instance.

    ``embed`` is the only method the production code touches. Tests assign
    a side_effect-like callable to control its behavior.
    """

    def __init__(self, embed_fn: object) -> None:
        self._embed_fn = embed_fn

    def embed(self, batch: list[str]) -> object:
        fn = self._embed_fn
        # The production code calls ``list(self._model.embed(batch))``; the
        # callable returns an iterable (or raises).
        assert callable(fn)
        return fn(batch)


def _install_noop_init(monkeypatch: pytest.MonkeyPatch, stub_model: _StubModel) -> None:
    """Replace ``FastembedBackend.__init__`` with a no-op installing stubs.

    Skips the real fastembed download. The replacement mimics the attribute
    surface ``encode`` relies on.
    """

    def fake_init(
        self: FastembedBackend,
        model: str,
        batch_size: int = 32,
        cache_dir: str | None = None,
        device: str | None = None,
    ) -> None:
        # Bypass the real wrap shell so the test exercises ``encode``'s wrap
        # in isolation.
        self._model = stub_model  # type: ignore[assignment]
        self._batch_size = batch_size
        self.dim = 768
        self.name = "fastembed:jina-code-v2"
        self.device = "cpu"

    monkeypatch.setattr(FastembedBackend, "__init__", fake_init)


def test_init_wraps_native_exception_to_model_download_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``FastembedBackend.__init__`` wraps a native error into the registered kind."""

    def raising_text_embedding(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated download failure")

    monkeypatch.setattr(
        "code_index.embeddings.fastembed.TextEmbedding",
        raising_text_embedding,
    )

    with pytest.raises(CodeIndexError) as exc_info:
        FastembedBackend(model=_DEFAULT_MODEL, batch_size=32)

    err = exc_info.value
    assert err.code == EXIT_BACKEND
    assert err.kind == Kinds.BACKEND_MODEL_DOWNLOAD_FAILED
    assert err.detail is not None
    assert "simulated download failure" in str(err.detail["cause"])
    assert err.detail["type"] == "RuntimeError"
    assert err.detail["model"] == _DEFAULT_MODEL


def test_init_wrap_preserves_from_exc_chaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``raise ... from exc`` chain is preserved on the wrapped error."""
    original = RuntimeError("simulated download failure")

    def raising_text_embedding(*_args: object, **_kwargs: object) -> object:
        raise original

    monkeypatch.setattr(
        "code_index.embeddings.fastembed.TextEmbedding",
        raising_text_embedding,
    )

    with pytest.raises(CodeIndexError) as exc_info:
        FastembedBackend(model=_DEFAULT_MODEL, batch_size=32)

    assert exc_info.value.__cause__ is original


def test_from_config_wraps_constructor_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``from_config`` wraps a ``FastembedBackend(...)`` failure as model-download-failed."""

    def raising_init(
        self: FastembedBackend,
        model: str,
        batch_size: int = 32,
        cache_dir: str | None = None,
        device: str | None = None,
    ) -> None:
        raise RuntimeError("simulated init failure")

    monkeypatch.setattr(FastembedBackend, "__init__", raising_init)

    config = _make_config()

    with pytest.raises(CodeIndexError) as exc_info:
        from_config(config)

    err = exc_info.value
    assert err.code == EXIT_BACKEND
    assert err.kind == Kinds.BACKEND_MODEL_DOWNLOAD_FAILED
    assert err.detail is not None
    assert "simulated init failure" in str(err.detail["cause"])
    assert err.detail["type"] == "RuntimeError"
    assert err.detail["model"] == _DEFAULT_MODEL


def test_from_config_passes_through_code_index_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``CodeIndexError`` raised inside ``FastembedBackend.__init__`` is not re-wrapped."""
    inner = CodeIndexError(
        code=EXIT_BACKEND,
        kind=Kinds.BACKEND_MODEL_DOWNLOAD_FAILED,
        message="already wrapped from init",
    )

    def raising_init(
        self: FastembedBackend,
        model: str,
        batch_size: int = 32,
        cache_dir: str | None = None,
        device: str | None = None,
    ) -> None:
        raise inner

    monkeypatch.setattr(FastembedBackend, "__init__", raising_init)

    config = _make_config()

    with pytest.raises(CodeIndexError) as exc_info:
        from_config(config)

    assert exc_info.value is inner
    assert exc_info.value.message == "already wrapped from init"


def test_encode_wraps_native_exception_to_encode_failed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``FastembedBackend.encode`` wraps a native error from ``_model.embed`` into the registered kind."""

    def raising_embed(_batch: list[str]) -> object:
        raise ValueError("simulated encode failure")

    stub = _StubModel(raising_embed)
    _install_noop_init(monkeypatch, stub)

    backend = FastembedBackend(model=_DEFAULT_MODEL, batch_size=32)

    with pytest.raises(CodeIndexError) as exc_info:
        backend.encode(["hello", "world"])

    err = exc_info.value
    assert err.code == EXIT_BACKEND
    assert err.kind == Kinds.BACKEND_ENCODE_FAILED
    assert err.detail is not None
    assert "simulated encode failure" in str(err.detail["cause"])
    assert err.detail["type"] == "ValueError"
    assert err.detail["model"] == backend.name
    assert err.detail["batch_size"] == 2


def test_encode_does_not_rewrap_code_index_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``CodeIndexError`` raised from inside ``_model.embed`` propagates unchanged."""
    inner = CodeIndexError(
        code=EXIT_BACKEND,
        kind=Kinds.BACKEND_ENCODE_FAILED,
        message="already wrapped",
    )

    def raising_embed(_batch: list[str]) -> object:
        raise inner

    stub = _StubModel(raising_embed)
    _install_noop_init(monkeypatch, stub)

    backend = FastembedBackend(model=_DEFAULT_MODEL, batch_size=32)

    with pytest.raises(CodeIndexError) as exc_info:
        backend.encode(["hello"])

    assert exc_info.value is inner
    assert exc_info.value.message == "already wrapped"


def test_encode_succeeds_when_embed_returns_vectors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sanity check: the wrap shell does not interfere with the happy path."""

    def happy_embed(batch: list[str]) -> list[np.ndarray]:
        return [np.zeros(768, dtype=np.float32) for _ in batch]

    stub = _StubModel(happy_embed)
    _install_noop_init(monkeypatch, stub)

    backend = FastembedBackend(model=_DEFAULT_MODEL, batch_size=32)
    result = backend.encode(["a", "b", "c"])
    assert result.shape == (3, 768)


def test_wrapped_envelope_round_trips_through_json_loads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The error envelope from a wrapped failure survives ``json.dumps`` / ``json.loads``."""

    def raising_text_embedding(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("simulated download failure")

    monkeypatch.setattr(
        "code_index.embeddings.fastembed.TextEmbedding",
        raising_text_embedding,
    )

    with pytest.raises(CodeIndexError) as exc_info:
        FastembedBackend(model=_DEFAULT_MODEL, batch_size=32)

    envelope = exc_info.value.envelope()
    document = json.dumps(envelope)
    round_tripped = json.loads(document)

    assert round_tripped["error"]["code"] == 20
    assert round_tripped["error"]["kind"] == "backend.model_download_failed"


def test_wrapped_encode_envelope_round_trips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The encode-failure envelope also survives the JSON round-trip."""

    def raising_embed(_batch: list[str]) -> object:
        raise ValueError("simulated encode failure")

    stub = _StubModel(raising_embed)
    _install_noop_init(monkeypatch, stub)

    backend = FastembedBackend(model=_DEFAULT_MODEL, batch_size=32)

    with pytest.raises(CodeIndexError) as exc_info:
        backend.encode(["hello"])

    envelope = exc_info.value.envelope()
    document = json.dumps(envelope)
    round_tripped = json.loads(document)

    assert round_tripped["error"]["code"] == 20
    assert round_tripped["error"]["kind"] == "backend.encode_failed"


class _CapturingTextEmbedding:
    """Stub for ``fastembed.TextEmbedding`` that records construction kwargs.

    Records the kwargs the production ``__init__`` passes (notably the
    provider selection) and exposes the nested
    ``model.tokenizer.enable_truncation`` attribute path the truncation
    override touches, so real construction proceeds without a download.
    """

    last_kwargs: dict[str, object] | None = None

    class model:  # noqa: N801 - mirror fastembed's nested attribute path
        class tokenizer:
            @staticmethod
            def enable_truncation(*_args: object, **_kwargs: object) -> None:
                return None

    def __init__(self, *args: object, **kwargs: object) -> None:
        type(self).last_kwargs = kwargs

    @staticmethod
    def get_embedding_size(_model: str) -> int:
        return 768


def _install_capturing_text_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> type[_CapturingTextEmbedding]:
    """Replace the real ``TextEmbedding`` with the capturing stub."""
    _CapturingTextEmbedding.last_kwargs = None
    monkeypatch.setattr(fastembed_module, "TextEmbedding", _CapturingTextEmbedding)
    return _CapturingTextEmbedding


def test_init_cuda_passes_cuda_provider_and_sets_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolved ``cuda`` constructs with the CUDA provider and device=='cuda'."""
    monkeypatch.setattr(
        device_module,
        "available_providers",
        lambda: [CUDA_PROVIDER, "CPUExecutionProvider"],
    )
    captured = _install_capturing_text_embedding(monkeypatch)

    backend = FastembedBackend(model=_DEFAULT_MODEL, batch_size=32, device="cuda")

    assert backend.device == "cuda"
    assert captured.last_kwargs is not None
    providers = captured.last_kwargs.get("providers")
    assert isinstance(providers, list)
    assert CUDA_PROVIDER in providers


def test_init_cpu_omits_cuda_provider_and_sets_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolved ``cpu`` constructs without the CUDA provider and device=='cpu'."""
    monkeypatch.setattr(
        device_module,
        "available_providers",
        lambda: ["CPUExecutionProvider"],
    )
    captured = _install_capturing_text_embedding(monkeypatch)

    backend = FastembedBackend(model=_DEFAULT_MODEL, batch_size=32, device="cpu")

    assert backend.device == "cpu"
    assert captured.last_kwargs is not None
    # CPU path passes no CUDA provider (providers defaults to None — fastembed's
    # CPU-default construction, behaviorally unchanged from before this step).
    assert captured.last_kwargs.get("providers") is None


def test_init_cuda_unavailable_falls_back_to_cpu_with_warning(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``device='cuda'`` with no provider → CPU, no provider kwarg, one warning."""
    monkeypatch.setattr(
        device_module,
        "available_providers",
        lambda: ["CPUExecutionProvider"],
    )
    captured = _install_capturing_text_embedding(monkeypatch)

    backend = FastembedBackend(model=_DEFAULT_MODEL, batch_size=32, device="cuda")

    assert backend.device == "cpu"
    assert captured.last_kwargs is not None
    assert captured.last_kwargs.get("providers") is None

    err = capsys.readouterr().err
    # Exactly one fallback warning line mentioning the env var and CPU fallback.
    warning_lines = [line for line in err.splitlines() if "CODE_INDEX_DEVICE" in line]
    assert len(warning_lines) == 1


def test_voyage_branch_still_raises_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-existing Voyage stub raises ``CLI_NOT_IMPLEMENTED`` and is not re-wrapped.

    The factory's new wrap layer must be a no-op for the Voyage stub's
    ``CodeIndexError`` — the ``except CodeIndexError: raise`` clause covers
    this, but the Voyage branch is not even inside the fastembed try-block,
    so this is more of an integration smoke test than a wrap test.
    """
    # The voyage branch is reached only when embed_backend == "voyage";
    # FastembedBackend should never be constructed. Use a spy to confirm.
    sentinel: dict[str, object] = {"called": False}

    def tripwire_init(*_args: object, **_kwargs: object) -> None:
        sentinel["called"] = True

    monkeypatch.setattr(factory_module.FastembedBackend, "__init__", tripwire_init)

    config = _make_config(embed_backend="voyage", embed_model="voyage-code-3")
    with pytest.raises(CodeIndexError) as exc_info:
        from_config(config)

    assert exc_info.value.kind == Kinds.CLI_NOT_IMPLEMENTED
    assert sentinel["called"] is False
