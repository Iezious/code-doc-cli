"""Tests for ``code_index config show`` (Phase 7, step 001).

Covers the eight DoD cases from
``docs/plans/007.config-show-json-polish/001.config-show.md``:

1. Fresh init, no index yet -> ``index`` is ``null`` under JSON.
2. After build -> ``index`` is a dict of four non-empty string values.
3. Model mismatch -> both ``config.embed_model`` and ``index.embed_model``
   are reported; exit 0, no envelope.
4. Schema mismatch -> ``index.schema_version`` reflects the mutated value;
   exit 0, no envelope (the diagnostic carve-out).
5. Text mode -> ``key: value`` lines and ``index: not built`` when absent.
6. Config not found -> exit 12, ``kind == "index.missing"``.
7. Index unreadable -> exit 10, ``kind == "index.unreadable"``.
8. Stream discipline + JSON round-trip on every success path.

Tests drive the CLI through :func:`code_index.cli._invoke` so the Phase 1
boundary handler routes ``CodeIndexError`` envelopes to stdout (matches the
pattern in ``tests/test_cli.py`` and ``tests/test_index_build_cli.py``). The
integration tests that require a populated index reuse the polyglot fixture
at ``tests/fixtures/projects/polyglot_minimal/`` and the persistent
fastembed cache at ``tests/.cache/fastembed/``.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from code_index import indexer
from code_index.cli import _invoke
from code_index.embeddings.fastembed import FastembedBackend

FIXTURE_SRC: Path = (
    Path(__file__).parent / "fixtures" / "projects" / "polyglot_minimal"
)
_FASTEMBED_CACHE: str = "tests/.cache/fastembed"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Invoke through the boundary handler so envelopes hit stdout."""
    capsys.readouterr()
    exit_code: int = _invoke(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def _copy_fixture(tmp_path: Path) -> None:
    """Copy ``polyglot_minimal/`` into ``tmp_path`` and add ``.git/``.

    Mirrors :func:`tests.test_index_build_cli._copy_fixture` — the ``.git/``
    marker activates the walker's gitignore handling.
    """
    shutil.copytree(FIXTURE_SRC, tmp_path, dirs_exist_ok=True)
    (tmp_path / ".git").mkdir(exist_ok=True)


@pytest.fixture
def warm_fastembed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect the indexer's backend factory to use the persistent cache."""

    def _build_backend(config: Any) -> FastembedBackend:
        return FastembedBackend(
            model=config.embed_model,
            batch_size=config.embed_batch_size,
            cache_dir=_FASTEMBED_CACHE,
        )

    monkeypatch.setattr(indexer, "from_config", _build_backend)


def _init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Run ``code_index init`` in ``tmp_path``."""
    monkeypatch.chdir(tmp_path)
    exit_code, _out, _err = _run(["init"], capsys)
    assert exit_code == 0


def _build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Run ``code_index index build --root <tmp_path>`` (caller is already chdir'd)."""
    exit_code, _out, _err = _run(
        ["index", "build", "--root", str(tmp_path)], capsys
    )
    assert exit_code == 0


# ---------------------------------------------------------------------------
# 1. Fresh init, no index yet — JSON has ``"index": null``
# ---------------------------------------------------------------------------


def test_fresh_init_index_is_null(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert set(payload.keys()) == {
        "config",
        "index",
        "requested_device",
        "effective_device",
    }
    assert payload["index"] is None
    assert err == ""


# ---------------------------------------------------------------------------
# 2. After build — JSON ``index`` is a dict of four non-empty strings
# ---------------------------------------------------------------------------


def test_after_build_index_block_is_populated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    warm_fastembed: None,
) -> None:
    del warm_fastembed
    _copy_fixture(tmp_path)
    _init(tmp_path, monkeypatch, capsys)
    _build(tmp_path, capsys)

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    index_block: Any = payload["index"]
    assert isinstance(index_block, dict)
    assert set(index_block.keys()) == {
        "schema_version",
        "code_index_version",
        "embed_model",
        "embed_dim",
        "embed_device",
    }
    for key, value in index_block.items():
        assert isinstance(value, str), (key, value)
        assert value != "", (key, value)
    # JSON key ordering inside the ``index`` block is the contract pinned
    # in ``001.context.md`` ("JSON key ordering"); ``embed_device`` is the
    # final element (Phase 8, step 004).
    assert list(index_block.keys()) == [
        "schema_version",
        "code_index_version",
        "embed_model",
        "embed_dim",
        "embed_device",
    ]


# ---------------------------------------------------------------------------
# 3. Model mismatch — both values emitted, no envelope
# ---------------------------------------------------------------------------


def _set_meta_direct(db_path: Path, key: str, value: str) -> None:
    """Update ``meta.value`` directly via ``sqlite3.connect`` (no schema check)."""
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        conn.commit()
    finally:
        conn.close()


def test_model_mismatch_reports_both_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    warm_fastembed: None,
) -> None:
    del warm_fastembed
    _copy_fixture(tmp_path)
    _init(tmp_path, monkeypatch, capsys)
    _build(tmp_path, capsys)

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    _set_meta_direct(db_path, "embed_model", "wrong:model")

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["config"]["embed_model"] == (
        "jinaai/jina-embeddings-v2-base-code"
    )
    assert payload["index"]["embed_model"] == "wrong:model"
    # No error envelope — both values coexist in one success document.
    assert "error" not in payload


