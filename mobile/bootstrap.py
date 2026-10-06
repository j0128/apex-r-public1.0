"""Add shared core modules to sys.path (dev: ../shared, APK bundle: ./lib)."""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
for candidate in (_HERE / "lib", _HERE.parent / "shared"):
    if candidate.is_dir():
        path = str(candidate)
        if path not in sys.path:
            sys.path.insert(0, path)
