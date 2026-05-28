"""Device resolution for the fastembed embedding backend.

Reads and validates the machine-local ``CODE_INDEX_DEVICE`` env var, probes
onnxruntime for a CUDA execution provider, and resolves to ``cpu`` or ``cuda``.

``CODE_INDEX_DEVICE`` is the first env var the codebase reads; it is NOT a
TOML/config key and is never part of :class:`~code_index.config.CodeIndexConfig`.
See ``docs/architecture/config.md`` ("machine-local execution tuning via env")
and ``docs/architecture/embeddings.md`` ("GPU acceleration").

Two entry points are kept deliberately separate so ``config show`` can read the
raw value with no probe (:func:`requested_device`) and the resolved value with a
quiet probe (``resolve_device(warn=False)``), while the backend resolves with the
warning enabled. The onnxruntime probe is isolated so a missing or broken
onnxruntime never raises out of this module.
"""

from __future__ import annotations

import os

from code_index.errors import EXIT_CONFIG, CodeIndexError, Kinds, write_log_stderr

DEVICE_ENV_VAR: str = "CODE_INDEX_DEVICE"
VALID_DEVICES: tuple[str, ...] = ("auto", "cpu", "cuda")
CUDA_PROVIDER: str = "CUDAExecutionProvider"


def requested_device() -> str:
    """Return the raw CODE_INDEX_DEVICE value (auto|cpu|cuda), 'auto' if unset.

    No probe. Invalid values raise :class:`~code_index.errors.CodeIndexError`
    with kind ``config.bad_enum`` and exit code ``2`` (same class as a bad
    config enum from user-controlled input).
    """
    value: str = os.environ.get(DEVICE_ENV_VAR, "auto")
    if value not in VALID_DEVICES:
        raise CodeIndexError(
            code=EXIT_CONFIG,
            kind=Kinds.CONFIG_BAD_ENUM,
            message=(f"invalid {DEVICE_ENV_VAR} {value!r}; allowed: {list(VALID_DEVICES)}"),
            detail={
                "key": DEVICE_ENV_VAR,
                "value": value,
                "allowed": list(VALID_DEVICES),
            },
        )
    return value


def available_providers() -> list[str]:
    """Return onnxruntime.get_available_providers(); [] if onnxruntime is
    missing or the call raises (diagnostic stance, never propagates)."""
    try:
        import onnxruntime  # type: ignore[reportMissingTypeStubs]

        providers = onnxruntime.get_available_providers()  # type: ignore[reportUnknownMemberType]
        return [str(p) for p in providers]  # type: ignore[reportUnknownVariableType]
    except Exception:
        return []


def cuda_available() -> bool:
    """True iff CUDA_PROVIDER is in available_providers()."""
    return CUDA_PROVIDER in available_providers()


def resolve_device(requested: str | None = None, *, warn: bool = True) -> str:
    """Resolve requested (default: requested_device()) to 'cpu' or 'cuda'.

    auto -> cuda if cuda_available() else cpu (silent).
    cuda -> cuda if cuda_available() else cpu; when falling back and warn,
            emit a single clean stderr warning.
    cpu  -> cpu.
    """
    device: str = requested if requested is not None else requested_device()

    if device == "cpu":
        return "cpu"

    if device == "auto":
        return "cuda" if cuda_available() else "cpu"

    # device == "cuda"
    if cuda_available():
        return "cuda"
    if warn:
        write_log_stderr(
            f"{DEVICE_ENV_VAR}=cuda requested but the CUDA execution provider "
            "is unavailable; falling back to CPU."
        )
    return "cpu"