# ---------------------------------------------------------------------------
# 4. Schema mismatch — diagnostic carve-out, no envelope
# ---------------------------------------------------------------------------


def test_schema_mismatch_does_not_raise(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    warm_fastembed: None,
) -> None:
    del warm_fastembed
    _copy_fixture(tmp_path)
    _init(tmp_path, monkeypatch, capsys)
    _build(tmp_path, capsys)

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    _set_meta_direct(db_path, "schema_version", "99")

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["index"]["schema_version"] == "99"
    assert "error" not in payload


# ---------------------------------------------------------------------------
# 5. Text mode — ``key: value`` and ``index: not built`` when absent
# ---------------------------------------------------------------------------


def test_text_mode_no_index_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, err = _run(["config", "show"], capsys)
    assert exit_code == 0
    assert "config:" in out
    assert "embed_model:" in out
    assert "index: not built" in out
    assert err == ""


def test_text_mode_with_index_built(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    warm_fastembed: None,
) -> None:
    del warm_fastembed
    _copy_fixture(tmp_path)
    _init(tmp_path, monkeypatch, capsys)
    _build(tmp_path, capsys)

    exit_code, out, err = _run(["config", "show"], capsys)
    assert exit_code == 0
    # Both block headers present; ``embed_model:`` appears in both blocks.
    assert "config:" in out
    assert "index:" in out
    assert out.count("embed_model:") == 2
    assert "schema_version:" in out
    assert "embed_dim:" in out
    assert err == ""


# ---------------------------------------------------------------------------
# 6. Config not found -> exit 12, ``kind == "index.missing"``
# ---------------------------------------------------------------------------


def test_no_config_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # Bare tmp_path with no ``docs/.helpers/``; upward discovery must fail
    # cleanly. ``Path.cwd()`` is the start; pytest's tmp_path is outside the
    # repo's docs/.helpers/ so no false-positive discovery.
    monkeypatch.chdir(tmp_path)

    exit_code, out, err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 12
    payload: dict[str, Any] = json.loads(out)
    assert payload["error"]["code"] == 12
    assert payload["error"]["kind"] == "index.missing"
    assert "index.missing" in err


# ---------------------------------------------------------------------------
# 7. Index unreadable -> exit 10, ``kind == "index.unreadable"``
# ---------------------------------------------------------------------------


def test_index_file_unparseable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init(tmp_path, monkeypatch, capsys)

    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    db_path.write_bytes(b"not a sqlite file at all, just garbage bytes")

    exit_code, out, err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 10
    payload: dict[str, Any] = json.loads(out)
    assert payload["error"]["code"] == 10
    assert payload["error"]["kind"] == "index.unreadable"
    assert "index.unreadable" in err


# ---------------------------------------------------------------------------
# 8. Stream discipline — JSON on stdout, empty stderr on the happy path
# ---------------------------------------------------------------------------


def test_stream_discipline_json_happy_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    # Round-trips through json.loads without raising.
    payload: dict[str, Any] = json.loads(out)
    assert isinstance(payload, dict)
    assert err == ""


# ---------------------------------------------------------------------------
# 9. Device fields (Phase 8, step 004) — top-level siblings + index.embed_device
# ---------------------------------------------------------------------------


