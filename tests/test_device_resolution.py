"""Unit tests for the device-resolution helper.

No real GPU is required: the onnxruntime probe is monkeypatched (via the
module's ``available_providers`` / the underlying ``get_available_providers``)
and ``os.environ`` is controlled with ``monkeypatch``. stderr is captured with
``capsys`` to assert the single fallback warning on the requested-cuda path and
its absence on the silent paths.
"""

from __future__ import annotations

import pytest

from code_index.embeddings import device as device_mod
from code_index.errors import EXIT_CONFIG, CodeIndexError, Kinds

# ---------------------------------------------------------------------------
# requested_device — raw value, no probe
# ---------------------------------------------------------------------------


def test_requested_device_defaults_to_auto_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(device_mod.DEVICE_ENV_VAR, raising=False)
    assert device_mod.requested_device() == "auto"


@pytest.mark.parametrize("value", ["auto", "cpu", "cuda"])
def test_requested_device_returns_set_value(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(device_mod.DEVICE_ENV_VAR, value)
    assert device_mod.requested_device() == value


def test_requested_device_raises_on_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(device_mod.DEVICE_ENV_VAR, "gpu")
    with pytest.raises(CodeIndexError) as exc_info:
        device_mod.requested_device()
    err = exc_info.value
    assert err.kind == Kinds.CONFIG_BAD_ENUM
    assert err.code == EXIT_CONFIG


# ---------------------------------------------------------------------------
# available_providers / cuda_available — probe isolation
# ---------------------------------------------------------------------------


def test_cuda_available_true_when_provider_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        device_mod,
        "available_providers",
        lambda: ["CPUExecutionProvider", device_mod.CUDA_PROVIDER],
    )
    assert device_mod.cuda_available() is True


def test_cuda_available_false_when_provider_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(device_mod, "available_providers", lambda: ["CPUExecutionProvider"])
    assert device_mod.cuda_available() is False


def test_available_providers_returns_empty_when_probe_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    fake = types.ModuleType("onnxruntime")

    def _boom() -> list[str]:
        raise RuntimeError("broken onnxruntime install")

    fake.get_available_providers = _boom  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "onnxruntime", fake)

    # Must not raise; degrades to [].
    assert device_mod.available_providers() == []
    assert device_mod.cuda_available() is False


def test_available_providers_returns_empty_when_import_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import builtins

    real_import = builtins.__import__

    def _no_onnxruntime(name: str, *args: object, **kwargs: object) -> object:
        if name == "onnxruntime":
            raise ImportError("no module named onnxruntime")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(builtins, "__import__", _no_onnxruntime)
    assert device_mod.available_providers() == []


# ---------------------------------------------------------------------------
# resolve_device
# ---------------------------------------------------------------------------


def test_resolve_auto_cuda_available_is_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(device_mod, "cuda_available", lambda: True)
    assert device_mod.resolve_device("auto") == "cuda"
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_resolve_auto_cuda_unavailable_is_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(device_mod, "cuda_available", lambda: False)
    assert device_mod.resolve_device("auto") == "cpu"
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_resolve_cuda_available_no_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(device_mod, "cuda_available", lambda: True)
    assert device_mod.resolve_device("cuda") == "cuda"
    assert capsys.readouterr().err == ""


def test_resolve_cuda_unavailable_falls_back_with_single_warning(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(device_mod, "cuda_available", lambda: False)
    assert device_mod.resolve_device("cuda") == "cpu"
    captured = capsys.readouterr()
    assert captured.out == ""
    # Exactly one warning line on stderr.
    lines = [line for line in captured.err.splitlines() if line.strip()]
    assert len(lines) == 1


def test_resolve_cuda_unavailable_warn_false_is_silent(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(device_mod, "cuda_available", lambda: False)
    assert device_mod.resolve_device("cuda", warn=False) == "cpu"
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("cuda", [True, False])
def test_resolve_cpu_is_unconditional_and_silent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    cuda: bool,
) -> None:
    monkeypatch.setattr(device_mod, "cuda_available", lambda: cuda)
    assert device_mod.resolve_device("cpu") == "cpu"
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out == ""


def test_resolve_default_uses_requested_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(device_mod.DEVICE_ENV_VAR, "cpu")
    monkeypatch.setattr(device_mod, "cuda_available", lambda: True)
    # No explicit requested -> reads env via requested_device(), which is cpu.
    assert device_mod.resolve_device() == "cpu"
