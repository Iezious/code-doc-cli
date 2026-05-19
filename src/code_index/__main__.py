"""Module entry point: ``python -m code_index``.

Delegates to :data:`code_index.cli.app`. The Typer app's ``__call__`` wraps
the invocation in our boundary exception handler (see
:mod:`code_index.cli`), so calling ``app()`` here has the same surface as
the ``[project.scripts]`` entry.
"""

from __future__ import annotations

from code_index.cli import app


def main() -> None:
    """Invoke the CLI. Retained as a named entry alongside :data:`app`."""
    app()


if __name__ == "__main__":
    app()
