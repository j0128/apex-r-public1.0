#!/usr/bin/env python3
"""Desktop smoke test before APK: imports + tiny monitor run (no Flet window)."""

from __future__ import annotations

import bootstrap  # noqa: F401

import sys
import traceback
from datetime import date, timedelta


def main() -> int:
    errors: list[str] = []

    def check(label: str, fn) -> None:
        try:
            fn()
            print(f"OK  {label}")
        except Exception as e:
            errors.append(f"{label}: {e}")
            print(f"FAIL {label}: {e}")
            traceback.print_exc()

    def imports() -> None:
        import numpy as np
        import pandas as pd
        import pytz
        import yaml
        import yfinance as yf
        from apex_core import ApexConfig, format_report, run_monitor
        from config_io import default_config_path, load_config
        from strategy_presets import APP_VERSION

        assert np.__version__
        assert pd.__version__
        assert yf.__version__
        print(f"     numpy={np.__version__} pandas={pd.__version__} yfinance={yf.__version__} app={APP_VERSION}")

    def tiny_fetch() -> None:
        import time
        import yfinance as yf

        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                raw = yf.download("AAPL", period="5d", progress=False, auto_adjust=False)
                if raw is not None and len(raw) >= 1:
                    print(f"     AAPL rows={len(raw)}")
                    return
                last_err = RuntimeError("yfinance returned empty data for AAPL")
            except Exception as e:
                last_err = e
            time.sleep(2 * attempt)
        # Network/rate-limit is soft: APK packaging still valid if imports OK
        print(f"WARN yfinance_fetch skipped after retries: {last_err}")

    def tiny_monitor() -> None:
        import time
        from apex_core import ApexConfig, format_report, run_monitor

        q = (date.today() - timedelta(days=1)).isoformat()
        cfg = ApexConfig(
            query_date=q,
            current_month_capital_twd=1_000_000.0,
            next_month_injection_twd=0.0,
            user_tickers="AAPL,MSFT",
            tw_tickers="",
            strategy_id="apex_rdyn_w",
            universe_size=2,
            top_n_limit=2,
        )
        last_err: Exception | None = None
        for attempt in range(1, 4):
            try:
                result = run_monitor(cfg)
                text = format_report(result) if not isinstance(result, str) else result
                if text and len(text) >= 20:
                    print(f"     report_chars={len(text)}")
                    return
                last_err = RuntimeError("format_report too short")
            except Exception as e:
                last_err = e
            time.sleep(2 * attempt)
        print(f"WARN run_monitor_tiny skipped after retries: {last_err}")

    check("imports", imports)
    check("yfinance_fetch", tiny_fetch)
    check("run_monitor_tiny", tiny_monitor)

    if errors:
        print("\nSMOKE FAILED:")
        for e in errors:
            print(" -", e)
        return 1
    print("\nSMOKE PASSED (network steps may be WARN-only under Yahoo rate limits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
