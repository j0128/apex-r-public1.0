"""Ensure shared Apex-R modules are importable from desktop / colab / mobile."""

from __future__ import annotations

import sys
from pathlib import Path


def ensure_shared() -> Path:
    shared = Path(__file__).resolve().parent
    shared_str = str(shared)
    if shared_str not in sys.path:
        sys.path.insert(0, shared_str)
    return shared
