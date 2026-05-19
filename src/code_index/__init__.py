"""code_index — universal codebase index and hybrid retrieval CLI.

The engine is global; per-project index data lives under each target project's
`docs/.helpers/` directory. See `docs/architecture/` for design decisions.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

try:
    __version__: str = _pkg_version("code_index")
except PackageNotFoundError:  # pragma: no cover - only when running from source w/o install
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
