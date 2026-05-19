"""Tests for code_index.errors — exit codes, envelope, stream discipline."""

from __future__ import annotations

import json

import pytest

from code_index.errors import (
    EXIT_BACKEND,
    EXIT_BACKEND_AUTH,
    EXIT_BACKEND_RATE_LIMIT,
    EXIT_CONFIG,
    EXIT_INDEX_MISSING,
    EXIT_INDEX_MODEL,
    EXIT_INDEX_SCHEMA,
    EXIT_IO,
    EXIT_IO_OVERSIZE,
    EXIT_OK,
    EXIT_PARSING_PLUGIN,
    EXIT_UNKNOWN,
    EXIT_USAGE,
    CodeIndexError,
    Kinds,
    write_error_envelope_stdout,
    write_error_summary_stderr,
    write_log_stderr,
    write_result_stdout,
)


def _sample_error() -> CodeIndexError:
    return CodeIndexError(
        EXIT_CONFIG,
        Kinds.CONFIG_VERSION_MISMATCH,
        "engine 0.5.1 does not satisfy pin '>=0.3,<0.5' in docs/.helpers/config.toml",
        {"pin": ">=0.3,<0.5", "engine_version": "0.5.1"},
    )


def test_envelope_shape() -> None:
    err = CodeIndexError(
        EXIT_CONFIG,
        Kinds.CONFIG_VERSION_MISMATCH,
        "msg",
        {"pin": ">=0.3,<0.5"},
    )
    env = err.envelope()
    assert set(env.keys()) == {"error"}
    inner = env["error"]
    assert isinstance(inner, dict)
    assert set(inner.keys()) == {"code", "kind", "message", "detail"}
    assert inner["code"] == EXIT_CONFIG
    assert inner["kind"] == "config.version_mismatch"
    assert inner["message"] == "msg"
    assert inner["detail"] == {"pin": ">=0.3,<0.5"}


def test_envelope_detail_optional() -> None:
    # Documented choice: when detail is omitted, the key is present with
    # value None. Agents that recognize the kind can read detail uniformly.
    err = CodeIndexError(EXIT_USAGE, Kinds.CLI_NOT_IMPLEMENTED, "stub")
    env = err.envelope()
    inner = env["error"]
    assert isinstance(inner, dict)
    assert "detail" in inner
    assert inner["detail"] is None


def test_envelope_writer_uses_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    err = _sample_error()
    write_error_envelope_stdout(err)
    captured = capsys.readouterr()
    assert captured.err == ""
    parsed = json.loads(captured.out)
    assert parsed == err.envelope()


def test_summary_writer_uses_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    err = _sample_error()
    write_error_summary_stderr(err)
    captured = capsys.readouterr()
    assert captured.out == ""
    # First line contains the message; further lines may follow with detail.
    first_line = captured.err.splitlines()[0]
    assert err.message in first_line


def test_result_writer_uses_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    write_result_stdout("hello\n")
    captured = capsys.readouterr()
    assert captured.out == "hello\n"
    assert captured.err == ""


def test_log_writer_uses_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    write_log_stderr("walking ...")
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "walking ..." in captured.err


def test_exit_codes_match_contract() -> None:
    # Values per docs/architecture/errors-and-exit-codes.md exit-code table.
    assert EXIT_OK == 0
    assert EXIT_USAGE == 1
    assert EXIT_CONFIG == 2
    assert EXIT_INDEX_SCHEMA == 10
    assert EXIT_INDEX_MODEL == 11
    assert EXIT_INDEX_MISSING == 12
    assert EXIT_BACKEND == 20
    assert EXIT_BACKEND_AUTH == 21
    assert EXIT_BACKEND_RATE_LIMIT == 22
    assert EXIT_PARSING_PLUGIN == 30
    assert EXIT_IO == 40
    assert EXIT_IO_OVERSIZE == 41
    assert EXIT_UNKNOWN == 99


def test_kinds_match_contract() -> None:
    # Each dotted string per the "Enumerated failure surface" section of
    # docs/architecture/errors-and-exit-codes.md, plus cli.not_implemented
    # added by feature 001.
    assert Kinds.CLI_NOT_IMPLEMENTED == "cli.not_implemented"

    assert Kinds.CONFIG_PARSE_ERROR == "config.parse_error"
    assert Kinds.CONFIG_MISSING_KEY == "config.missing_key"
    assert Kinds.CONFIG_VERSION_MISMATCH == "config.version_mismatch"
    assert Kinds.CONFIG_BAD_ENUM == "config.bad_enum"
    assert Kinds.CONFIG_MODEL_BACKEND_MISMATCH == "config.model_backend_mismatch"
    assert Kinds.CONFIG_BAD_PATH == "config.bad_path"
    assert Kinds.CONFIG_UNKNOWN_LANGUAGE == "config.unknown_language"

    assert Kinds.INDEX_VEC_EXTENSION_UNAVAILABLE == "index.vec_extension_unavailable"
    assert Kinds.INDEX_FTS5_UNAVAILABLE == "index.fts5_unavailable"
    assert Kinds.INDEX_SCHEMA_MISMATCH == "index.schema_mismatch"
    assert Kinds.INDEX_MISSING == "index.missing"
    assert Kinds.INDEX_UNREADABLE == "index.unreadable"
    assert Kinds.INDEX_EMBED_DIM_MISMATCH == "index.embed_dim_mismatch"
    assert Kinds.INDEX_EMBED_MODEL_MISMATCH == "index.embed_model_mismatch"

    assert Kinds.BACKEND_MODEL_DOWNLOAD_FAILED == "backend.model_download_failed"
    assert Kinds.BACKEND_ENCODE_FAILED == "backend.encode_failed"
    assert Kinds.BACKEND_AUTH_FAILED == "backend.auth_failed"
    assert Kinds.BACKEND_RATE_LIMITED == "backend.rate_limited"

    assert Kinds.PARSING_PLUGIN_ERROR == "parsing.plugin_error"

    assert Kinds.IO_PERMISSION_DENIED == "io.permission_denied"
    assert Kinds.IO_DECODE_ERROR == "io.decode_error"
    assert Kinds.IO_OVERSIZE == "io.oversize"
