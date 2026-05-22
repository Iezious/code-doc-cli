"""Errors module — exit codes, kind registry, exception type, stream helpers.

Single source of truth for the failure surface described in
``docs/architecture/errors-and-exit-codes.md``. Consumed by config (003),
storage (004), and CLI (005). No subcommand-specific logic lives here.

Stream discipline: the four ``write_*`` helpers in this module are the only
sanctioned writers to ``sys.stdout`` / ``sys.stderr`` in the codebase.
Subcommand code must never call ``print`` directly.
"""

from __future__ import annotations

import json
import sys

# ---------------------------------------------------------------------------
# Exit-code integer constants
#
# Values mirror the table in docs/architecture/errors-and-exit-codes.md.
# Categories are spaced (10, 20, 30, 40) so new failure kinds can be inserted
# within a category without renumbering existing ones.
# ---------------------------------------------------------------------------

EXIT_OK: int = 0
EXIT_USAGE: int = 1
EXIT_CONFIG: int = 2
EXIT_INDEX_SCHEMA: int = 10
EXIT_INDEX_MODEL: int = 11
EXIT_INDEX_MISSING: int = 12
EXIT_BACKEND: int = 20
EXIT_BACKEND_AUTH: int = 21
EXIT_BACKEND_RATE_LIMIT: int = 22
EXIT_PARSING_PLUGIN: int = 30
EXIT_IO: int = 40
EXIT_IO_OVERSIZE: int = 41
EXIT_UNKNOWN: int = 99


# ---------------------------------------------------------------------------
# Kind registry
#
# Every dotted-string kind named in the "Enumerated failure surface" section
# of docs/architecture/errors-and-exit-codes.md, plus the new
# ``cli.not_implemented`` introduced by feature 001 (recorded in outcome.md).
#
# Phase 1 only raises CLI, Config and Index kinds; backend / parsing / io
# entries are listed for registry completeness so later phases do not have to
# re-edit this class.
# ---------------------------------------------------------------------------


class Kinds:
    """Registry of stable ``kind`` strings in the error envelope."""

    # CLI / usage (code 1)
    CLI_NOT_IMPLEMENTED: str = "cli.not_implemented"
    USAGE_CONFIRMATION_REQUIRED: str = "usage.confirmation_required"
    CLI_BAD_ENUM: str = "cli.bad_enum"

    # Config (code 2)
    CONFIG_PARSE_ERROR: str = "config.parse_error"
    CONFIG_MISSING_KEY: str = "config.missing_key"
    CONFIG_VERSION_MISMATCH: str = "config.version_mismatch"
    CONFIG_BAD_ENUM: str = "config.bad_enum"
    CONFIG_MODEL_BACKEND_MISMATCH: str = "config.model_backend_mismatch"
    CONFIG_BAD_PATH: str = "config.bad_path"
    CONFIG_UNKNOWN_LANGUAGE: str = "config.unknown_language"

    # Index / storage (codes 10, 12)
    INDEX_VEC_EXTENSION_UNAVAILABLE: str = "index.vec_extension_unavailable"
    INDEX_FTS5_UNAVAILABLE: str = "index.fts5_unavailable"
    INDEX_SCHEMA_MISMATCH: str = "index.schema_mismatch"
    INDEX_MISSING: str = "index.missing"
    INDEX_UNREADABLE: str = "index.unreadable"

    # Index / model (code 11)
    INDEX_EMBED_DIM_MISMATCH: str = "index.embed_dim_mismatch"
    INDEX_EMBED_MODEL_MISMATCH: str = "index.embed_model_mismatch"

    # Embedding backend (codes 20, 21, 22) — no producer in Phase 1
    BACKEND_MODEL_DOWNLOAD_FAILED: str = "backend.model_download_failed"
    BACKEND_ENCODE_FAILED: str = "backend.encode_failed"
    BACKEND_AUTH_FAILED: str = "backend.auth_failed"
    BACKEND_RATE_LIMITED: str = "backend.rate_limited"

    # Parsing (code 30) — no producer in Phase 1
    PARSING_PLUGIN_ERROR: str = "parsing.plugin_error"

    # IO (codes 40, 41) — no producer in Phase 1
    IO_PERMISSION_DENIED: str = "io.permission_denied"
    IO_DECODE_ERROR: str = "io.decode_error"
    IO_OVERSIZE: str = "io.oversize"


