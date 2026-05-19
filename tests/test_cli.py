"""Tests for the Typer CLI scaffold (step 005).

Exercises the Phase 1 DoD (DoD-1 through DoD-7) from ``005.cli.md``:

- DoD-1: ``--help`` lists every MVP subcommand.
- DoD-2: ``config show --config <valid fixture>`` exits 0 and prints to stdout.
- DoD-3: Each Config-failure fixture produces the doc'd ``code``/``kind``
  under ``--format json``.
- DoD-4: Every stub exits 1 with ``kind = "cli.not_implemented"`` under JSON.
- DoD-5: Unhandled exception path: exit 99, ``kind = "unknown"``.
- DoD-6: Stream discipline — valid call: stdout only; broken call:
  envelope on stdout (JSON) plus summary on stderr.
- DoD-7: ``python -m code_index --help`` parity with ``code_index --help``.

The tests drive the boundary handler via :func:`code_index.cli._invoke`,
which is the same path used by the ``[project.scripts]`` entry. Direct
``CliRunner.invoke`` would bypass the handler.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from code_index import cli as cli_module
from code_index.cli import _invoke

FIXTURES = Path(__file__).parent / "fixtures"


def _run(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> tuple[int, str, str]:
    """Invoke the CLI through the boundary handler and capture streams."""
    capsys.readouterr()  # drain any prior capture
    exit_code: int = _invoke(argv)
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


# ---------------------------------------------------------------------------
# DoD-1 — `--help` lists every MVP subcommand.
# ---------------------------------------------------------------------------


def test_top_level_help_lists_mvp_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _err = _run(["--help"], capsys)
    assert code == 0
    for name in ("init", "index", "search", "symbols", "graph", "config"):
        assert name in out, f"missing {name!r} in --help: {out}"


def test_index_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = _run(["index", "--help"], capsys)
    assert code == 0
    for name in ("build", "sync", "rebuild"):
        assert name in out


def test_symbols_help_lists_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _err = _run(["symbols", "--help"], capsys)
    assert code == 0
    for name in ("defs", "refs"):
        assert name in out


def test_graph_help_lists_subcommands(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, _err = _run(["graph", "--help"], capsys)
    assert code == 0
    for name in ("callers", "deps"):
        assert name in out


def test_config_help_lists_subcommands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, _err = _run(["config", "--help"], capsys)
    assert code == 0
    assert "show" in out


# ---------------------------------------------------------------------------
# DoD-2 — `config show --config <valid>` exits 0, prints to stdout.
# ---------------------------------------------------------------------------


def test_config_show_valid_text(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(
        ["--config", str(FIXTURES / "config_valid.toml"), "config", "show"],
        capsys,
    )
    assert code == 0
    assert "embed_backend = fastembed" in out
    assert "embed_model = jinaai/jina-embeddings-v2-base-code" in out
    # Keys are sorted alphabetically.
    out_keys = [
        line.split(" = ", 1)[0] for line in out.strip().splitlines() if " = " in line
    ]
    assert out_keys == sorted(out_keys)
    # Valid fixture, no unknown keys -> stderr is empty.
    assert err == ""


def test_config_show_valid_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(
        [
            "--config",
            str(FIXTURES / "config_valid.toml"),
            "--format",
            "json",
            "config",
            "show",
        ],
        capsys,
    )
    assert code == 0
    payload: dict[str, Any] = json.loads(out)
    inner: dict[str, Any] = payload["config"]
    # Pinned Phase 1 shape (005.context.md).
    expected_keys = {
        "version",
        "project",
        "project_root",
        "config_path",
        "roots",
        "ignores",
        "languages",
        "extra_languages",
        "embed_backend",
        "embed_model",
        "embed_batch_size",
    }
    assert set(inner.keys()) == expected_keys
    assert inner["embed_backend"] == "fastembed"
    assert inner["embed_batch_size"] == 16
    assert err == ""


# ---------------------------------------------------------------------------
# DoD-3 — each Config-failure fixture produces the documented code/kind.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fixture", "expected_code", "expected_kind"),
    [
        ("config_malformed.toml", 2, "config.parse_error"),
        ("config_missing_version.toml", 2, "config.missing_key"),
        ("config_version_mismatch.toml", 2, "config.version_mismatch"),
        ("config_bad_enum.toml", 2, "config.bad_enum"),
        ("config_bad_path.toml", 2, "config.bad_path"),
    ],
)
def test_config_show_failure_envelope(
    fixture: str,
    expected_code: int,
    expected_kind: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(
        [
            "--config",
            str(FIXTURES / fixture),
            "--format",
            "json",
            "config",
            "show",
        ],
        capsys,
    )
    assert code == expected_code
    payload: dict[str, Any] = json.loads(out)
    assert payload["error"]["code"] == expected_code
    assert payload["error"]["kind"] == expected_kind
    # Human summary mirrors the envelope on stderr.
    assert expected_kind in err


# ---------------------------------------------------------------------------
# DoD-4 — every stub exits 1 with kind = "cli.not_implemented".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["init"],
        ["index", "build"],
        ["index", "sync"],
        ["index", "rebuild"],
        ["search", "foo"],
        ["symbols", "defs", "foo"],
        ["symbols", "refs", "foo"],
        ["graph", "callers", "foo"],
        ["graph", "deps", "foo"],
    ],
)
def test_stub_subcommands_envelope(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _err = _run(["--format", "json", *argv], capsys)
    assert code == 1
    payload: dict[str, Any] = json.loads(out)
    assert payload["error"]["code"] == 1
    assert payload["error"]["kind"] == "cli.not_implemented"


def test_stub_text_mode_stderr_only(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(["init"], capsys)
    assert code == 1
    # Text mode: nothing on stdout, summary on stderr.
    assert out == ""
    assert "cli.not_implemented" in err


# ---------------------------------------------------------------------------
# DoD-5 — unhandled exception path: exit 99, kind="unknown".
# ---------------------------------------------------------------------------


def test_unhandled_exception_envelope(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Force a non-CodeIndexError inside config loading.

    We monkeypatch ``code_index.cli.load_config`` to raise a bare
    ``RuntimeError``; the boundary handler must synthesize an envelope with
    ``code=99`` and the kind string :data:`code_index.cli._UNKNOWN_KIND`
    (chosen as ``"unknown"`` per ``005.cli.md`` DoD-5; documented in
    ``cli.py``).
    """

    def boom(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(cli_module, "load_config", boom)
    code, out, err = _run(
        [
            "--config",
            str(FIXTURES / "config_valid.toml"),
            "--format",
            "json",
            "config",
            "show",
        ],
        capsys,
    )
    assert code == 99
    payload: dict[str, Any] = json.loads(out)
    assert payload["error"]["code"] == 99
    assert payload["error"]["kind"] == "unknown"
    assert "unknown" in err


# ---------------------------------------------------------------------------
# DoD-6 — stream discipline.
# ---------------------------------------------------------------------------


def test_stream_discipline_valid_call(capsys: pytest.CaptureFixture[str]) -> None:
    code, out, err = _run(
        ["--config", str(FIXTURES / "config_valid.toml"), "config", "show"],
        capsys,
    )
    assert code == 0
    assert out != ""
    assert err == ""


def test_stream_discipline_broken_call_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(
        [
            "--config",
            str(FIXTURES / "config_malformed.toml"),
            "--format",
            "json",
            "config",
            "show",
        ],
        capsys,
    )
    assert code == 2
    # Envelope on stdout.
    payload: dict[str, Any] = json.loads(out)
    assert "error" in payload
    # Summary on stderr.
    assert "config.parse_error" in err


def test_stream_discipline_broken_call_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code, out, err = _run(
        [
            "--config",
            str(FIXTURES / "config_malformed.toml"),
            "config",
            "show",
        ],
        capsys,
    )
    assert code == 2
    # Text mode: stdout stays empty on failure.
    assert out == ""
    assert "config.parse_error" in err


# ---------------------------------------------------------------------------
# DoD-7 — `python -m code_index --help` parity.
# ---------------------------------------------------------------------------


def test_module_main_help_parity() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "code_index", "--help"],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 0
    for name in ("init", "index", "search", "symbols", "graph", "config"):
        assert name in result.stdout