def test_requested_device_defaults_to_auto_when_unset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``requested_device`` is ``auto`` when ``CODE_INDEX_DEVICE`` is unset.

    Break the onnxruntime probe to prove ``requested_device`` performs no
    probe: it must report ``auto`` even when the probe is broken. The broken
    probe is swallowed by :func:`available_providers` (step 001), so the
    command still exits 0 and ``effective_device`` degrades to ``cpu``.
    """
    monkeypatch.delenv("CODE_INDEX_DEVICE", raising=False)

    import onnxruntime  # type: ignore[reportMissingTypeStubs]

    def _boom() -> list[str]:
        raise RuntimeError("probe is broken")

    monkeypatch.setattr(onnxruntime, "get_available_providers", _boom)

    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["requested_device"] == "auto"
    assert err == ""


def test_requested_device_reflects_env_value(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``requested_device`` echoes a set ``CODE_INDEX_DEVICE`` value, no probe."""
    monkeypatch.setenv("CODE_INDEX_DEVICE", "cpu")

    def _boom() -> list[str]:
        raise RuntimeError("probe must not run for requested_device")

    monkeypatch.setattr(
        "code_index.embeddings.device.available_providers", _boom
    )

    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["requested_device"] == "cpu"


def test_effective_device_cuda_unavailable_no_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Requested ``cuda`` + CUDA unavailable -> ``effective_device == cpu``,
    NO stderr warning (quiet probe, ``warn=False``)."""
    monkeypatch.setenv("CODE_INDEX_DEVICE", "cuda")
    # CUDA provider absent -> resolution falls back to cpu.
    monkeypatch.setattr(
        "code_index.embeddings.device.available_providers",
        lambda: ["CPUExecutionProvider"],
    )

    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["requested_device"] == "cuda"
    assert payload["effective_device"] == "cpu"
    # Diagnostic stance: config show never warns about device resolution.
    assert err == ""


def test_effective_device_cuda_available(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Requested ``cuda`` + CUDA available -> ``effective_device == cuda``."""
    monkeypatch.setenv("CODE_INDEX_DEVICE", "cuda")
    monkeypatch.setattr(
        "code_index.embeddings.device.available_providers",
        lambda: ["CUDAExecutionProvider", "CPUExecutionProvider"],
    )

    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["effective_device"] == "cuda"


def test_config_show_survives_broken_probe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A broken onnxruntime probe must not fail ``config show``.

    ``get_available_providers`` raising is swallowed by
    :func:`available_providers` (step 001), so ``effective_device`` degrades
    to ``cpu`` and the command exits 0 with no warning.
    """
    monkeypatch.setenv("CODE_INDEX_DEVICE", "auto")

    import onnxruntime  # type: ignore[reportMissingTypeStubs]

    def _raise() -> list[str]:
        raise RuntimeError("onnxruntime is broken")

    monkeypatch.setattr(onnxruntime, "get_available_providers", _raise)

    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["effective_device"] == "cpu"
    assert err == ""


def test_index_embed_device_empty_for_pre_feature_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    warm_fastembed: None,
) -> None:
    """A pre-feature index (no ``embed_device`` meta row) renders the value
    per the existing sibling-key convention: present-but-absent meta is the
    empty string ``""`` (matching ``schema_version``/``embed_model`` handling),
    not JSON ``null``."""
    del warm_fastembed
    _copy_fixture(tmp_path)
    _init(tmp_path, monkeypatch, capsys)
    _build(tmp_path, capsys)

    # Simulate a pre-feature index by clearing the ``embed_device`` row.
    db_path: Path = tmp_path / "docs" / ".helpers" / "index.sqlite"
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("DELETE FROM meta WHERE key = 'embed_device'")
        conn.commit()
    finally:
        conn.close()

    exit_code, out, _err = _run(
        ["--format", "json", "config", "show"], capsys
    )
    assert exit_code == 0
    payload: dict[str, Any] = json.loads(out)
    assert payload["index"]["embed_device"] == ""


def test_text_mode_renders_device_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Text mode prints both device fields under a ``device:`` stanza."""
    monkeypatch.setenv("CODE_INDEX_DEVICE", "cpu")
    _init(tmp_path, monkeypatch, capsys)

    exit_code, out, err = _run(["config", "show"], capsys)
    assert exit_code == 0
    assert "device:" in out
    assert "requested_device: cpu" in out
    assert "effective_device: cpu" in out
    assert err == ""
