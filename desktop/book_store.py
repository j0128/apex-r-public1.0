"""Month-lock store for desktop entry points (GUI, daily email, committee, CLI).

Every desktop caller of run_monitor passes this store so the month-start book
is identical no matter which tool, or which day of the month, you query on.
"""

from __future__ import annotations

import bootstrap  # noqa: F401

import sys
from pathlib import Path

from locked_book import LockedBookStore


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def default_store() -> LockedBookStore:
    return LockedBookStore(_base_dir() / "locked_books")
