#!/usr/bin/env python3
"""Apex-TW quick launcher — Taiwan-only universe + 0050.TW regime.

Examples:
  py -3 run_apex_tw.py
  py -3 run_apex_tw.py --strategy apex_tw_m
  py -3 run_apex_tw.py --refresh-universe --force-universe
  py -3 run_apex_tw.py --output apex_tw_report.txt
"""

from __future__ import annotations

import bootstrap  # noqa: F401

import argparse
import sys
from pathlib import Path

from apex_core import format_report, run_monitor
from book_store import default_store
from config_io import load_config, save_config
from strategy_presets import apply_preset, report_header_cfg
from universe_builder import (
    build_universe,
    can_refresh_universe,
    universe_refresh_status,
)


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Apex-TW 台股實驗監控")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "config_apex_tw.yaml",
        help="設定檔 (default: config_apex_tw.yaml)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=["apex_tw_rdyn", "apex_tw_m", "apex_rdyn_w", "apex_m"],
        default=None,
        help="apex_tw_rdyn=RDyn-W | apex_tw_m=R0",
    )
    parser.add_argument("--output", type=Path, default=None, help="另存報告")
    parser.add_argument("--refresh-universe", action="store_true")
    parser.add_argument("--force-universe", action="store_true")
    args = parser.parse_args()

    if not args.config.exists():
        print(f"找不到設定檔: {args.config}", file=sys.stderr)
        return 1

    cfg = load_config(args.config)
    cfg.market = "tw"
    if not (cfg.benchmark or "").strip():
        cfg.benchmark = "0050.TW"
    if args.strategy:
        cfg = apply_preset(cfg, args.strategy)
        cfg.market = "tw"
        cfg.benchmark = cfg.benchmark or "0050.TW"

    print(f"📋 策略：{report_header_cfg(cfg)} | 市場={cfg.market} | 基準={cfg.benchmark or '0050.TW'}")

    if args.refresh_universe:
        mode = cfg.universe_mode or "dollar_volume"
        allowed, reason = can_refresh_universe(
            cfg.universe_last_updated,
            cfg.query_date,
            force=args.force_universe,
        )
        print(universe_refresh_status(cfg.universe_last_updated, cfg.query_date)["message"])
        if not allowed:
            print(f"❌ 拒絕更新宇宙：{reason}", file=sys.stderr)
            print("   若仍要更新請加 --force-universe", file=sys.stderr)
            return 2

        mode_label = "成交額" if mode == "dollar_volume" else "動量"
        print(f"🔄 更新台股宇宙 (Top {cfg.universe_size}, 兩年{mode_label})…")
        result = build_universe(
            as_of=cfg.query_date,
            top_n=cfg.universe_size,
            mode=mode,
            momentum_days=cfg.universe_momentum_days,
            market="tw",
            benchmark=cfg.benchmark or "0050.TW",
        )
        # TW market stores picks in user_tickers
        cfg.user_tickers = ", ".join(result.combined)
        cfg.tw_tickers = ""
        cfg.universe_last_updated = result.as_of
        cfg.market = "tw"
        save_config(args.config, cfg)
        for line in result.summary_lines():
            print(line)
        print()

    n = len(cfg.ticker_list())
    print(f"📥 Apex-TW 啟動中... 宇宙 {n} 檔 | 查詢日 {cfg.query_date}\n")
    result = run_monitor(cfg, book_store=default_store())
    report = format_report(result, strategy_id=cfg.strategy_id, cfg=cfg)
    print(report)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"\n報告已儲存 -> {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
