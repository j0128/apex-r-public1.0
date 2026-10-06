#!/usr/bin/env python3
"""Apex-R local monitor — run: py -3.13 monitor_local.py [--config config.yaml]"""

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
    ensure_universe_cycle_stamp,
    parse_ticker_csv,
    universe_refresh_status,
)


def main() -> int:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parser = argparse.ArgumentParser(description="Apex-R 4.0 實戰監控中心（本機版）")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(__file__).parent / "config.yaml",
        help="設定檔路徑 (default: config.yaml)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        choices=[
            "apex_rdyn_w",
            "apex_r",
            "apex_m",
            "apex_opt",
            "apex_custom",
            "apex_tw_rdyn",
            "apex_tw_m",
        ],
        default=None,
        help="策略預設（含 apex_tw_* 台股實驗）",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="另存報告至文字檔",
    )
    parser.add_argument(
        "--refresh-universe",
        action="store_true",
        help="執行前更新美股宇宙（受兩年週期閘門限制）",
    )
    parser.add_argument(
        "--force-universe",
        action="store_true",
        help="搭配 --refresh-universe 強制略過兩年閘門",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"找不到設定檔: {args.config}", file=sys.stderr)
        return 1

    cfg = load_config(args.config)
    if args.strategy:
        cfg = apply_preset(cfg, args.strategy)

    print(f"📋 策略：{report_header_cfg(cfg)}")

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

        tw = parse_ticker_csv(cfg.tw_tickers)
        mode_label = "成交額" if mode == "dollar_volume" else "動量"
        market = (cfg.market or "us").strip().lower()
        market_label = "台股" if market == "tw" else "美股"
        print(f"🔄 更新{market_label}宇宙 (Top {cfg.universe_size}, 兩年{mode_label})…")
        result = build_universe(
            as_of=cfg.query_date,
            top_n=cfg.universe_size,
            tw_tickers=tw if market != "tw" else None,
            mode=mode,
            momentum_days=cfg.universe_momentum_days,
            market=market,
            benchmark=cfg.benchmark or ("0050.TW" if market == "tw" else "SPY"),
        )
        if market == "tw":
            cfg.user_tickers = ", ".join(result.combined)
            cfg.tw_tickers = ""
        else:
            cfg.user_tickers = ", ".join(result.us_tickers)
        cfg.universe_last_updated = result.as_of
        save_config(args.config, cfg)
        for line in result.summary_lines():
            print(line)
        print()
    elif parse_ticker_csv(cfg.user_tickers) and not (cfg.universe_last_updated or "").strip():
        # Migrate: stamp existing universe without rebuilding
        cfg.universe_last_updated = ensure_universe_cycle_stamp(None, cfg.query_date)
        save_config(args.config, cfg)
        print(f"📌 已為現有宇宙蓋兩年週期章：{cfg.universe_last_updated}")

    market_tag = f" | 市場 {cfg.market}" if (cfg.market or "us") != "us" else ""
    print(
        f"📥 Apex 啟動中... 宇宙 {len(cfg.ticker_list())} 檔 | 查詢日 {cfg.query_date}{market_tag}\n"
    )

    result = run_monitor(cfg, book_store=default_store())
    report = format_report(result, strategy_id=cfg.strategy_id, cfg=cfg)
    print(report)

    if args.output:
        args.output.write_text(report, encoding="utf-8")
        print(f"\n報告已儲存 -> {args.output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
