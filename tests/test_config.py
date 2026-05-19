"""Tests for the per-project config loader.

Each test asserts the externally visible contract from
``docs/architecture/errors-and-exit-codes.md`` Config section: exit ``code``,
dotted ``kind``, and (where the doc pins them) keys in ``detail``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_index.config import (
    ALLOWED_BACKENDS,
    BACKEND_DEFAULT_MODEL,
    DEFAULT_LANGUAGES,
    CodeIndexConfig,
    load_config,
)
from code_index.errors import EXIT_CONFIG, CodeIndexError, Kinds

FIXTURES = Path(__file__).parent / "fixtures"


def _write(tmp_path: Path, name: str, body: str) -> Path:
    """Write ``body`` to ``tmp_path/name`` and return the path."""
    target = tmp_path / name
    target.write_text(body, encoding="utf-8")
    return target


def test_valid_config_loads(tmp_path: Path) -> None:
    cfg = load_config(
        FIXTURES / "config_valid.toml",
        project_root=tmp_path,
        engine_version="0.1.0",
    )
    assert isinstance(cfg, CodeIndexConfig)
    assert cfg.version == ">=0.1,<1.0"
    assert cfg.project == "demo"
    assert cfg.roots == ["."]
    assert cfg.ignores == ["**/snapshots/**"]
    assert cfg.languages == ["python", "typescript"]
    assert cfg.extra_languages == []
    assert cfg.embed_backend == "fastembed"
    assert cfg.embed_model == "jinaai/jina-embeddings-v2-base-code"
    assert cfg.embed_batch_size == 16


def test_defaults_applied(tmp_path: Path) -> None:
    minimal = _write(
        tmp_path,
        "minimal.toml",
        '[code_index]\nversion = ">=0.1,<1.0"\n',
    )
    cfg = load_config(minimal, project_root=tmp_path, engine_version="0.1.0")
    assert cfg.roots == ["."]
    assert cfg.ignores == []
    assert cfg.languages == list(DEFAULT_LANGUAGES)
    assert cfg.embed_backend == "fastembed"
    assert cfg.embed_model == BACKEND_DEFAULT_MODEL["fastembed"]
    assert cfg.embed_batch_size == 32


def test_project_default_is_dirname(tmp_path: Path) -> None:
    project_root = tmp_path / "my-project"
    project_root.mkdir()
    cfg_file = _write(
        project_root,
        "c.toml",
        '[code_index]\nversion = ">=0.1,<1.0"\n',
    )
    cfg = load_config(cfg_file, project_root=project_root, engine_version="0.1.0")
    assert cfg.project == "my-project"


def test_embed_model_default_per_backend(tmp_path: Path) -> None:
    voyage = _write(
        tmp_path,
        "voyage.toml",
        '[code_index]\nversion = ">=0.1,<1.0"\nembed_backend = "voyage"\n',
    )
    cfg_v = load_config(voyage, project_root=tmp_path, engine_version="0.1.0")
    assert cfg_v.embed_backend == "voyage"
    assert cfg_v.embed_model == "voyage-code-3"

    fast = _write(
        tmp_path,
        "fast.toml",
        '[code_index]\nversion = ">=0.1,<1.0"\nembed_backend = "fastembed"\n',
    )
    cfg_f = load_config(fast, project_root=tmp_path, engine_version="0.1.0")
    assert cfg_f.embed_backend == "fastembed"
    assert cfg_f.embed_model == "jinaai/jina-embeddings-v2-base-code"

    # Sanity: ALLOWED_BACKENDS matches the keys we just exercised.
    assert set(ALLOWED_BACKENDS) == set(BACKEND_DEFAULT_MODEL.keys())


def test_malformed_toml_raises(tmp_path: Path) -> None:
    with pytest.raises(CodeIndexError) as excinfo:
        load_config(
            FIXTURES / "config_malformed.toml",
            project_root=tmp_path,
            engine_version="0.1.0",
        )
    assert excinfo.value.code == EXIT_CONFIG
    assert excinfo.value.kind == Kinds.CONFIG_PARSE_ERROR


def test_missing_version_raises(tmp_path: Path) -> None:
    with pytest.raises(CodeIndexError) as excinfo:
        load_config(
            FIXTURES / "config_missing_version.toml",
            project_root=tmp_path,
            engine_version="0.1.0",
        )
    assert excinfo.value.code == EXIT_CONFIG
    assert excinfo.value.kind == Kinds.CONFIG_MISSING_KEY


def test_version_mismatch_raises(tmp_path: Path) -> None:
    with pytest.raises(CodeIndexError) as excinfo:
        load_config(
            FIXTURES / "config_version_mismatch.toml",
            project_root=tmp_path,
            engine_version="0.1.0",
        )
    err = excinfo.value
    assert err.code == EXIT_CONFIG
    assert err.kind == Kinds.CONFIG_VERSION_MISMATCH
    assert err.detail is not None
    assert err.detail.get("pin") == ">=99.0"
    assert err.detail.get("engine_version") == "0.1.0"


def test_bad_enum_raises(tmp_path: Path) -> None:
    with pytest.raises(CodeIndexError) as excinfo:
        load_config(
            FIXTURES / "config_bad_enum.toml",
            project_root=tmp_path,
            engine_version="0.1.0",
        )
    assert excinfo.value.code == EXIT_CONFIG
    assert excinfo.value.kind == Kinds.CONFIG_BAD_ENUM


def test_bad_path_roots_raises(tmp_path: Path) -> None:
    with pytest.raises(CodeIndexError) as excinfo:
        load_config(
            FIXTURES / "config_bad_path.toml",
            project_root=tmp_path,
            engine_version="0.1.0",
        )
    assert excinfo.value.code == EXIT_CONFIG
    assert excinfo.value.kind == Kinds.CONFIG_BAD_PATH


def test_bad_path_extra_languages_raises(tmp_path: Path) -> None:
    cfg_file = _write(
        tmp_path,
        "extra.toml",
        '[code_index]\n'
        'version = ">=0.1,<1.0"\n'
        'extra_languages = ["./nope_plugin.py"]\n',
    )
    with pytest.raises(CodeIndexError) as excinfo:
        load_config(cfg_file, project_root=tmp_path, engine_version="0.1.0")
    assert excinfo.value.code == EXIT_CONFIG
    assert excinfo.value.kind == Kinds.CONFIG_BAD_PATH


def test_unknown_language_raises(tmp_path: Path) -> None:
    cfg_file = _write(
        tmp_path,
        "klingon.toml",
        '[code_index]\nversion = ">=0.1,<1.0"\nlanguages = ["klingon"]\n',
    )
    with pytest.raises(CodeIndexError) as excinfo:
        load_config(cfg_file, project_root=tmp_path, engine_version="0.1.0")
    assert excinfo.value.code == EXIT_CONFIG
    assert excinfo.value.kind == Kinds.CONFIG_UNKNOWN_LANGUAGE


def test_unknown_key_warns_not_raises(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cfg = load_config(
        FIXTURES / "config_unknown_key.toml",
        project_root=tmp_path,
        engine_version="0.1.0",
    )
    # Loader returns successfully — no raise.
    assert isinstance(cfg, CodeIndexConfig)
    captured = capsys.readouterr()
    # Warning on stderr names the unknown key; stdout is untouched.
    assert "mystery_key" in captured.err
    assert captured.out == ""
