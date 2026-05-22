"""Tests for ``code_index init --format json`` (Phase 7, step 002).

Covers the six DoD test cases from
``docs/plans/007.config-show-json-polish/002.init-json.md``:

1. Fresh init, JSON mode -> four-key document, ``force_used`` is False,
   stderr empty.
2. ``--name`` propagates into the ``project`` field.
3. ``--force`` against a populated dir -> ``force_used`` is True.
4. ``--force`` against an empty dir -> ``force_used`` is False.
5. Refuse without ``--force`` -> error envelope on stdout under JSON mode,
   round-trips through ``json.loads``.
6. Text mode unchanged from Phase 4.

The success-path cases drive the CLI through :class:`typer.testing.CliRunner`
(matches the step-file spec and Phase 4's `tests/test_cli_init.py` style).
The refuse-path case routes through :func:`code_index.cli._invoke` so the
:class:`BoundaryTyper.__call__` boundary handler emits the JSON envelope to
stdout; ``CliRunner`` bypasses that wrapper and yields a raw Click exit code
instead of an envelope (same pattern as
``tests/test_cli_init.py::test_refuses_overwrite_without_force`` and
``tests/test_index_build_cli.py::test_no_config_found_errors_with_init_hint``).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from code_index.cli import _invoke, app


def _helpers(tmp_path: Path) -> tuple[Path, Path]:
    """Return the expected ``(config.toml, .gitignore)`` paths under tmp_path."""
    helpers_dir: Path = tmp_path / "docs" / ".helpers"
    return helpers_dir / "config.toml", helpers_dir / ".gitignore"


def test_fresh_init_json_shape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init --format json`` against an empty dir emits the four-key shape."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["--format", "json", "init"])
    assert result.exit_code == 0, result.stderr

    payload: dict[str, Any] = json.loads(result.stdout)
    assert set(payload.keys()) == {
        "config_path",
        "gitignore_path",
        "project",
        "force_used",
    }

    config_path: str = payload["config_path"]
    gitignore_path: str = payload["gitignore_path"]
    # Absolute path strings with forward slashes (per 002.context.md "Path
    # string format"). No Windows backslashes.
    assert "\\" not in config_path
    assert "\\" not in gitignore_path
    assert config_path.endswith("docs/.helpers/config.toml")
    assert gitignore_path.endswith("docs/.helpers/.gitignore")
    # Absolute (POSIX or drive-letter prefixed).
    assert Path(config_path).is_absolute()
    assert Path(gitignore_path).is_absolute()

    assert payload["project"] == tmp_path.resolve().name
    assert payload["force_used"] is False

    # JSON mode keeps stderr empty on success — no progress chatter.
    assert result.stderr == ""


def test_name_flag_propagates_to_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init --format json --name custom-name`` sets ``project`` to the flag value."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    result = runner.invoke(
        app, ["--format", "json", "init", "--name", "custom-name"]
    )
    assert result.exit_code == 0, result.stderr

    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["project"] == "custom-name"


def test_force_against_populated_dir_sets_force_used_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init --force`` against a populated dir reports ``force_used == True``."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0, first.stderr

    config_path, _ = _helpers(tmp_path)
    assert config_path.is_file()

    second = runner.invoke(app, ["--format", "json", "init", "--force"])
    assert second.exit_code == 0, second.stderr

    payload: dict[str, Any] = json.loads(second.stdout)
    assert payload["force_used"] is True


def test_force_against_empty_dir_keeps_force_used_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init --force`` against an empty dir reports ``force_used == False``.

    The flag was passed but no prior file existed; nothing was overwritten,
    so ``force_used`` stays false (see 002.context.md "force_used definition").
    """
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["--format", "json", "init", "--force"])
    assert result.exit_code == 0, result.stderr

    payload: dict[str, Any] = json.loads(result.stdout)
    assert payload["force_used"] is False


def test_refuse_without_force_emits_json_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Second ``init`` (no ``--force``) under JSON mode emits an error envelope.

    Routes through :func:`code_index.cli._invoke` so the boundary handler
    fires; ``CliRunner`` bypasses it. The test asserts the envelope structure
    (``{"error": {"code", "kind", "message", "detail"}}``) and that the
    envelope round-trips through :func:`json.loads`; the specific ``kind``
    is Phase 4's choice (``cli.not_implemented``) and is asserted here to
    catch any inadvertent regression of that contract.
    """
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    first = runner.invoke(app, ["init"])
    assert first.exit_code == 0, first.stderr

    capsys.readouterr()
    exit_code: int = _invoke(["--format", "json", "init"])
    captured = capsys.readouterr()

    assert exit_code != 0
    envelope: dict[str, Any] = json.loads(captured.out)
    assert "error" in envelope
    error: dict[str, Any] = envelope["error"]
    assert set(error.keys()) >= {"code", "kind", "message", "detail"}
    # Phase 4's pinned choice for the refuse path (see Phase 4's
    # `002.context.md` and `tests/test_cli_init.py`).
    assert error["kind"] == "cli.not_implemented"
    assert error["code"] == 1


def test_text_mode_unchanged_under_no_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``init`` with no ``--format`` still emits the Phase 4 single-line summary."""
    monkeypatch.chdir(tmp_path)
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["init"])
    assert result.exit_code == 0, result.stderr

    # Phase 4 text-mode shape: "wrote docs/.helpers/config.toml\n".
    assert result.stdout.strip() == "wrote docs/.helpers/config.toml"
    # Should not be valid JSON — proves text mode is still text.
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.stdout)
