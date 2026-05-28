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
    # Phase 7 (feature 007 step 001) replaced the Phase 1 ``key = value``
    # text format with two ``key: value`` stanzas under ``config:`` and
    # ``index:`` headers. With no index built against the fixture, the
    # ``index`` block reads ``not built``.
    assert "embed_backend: fastembed" in out
    assert "embed_model: jinaai/jina-embeddings-v2-base-code" in out
    assert "index: not built" in out
    # Phase 8 (feature 008 step 004) appends a ``device:`` stanza carrying
    # ``requested_device``/``effective_device`` (top-level JSON siblings, not
    # config keys). Scope the sorted-keys check to the ``config:`` stanza so it
    # keeps asserting config-key ordering, not the device lines.
    assert "device:" in out
    assert "requested_device:" in out
    assert "effective_device:" in out
    # Keys inside the ``config`` block are sorted alphabetically.
    lines: list[str] = out.splitlines()
    config_start: int = lines.index("config:")
    config_keys: list[str] = []
    for line in lines[config_start + 1 :]:
        if not (line.startswith("  ") and ":" in line):
            break
        config_keys.append(line.strip().split(":", 1)[0])
    assert config_keys == sorted(config_keys)
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
#
# All MVP subcommands have real implementations as of Phase 6 step 004 —
# ``init`` / ``index build`` (Phase 4 steps 002 / 004), ``search`` (Phase 5
# step 002), ``index sync`` / ``index rebuild`` / ``symbols defs|refs`` /
# ``graph callers|deps`` (Phase 6 steps 001 / 002 / 003 / 004). With no
# remaining stubs there is nothing to assert here; the ``_stub`` helper and
# ``Kinds.CLI_NOT_IMPLEMENTED`` constant are still exercised by their
# direct callers in earlier-phase tests and by ``code_index.errors`` unit
# tests. If a future phase reintroduces a stub, restore the parametrize
# block.
# ---------------------------------------------------------------------------


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
