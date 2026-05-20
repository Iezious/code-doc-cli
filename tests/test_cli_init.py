"""Tests for the ``code_index init`` subcommand (step 002 of feature 004).

Exercises the five DoD test cases from ``docs/plans/004.walker-and-build/
002.init.md``:

- fresh init writes both files (and the result round-trips through the
  Phase 1 config loader);
- a second init against the populated dir refuses with non-zero exit;
- ``--force`` overwrites the existing config;
- ``--name <value>`` sets ``project`` in the written TOML;
- ``--force`` against a populated dir whose ``.gitignore`` already matches
  the template does not error and does not rewrite the gitignore.

Tests use :class:`typer.testing.CliRunner` and ``monkeypatch.chdir`` so the
CLI's "project root = CWD" discovery resolves under ``tmp_path``. The
refuse-without-force path's ``kind`` choice — :data:`Kinds.CLI_NOT_IMPLEMENTED`
under code 1 — is the closest existing match in the Phase 1 errors module
and is documented in :func:`test_refuses_overwrite_without_force` below.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from code_index.cli import _invoke, app
from code_index.config import load_config
from code_index.errors import EXIT_USAGE, Kinds
from code_index.init import GITIGNORE_TEMPLATE, compute_version_pin


def _helpers(tmp_path: Path) -> tuple[Path, Path]:
    """Return the expected ``(config.toml, .gitignore)`` paths under tmp_path."""
    helpers_dir: Path = tmp_path / "docs" / ".helpers"
    return helpers_dir / "config.toml", helpers_dir / ".gitignore"


def test_fresh_init_writes_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init`` against an empty tmp_path writes a valid skeleton + gitignore."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stderr

    config_path, gitignore_path = _helpers(tmp_path)
    assert config_path.is_file()
    assert gitignore_path.is_file()

    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    inner = parsed["code_index"]
    for key in ("version", "project", "roots", "embed_backend", "embed_model"):
        assert key in inner, f"missing {key!r} in written config: {inner}"
    assert inner["roots"] == ["."]
    assert inner["embed_backend"] == "fastembed"
    assert inner["embed_model"] == "jinaai/jina-embeddings-v2-base-code"
    # `project` defaults to the directory basename when --name is omitted.
    assert inner["project"] == tmp_path.resolve().name

    # gitignore content matches the pinned template exactly.
    assert gitignore_path.read_text(encoding="utf-8") == GITIGNORE_TEMPLATE
    for line in ("index.sqlite", "index.sqlite-wal", "index.sqlite-shm"):
        assert line in gitignore_path.read_text(encoding="utf-8")

    # Smoke: the written config round-trips through the Phase 1 loader.
    cfg = load_config(config_path)
    assert cfg.embed_backend == "fastembed"


def test_refuses_overwrite_without_force(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Second ``init`` against a populated dir refuses; stdout empty, stderr line.

    The refuse path uses ``code = EXIT_USAGE`` paired with
    ``kind = Kinds.CLI_NOT_IMPLEMENTED``, which is the closest existing match
    in the Phase 1 errors module per ``002.context.md`` — the only registered
    ``kind`` under the usage category. Any future architectural addition of a
    dedicated kind (e.g. ``cli.refuse_clobber``) must update this assertion
    deliberately.

    The refuse path is exercised via :func:`code_index.cli._invoke` rather
    than :class:`CliRunner` because ``CliRunner`` bypasses the
    ``BoundaryTyper.__call__`` wrapper that routes :class:`CodeIndexError`
    through the stream helpers. The success path tests in this module use
    ``CliRunner`` per the step file's guidance.
    """
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0, first.stderr

    # Drain any prior capture before invoking the boundary handler.
    capsys.readouterr()
    exit_code: int = _invoke(["init"])
    captured = capsys.readouterr()
    assert exit_code == EXIT_USAGE
    assert exit_code != 0
    assert captured.out == ""
    assert "refusing to overwrite" in captured.err
    assert Kinds.CLI_NOT_IMPLEMENTED in captured.err


def test_force_overwrites_existing_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init --force`` against a populated dir succeeds and rewrites config."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0, first.stderr

    config_path, _ = _helpers(tmp_path)
    # Mutate the config so we can prove the second run rewrote it.
    config_path.write_text("[code_index]\nversion = \"bogus\"\n", encoding="utf-8")

    second = runner.invoke(app, ["init", "--force"])
    assert second.exit_code == 0, second.stderr

    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert parsed["code_index"]["embed_backend"] == "fastembed"
    # Version pin matches what `compute_version_pin` would produce for the
    # running engine — proves the rewrite went through the real renderer.
    from code_index import __version__ as engine_version

    assert parsed["code_index"]["version"] == compute_version_pin(engine_version)


def test_name_flag_sets_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init --name custom-name`` writes ``project = "custom-name"``."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["init", "--name", "custom-name"])
    assert result.exit_code == 0, result.stderr

    config_path, _ = _helpers(tmp_path)
    parsed = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert parsed["code_index"]["project"] == "custom-name"


def test_gitignore_idempotent_under_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--force`` against a populated dir does not rewrite an identical gitignore."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0, first.stderr

    _, gitignore_path = _helpers(tmp_path)
    # Record the gitignore mtime; if the second run skipped the write it
    # should be unchanged.
    pre_mtime = gitignore_path.stat().st_mtime_ns
    pre_text = gitignore_path.read_text(encoding="utf-8")
    assert pre_text == GITIGNORE_TEMPLATE

    second = runner.invoke(app, ["init", "--force"])
    assert second.exit_code == 0, second.stderr

    post_mtime = gitignore_path.stat().st_mtime_ns
    post_text = gitignore_path.read_text(encoding="utf-8")
    assert post_text == pre_text
    # mtime stable across the no-op rewrite (idempotency).
    assert post_mtime == pre_mtime
