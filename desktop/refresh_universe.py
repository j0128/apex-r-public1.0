#!/usr/bin/env python3
"""Refresh US investment universe. Run: py -3.13 refresh_universe.py"""

from __future__ import annotations

import bootstrap  # noqa: F401

import argparse
import sys
from pathlib import Path

from config_io import load_config, save_config
from universe_builder import (
    build_universe,
    can_refresh_universe,
    parse_ticker_csv,
    universe_refresh_status,
)


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="更新 Apex-R 美股投資宇宙（預設約兩年一次）")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "config.yaml",
        help="設定檔路徑",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default=None,
        help="基準日 (default: config query_date)",
    )
    parser.add_argument(
        "--size",
        type=int,
        default=None,
        help="美股數量 (default: config universe_size)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["dollar_volume", "momentum"],
        default=None,
        help="篩選方式 (default: config universe_mode)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="略過兩年週期閘門強制更新（不建議）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只顯示結果，不寫入設定檔",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"找不到設定檔: {args.config}", file=sys.stderr)
        return 1

    cfg = load_config(args.config)
    as_of = args.as_of or cfg.query_date
    size = args.size or cfg.universe_size
    mode = args.mode or cfg.universe_mode or "dollar_volume"
    tw = parse_ticker_csv(cfg.tw_tickers)

    allowed, reason = can_refresh_universe(cfg.universe_last_updated, as_of, force=args.force)
    print(universe_refresh_status(cfg.universe_last_updated, as_of)["message"])
    if not allowed:
        print(f"❌ 拒絕更新：{reason}", file=sys.stderr)
        print("   若仍要更新請加 --force", file=sys.stderr)
        return 2

    mode_label = "兩年成交額" if mode == "dollar_volume" else "兩年動量"
    print(f"📡 更新美股宇宙 | {mode_label} | S&P 500 流動池")
    print(f"   基準日 {as_of} | Top {size} | 台股 {len(tw)} 檔")
    if args.force:
        print("   ⚠ 強制更新模式")
    print()

    result = build_universe(
        as_of=as_of,
        top_n=size,
        tw_tickers=tw,
        mode=mode,
        momentum_days=cfg.universe_momentum_days,
    )

    for line in result.summary_lines():
        print(line)

    if args.dry_run:
        print("\n(dry-run: 未寫入 config.yaml)")
        return 0

    cfg.user_tickers = ", ".join(result.us_tickers)
    cfg.universe_last_updated = result.as_of
    cfg.universe_mode = mode
    save_config(args.config, cfg)

    print(f"\n✅ 已更新 {args.config}")
    print(f"   美股 {len(result.us_tickers)} + 台股 {len(tw)} = 宇宙 {len(result.combined)} 檔")
    print(f"   下次預設可更新日 >= {universe_refresh_status(cfg.universe_last_updated, as_of)['next_refresh']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
