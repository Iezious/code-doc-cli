"""Smoke tests for the package skeleton (step 001).

The full subprocess invocation of ``python -m code_index --help`` is deferred
until step 005 lands the Typer app; for now we assert the module imports
without error.
"""

from __future__ import annotations

import importlib

import pytest


def test_version_is_str() -> None:
    import code_index

    assert isinstance(code_index.__version__, str)
    assert code_index.__version__ != ""


def test_module_main_imports() -> None:
    # The __main__ module must import cleanly even though it references
    # code_index.cli lazily (cli arrives in step 005).
    module = importlib.import_module("code_index.__main__")
    assert hasattr(module, "main")


@pytest.mark.xfail(strict=False, reason="cli implemented in step 005")
def test_module_main_invokes_cli() -> None:
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "code_index", "--help"],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
