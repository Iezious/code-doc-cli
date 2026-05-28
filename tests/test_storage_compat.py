"""Tests for :func:`code_index.storage.verify_index_compat`.

The helper guards the search and Phase 6 query paths from running against
an index built with a different embedding model or dim than the
currently-configured backend.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from code_index.errors import CodeIndexError
from code_index.storage import open_index, set_meta, verify_index_compat


class _StubBackend:
    """Minimal :class:`EmbeddingBackend`-shaped stub."""

    def __init__(self, name: str, dim: int) -> None:
        self.name = name
        self.dim = dim
        self.device = "cpu"

    def encode(self, texts: list[str]) -> np.ndarray:  # pragma: no cover - unused
        return np.zeros((len(texts), self.dim), dtype=np.float32)


def _db_path(tmp_path: Path) -> Path:
    return tmp_path / "index.sqlite"


def test_verify_index_compat_ok(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        set_meta(conn, "embed_model", "fake:tiny")
        set_meta(conn, "embed_dim", "4")
        conn.commit()

        backend = _StubBackend("fake:tiny", 4)
        # Returns None on match.
        assert verify_index_compat(conn, backend) is None
    finally:
        conn.close()


def test_verify_index_compat_model_mismatch(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        set_meta(conn, "embed_model", "fastembed:jina-code-v2")
        set_meta(conn, "embed_dim", "768")
        conn.commit()

        backend = _StubBackend("voyage:code-3", 1024)
        with pytest.raises(CodeIndexError) as excinfo:
            verify_index_compat(conn, backend)
        assert excinfo.value.code == 11
        assert excinfo.value.kind == "index.embed_model_mismatch"
        assert "code_index index rebuild" in excinfo.value.message
    finally:
        conn.close()


def test_verify_index_compat_dim_mismatch(tmp_path: Path) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        set_meta(conn, "embed_model", "voyage:code-3")
        set_meta(conn, "embed_dim", "768")
        conn.commit()

        backend = _StubBackend("voyage:code-3", 1024)
        with pytest.raises(CodeIndexError) as excinfo:
            verify_index_compat(conn, backend)
        assert excinfo.value.code == 11
        assert excinfo.value.kind == "index.embed_dim_mismatch"
    finally:
        conn.close()


def test_verify_index_compat_missing_meta_treated_as_model_mismatch(
    tmp_path: Path,
) -> None:
    conn = open_index(_db_path(tmp_path))
    try:
        # Fresh DB: no embed_model row was ever written.
        backend = _StubBackend("fake:tiny", 4)
        with pytest.raises(CodeIndexError) as excinfo:
            verify_index_compat(conn, backend)
        assert excinfo.value.code == 11
        assert excinfo.value.kind == "index.embed_model_mismatch"
        assert "rebuild" in excinfo.value.message
    finally:
        conn.close()
