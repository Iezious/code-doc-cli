"""Module-level docstring."""

import os
import sys as system
from pathlib import Path
from . import sibling
from ..pkg import utility

CONSTANT = 1  # forces a module-body chunk to exist


def top_level() -> int:
    return CONSTANT


async def async_func():
    pass


class Widget:
    """Class docstring."""

    def method(self) -> int:
        def helper():
            return 1
        return helper()