# ---------------------------------------------------------------------------
# Exception type and envelope
# ---------------------------------------------------------------------------


class CodeIndexError(Exception):
    """Categorized failure carrying exit code, dotted kind, message, detail."""

    code: int
    kind: str
    message: str
    detail: dict[str, object] | None

    def __init__(
        self,
        code: int,
        kind: str,
        message: str,
        detail: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.kind = kind
        self.message = message
        self.detail = detail

    def envelope(self) -> dict[str, object]:
        """Return the JSON envelope dict.

        Shape matches ``docs/architecture/errors-and-exit-codes.md``:

        ``{"error": {"code": int, "kind": str, "message": str,
        "detail": dict | None}}``.

        ``detail`` is always present as a key; ``None`` when no detail was
        supplied. Consumers that recognize the ``kind`` may inspect detail;
        others ignore it safely.
        """
        inner: dict[str, object] = {
            "code": self.code,
            "kind": self.kind,
            "message": self.message,
            "detail": self.detail,
        }
        return {"error": inner}


# ---------------------------------------------------------------------------
# Stream helpers — the only sanctioned writers to stdout/stderr.
# ---------------------------------------------------------------------------


def write_result_stdout(payload: str) -> None:
    """Write a successful result to stdout.

    Appends a trailing newline if ``payload`` does not already end with one,
    so callers can pass either a bare JSON document or human text without
    worrying about line termination. Never touches stderr.
    """
    if not payload.endswith("\n"):
        payload = payload + "\n"
    sys.stdout.write(payload)
    sys.stdout.flush()


def write_log_stderr(message: str) -> None:
    """Write a human log/warning/progress line to stderr.

    Used for progress, warnings, and human-mode error summaries. Never
    touches stdout. A trailing newline is appended if missing.
    """
    if not message.endswith("\n"):
        message = message + "\n"
    sys.stderr.write(message)
    sys.stderr.flush()


def write_json_stdout(payload: object) -> None:
    """Write a successful JSON document to stdout under ``--format json``.

    Serializes ``payload`` with ``json.dumps`` and emits exactly one JSON
    document followed by a newline. Used by subcommands that produce a
    structured success result; the error path uses
    :func:`write_error_envelope_stdout`. Never touches stderr.
    """
    document: str = json.dumps(payload, ensure_ascii=False)
    sys.stdout.write(document)
    sys.stdout.write("\n")
    sys.stdout.flush()


def write_error_envelope_stdout(err: CodeIndexError) -> None:
    """Write the JSON error envelope to stdout under ``--format json``.

    Emits exactly one JSON document followed by a newline. Never touches
    stderr; the human summary belongs to :func:`write_error_summary_stderr`.
    """
    document: str = json.dumps(err.envelope(), ensure_ascii=False)
    sys.stdout.write(document)
    sys.stdout.write("\n")
    sys.stdout.flush()


def write_error_summary_stderr(err: CodeIndexError) -> None:
    """Write a single-line human summary to stderr under ``--format text``.

    Format: ``error[<kind>]: <message>``. If ``err.detail`` is non-empty,
    each ``key: value`` pair is written as an additional indented line so
    humans can read the context without scraping JSON. Never touches stdout.
    """
    sys.stderr.write(f"error[{err.kind}]: {err.message}\n")
    if err.detail:
        for key, value in err.detail.items():
            sys.stderr.write(f"  {key}: {value}\n")
    sys.stderr.flush()
