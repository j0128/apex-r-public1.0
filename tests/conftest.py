import sys
from pathlib import Path

SHARED = Path(__file__).resolve().parents[1] / "shared"
sys.path.insert(0, str(SHARED))

DESKTOP = Path(__file__).resolve().parents[1] / "desktop"
sys.path.insert(0, str(DESKTOP))
