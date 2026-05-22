"""Tests for the ``code_index usage`` subcommand.

Covers fast feature 001 (``docs/plans/fast/001.usage-subcommand/plan.md``):

- ``code_index usage`` (no arg) prints the packaged ``USAGE.md`` index page.
- ``code_index usage <topic>`` for each of the 9 catalog names prints the
  matching markdown body under ``--format text`` and a
  ``{"topic", "content", "available"}`` document under ``--format json``.
- ``code_index usage <bad>`` raises :attr:`Kinds.CLI_BAD_ENUM` (code 1) with
  the standard error envelope.
- The packaged resource is readable from the test process — guards against
  the ``pyproject.toml`` ``force-include`` rule regressing.

Failure-path tests go through :func:`code_index.cli._invoke` so the Phase 1
boundary handler emits the JSON envelope to stdout (same pattern as
``tests/test_search_cli.py`` and ``tests/test_new_kinds.py``). Success-path
tests use :class:`typer.testing.CliRunner` like ``tests/test_init_cli.py``.
"""

from __future__ import annotations

import json
from importlib.resources import files as _resource_files
from typing import Any

import pytest
from typer.testing import CliRunner

from code_index.cli import USAGE_TOPICS, _invoke, app
from code_index.errors import Kinds


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Invoke through the boundary handler; return ``(exit_code, out, err)``."""
    capsys.readouterr()
    exit_code: int = _invoke(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_usage_no_arg_text() -> None:
    """Bare ``code_index usage`` prints the USAGE.md index page on stdout."""
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["usage"])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("# code_index"), result.stdout[:80]
    assert result.stderr == "", result.stderr


def test_usage_no_arg_json() -> None:
    """``code_index --format json usage`` returns the index-page document."""
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["--format", "json", "usage"])
    assert result.exit_code == 0, result.stderr
    parsed: dict[str, Any] = json.loads(result.stdout)
    assert parsed["topic"] == "usage"
    assert isinstance(parsed["content"], str) and parsed["content"], parsed
    assert parsed["available"] == list(USAGE_TOPICS)


def test_usage_init_text() -> None:
    """``code_index usage init`` prints the init detail page."""
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["usage", "init"])
    assert result.exit_code == 0, result.stderr
    assert result.stdout.startswith("# code_index init"), result.stdout[:80]


def test_usage_init_json_contains_marker() -> None:
    """``--format json usage init`` returns init.md content with a known marker."""
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["--format", "json", "usage", "init"])
    assert result.exit_code == 0, result.stderr
    parsed: dict[str, Any] = json.loads(result.stdout)
    assert parsed["topic"] == "init"
    # "Scaffold" is the first word of init.md's lead paragraph; stable text
    # under the move-only refactor (planner says coder picks a marker).
    assert "Scaffold" in parsed["content"], parsed["content"][:200]


@pytest.mark.parametrize("name", USAGE_TOPICS)
def test_usage_all_topics_json(name: str) -> None:
    """Every catalog name yields exit 0, matching ``topic``, non-empty content."""
    runner: CliRunner = CliRunner()
    result = runner.invoke(app, ["--format", "json", "usage", name])
    assert result.exit_code == 0, result.stderr
    parsed: dict[str, Any] = json.loads(result.stdout)
    assert parsed["topic"] == name
    assert isinstance(parsed["content"], str) and parsed["content"], parsed
    assert parsed["available"] == list(USAGE_TOPICS)


def test_usage_unknown_topic_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``--format json usage garbage`` emits a ``cli.bad_enum`` envelope, exit 1."""
    exit_code, out, _err = _run(["--format", "json", "usage", "garbage"], capsys)
    assert exit_code == 1
    parsed: dict[str, Any] = json.loads(out)
    error: dict[str, Any] = parsed["error"]
    assert error["code"] == 1
    assert error["kind"] == Kinds.CLI_BAD_ENUM
    assert error["kind"] == "cli.bad_enum"
    detail: dict[str, Any] = error["detail"]
    assert detail["flag"] == "<topic>"
    assert detail["value"] == "garbage"
    assert detail["expected"] == list(USAGE_TOPICS)


def test_usage_unknown_topic_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """``usage garbage`` (text mode): exit 1, stdout empty, stderr lists topics."""
    exit_code, out, err = _run(["usage", "garbage"], capsys)
    assert exit_code == 1
    assert out == ""
    assert "garbage" in err
    # Allowed values surface in the stderr summary so a human can self-recover.
    for name in USAGE_TOPICS:
        assert name in err, (name, err)


def test_usage_resource_present() -> None:
    """``code_index/usage/USAGE.md`` is readable as a packaged resource.

    Guards against the ``[tool.hatch.build.targets.wheel.force-include]``
    rule in ``pyproject.toml`` regressing — without that rule the built
    wheel would omit the markdown files and this test would fail under
    ``uv tool install code_index``.
    """
    resource = _resource_files("code_index") / "usage" / "USAGE.md"
    text: str = resource.read_text(encoding="utf-8")
    assert text.startswith("# code_index"), text[:80]
