"""Real-download integration tests for `FastembedBackend`.

These tests hit fastembed's actual model download path on first run, populating
the persistent gitignored cache at ``tests/.cache/fastembed/``. Subsequent runs
reuse the cache and are offline-capable.

The single session-scoped ``default_backend`` fixture is the canonical entry
point. All tests use it except:

* ``test_encode_multi_batch`` constructs a second backend with the same
  ``cache_dir`` (option (b) from the step context — skips download, pays one
  extra in-memory model-load to exercise a non-default ``batch_size``).
* ``test_second_instantiation_reuses_cache`` constructs a fresh backend — that
  fresh instantiation against a warm cache is the thing under test.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from code_index.embeddings import EmbeddingBackend, FastembedBackend

_DEFAULT_MODEL = "jinaai/jina-embeddings-v2-base-code"
_CACHE_DIR = "tests/.cache/fastembed"


@pytest.fixture(scope="session")
def default_backend() -> FastembedBackend:
    """Session-scoped default-model backend.

    Instantiated once per pytest session and reused by every test that just
    needs a working backend. The cache directory is created by fastembed on
    first download; this fixture never deletes or cleans it.
    """
    return FastembedBackend(_DEFAULT_MODEL, cache_dir=_CACHE_DIR)


def _snapshot_cache(root: str) -> list[tuple[str, int]]:
    """Return a sorted list of ``(relpath, size)`` tuples for files under ``root``."""
    base = Path(root)
    out: list[tuple[str, int]] = []
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            full = Path(dirpath) / name
            rel = full.relative_to(base).as_posix()
            out.append((rel, full.stat().st_size))
    out.sort()
    return out


def test_encode_shape(default_backend: FastembedBackend) -> None:
    result = default_backend.encode(["foo", "bar"])
    assert default_backend.dim == 768
    assert result.shape == (2, default_backend.dim)


def test_encode_single_under_batch(default_backend: FastembedBackend) -> None:
    result = default_backend.encode(["only-one"])
    assert result.shape == (1, 768)


def test_encode_multi_batch() -> None:
    """Exercise the batching loop with ``batch_size=4`` (option (b))."""
    backend = FastembedBackend(_DEFAULT_MODEL, batch_size=4, cache_dir=_CACHE_DIR)
    texts = [f"snippet-{i}" for i in range(11)]  # 2 * 4 + 3
    result = backend.encode(texts)
    assert result.shape == (11, 768)
    first4 = backend.encode(texts[:4])
    assert first4.shape == (4, 768)
    assert np.allclose(result[:4], first4, atol=1e-5)


def test_encode_empty_input(default_backend: FastembedBackend) -> None:
    result = default_backend.encode([])
    assert result.shape == (0, default_backend.dim)


def test_cache_directory_populated(default_backend: FastembedBackend) -> None:
    # Forcing fixture use ensures the cache has been populated.
    _ = default_backend
    cache = Path(_CACHE_DIR)
    assert cache.exists()
    assert any(cache.rglob("*"))


def test_second_instantiation_reuses_cache(default_backend: FastembedBackend) -> None:
    # Ensure the session fixture has run and populated the cache.
    _ = default_backend
    before = _snapshot_cache(_CACHE_DIR)
    fresh = FastembedBackend(_DEFAULT_MODEL, cache_dir=_CACHE_DIR)
    after = _snapshot_cache(_CACHE_DIR)
    assert before == after
    del fresh


def test_name_format(default_backend: FastembedBackend) -> None:
    assert default_backend.name == "fastembed:jina-code-v2"


def test_satisfies_protocol(default_backend: FastembedBackend) -> None:
    assert isinstance(default_backend, EmbeddingBackend)
