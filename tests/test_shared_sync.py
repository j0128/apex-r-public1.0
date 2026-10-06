import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_shared_modules_in_sync():
    r = subprocess.run([sys.executable, str(ROOT / "check_shared_sync.py")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
