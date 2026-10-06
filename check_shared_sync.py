"""Fail if colab/modules or mobile/lib drift from shared/.

Run from project root:  python check_shared_sync.py
Fix drift with:         .\\sync_shared.ps1   (or: python check_shared_sync.py --fix)
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SHARED = ROOT / "shared"
TARGETS = [ROOT / "colab" / "modules", ROOT / "mobile" / "lib"]
# Targets deliberately left behind. mobile/lib is frozen by owner request: the
# desktop-only month-lock work (apex_core.run_monitor book_store) is not copied
# there. Remove the entry (and run --fix) when mobile is ready to catch up.
FROZEN = {ROOT / "mobile" / "lib": "mobile frozen by owner request"}
FILES = [
    "apex_core.py", "universe_builder.py", "strategy_presets.py", "config_io.py",
    "committee.py", "committee_tw.py", "allocation_sheet.py", "markets.py",
]


def main(fix: bool = False) -> int:
    drift = []
    for target in TARGETS:
        if target in FROZEN:
            print(f"skipped: {target.relative_to(ROOT)} ({FROZEN[target]})")
            continue
        for name in FILES:
            src, dst = SHARED / name, target / name
            if not dst.exists() or src.read_bytes() != dst.read_bytes():
                drift.append(dst.relative_to(ROOT))
                if fix:
                    target.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dst)
    if drift:
        verb = "fixed" if fix else "DRIFT"
        for d in drift:
            print(f"{verb}: {d}")
        return 0 if fix else 1
    print("shared/ is in sync (frozen targets skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main(fix="--fix" in sys.argv))
