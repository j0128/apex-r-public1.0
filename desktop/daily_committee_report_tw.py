#!/usr/bin/env python3
"""AI 台股投資委員會日報 → Gmail（0050 錨 × R0 × RDyn-W）。

席次：錨定 0050 ＋ 基準 Apex-TW R0 ＋ 衛星 Apex-TW RDyn-W
含：個股消息、總經分析、配置 CSV、寄信。

Usage:
  py -3.13 daily_committee_report_tw.py
  py -3.13 daily_committee_report_tw.py --dry-run
  py -3.13 daily_committee_report_tw.py --date 2026-09-23 --via gmail
"""

from __future__ import annotations

import bootstrap  # noqa: F401

import argparse
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

from allocation_sheet import write_committee_tw_next_csv, write_engine_allocation_csvs
from apex_core import format_report, run_monitor
from book_store import default_store
from briefing import build_briefing
from briefing.market_snapshot import format_macro_analysis
from briefing.news_watchlist import fetch_news, summarize
from briefing.watchlist import TIER_HOLDING, WatchItem
from committee_tw import build_committee_tw_minutes, excerpt_tw_briefing
from config_io import load_config, save_config
from daily_email_report import (
    DESKTOP,
    dispatch_email,
    last_us_session_date,
    load_mail_address,
)
from strategy_presets import report_header_cfg


def _reconfigure_stdio() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def _anchor_news_block(query_hint: str = "") -> str:
    """強制附上 0050 錨定委員消息一行。"""
    _ = query_hint
    ticker = "0050.TW"
    news = fetch_news(ticker, limit=3)
    item = WatchItem(ticker=ticker, tier=TIER_HOLDING)
    # summarize needs PriceChange optional — pass None
    line = summarize(item, news, None)
    return f"【錨定袖 0050】\n{line}"


def main() -> int:
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(description="AI 台股投資委員會日報 → Gmail")
    parser.add_argument(
        "--config-m",
        type=Path,
        default=DESKTOP / "config_apex_tw_m.yaml",
        help="Apex-TW R0 設定",
    )
    parser.add_argument(
        "--config-r",
        type=Path,
        default=DESKTOP / "config_apex_tw.yaml",
        help="Apex-TW RDyn-W 設定",
    )
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--via", choices=["gmail", "draft", "smtp"], default="gmail")
    parser.add_argument("--no-save-config", action="store_true")
    args = parser.parse_args()

    if args.date:
        qdate = args.date
    else:
        # 台股收盤後：取最近一個平日（與美股日報同一規則即可）
        qdate = last_us_session_date().isoformat()

    cfg_m = replace(load_config(args.config_m), query_date=qdate)
    cfg_r = replace(load_config(args.config_r), query_date=qdate)
    cfg_m.market = "tw"
    cfg_r.market = "tw"
    if not (cfg_m.benchmark or "").strip():
        cfg_m.benchmark = "0050.TW"
    if not (cfg_r.benchmark or "").strip():
        cfg_r.benchmark = "0050.TW"

    if not args.no_save_config:
        save_config(args.config_m, cfg_m)
        save_config(args.config_r, cfg_r)

    print(f"查詢日：{qdate}", flush=True)
    print(f"基準 R0：{report_header_cfg(cfg_m)}", flush=True)
    print(f"衛星 RDyn：{report_header_cfg(cfg_r)}", flush=True)
    print("錨定：0050.TW", flush=True)

    print("執行 Apex-TW R0 monitor…", flush=True)
    m_result = run_monitor(cfg_m, book_store=default_store())
    m_report = format_report(m_result, strategy_id=cfg_m.strategy_id, cfg=cfg_m)

    print("執行 Apex-TW RDyn-W monitor…", flush=True)
    r_result = run_monitor(cfg_r, book_store=default_store())
    r_report = format_report(r_result, strategy_id=cfg_r.strategy_id, cfg=cfg_r)

    print("產生 R0 市場簡報（個股消息）…", flush=True)
    m_briefing = build_briefing(
        m_result,
        cfg_m,
        deep_dive_threshold_pct=7.0,
        progress=lambda s: print(f"  {s}", flush=True),
    )
    print("產生 RDyn 市場簡報…", flush=True)
    r_briefing = build_briefing(
        r_result,
        cfg_r,
        deep_dive_threshold_pct=7.0,
        progress=lambda s: print(f"  {s}", flush=True),
    )

    print("組裝總經分析…", flush=True)
    macro = format_macro_analysis(
        rdyn_regime=r_result.rdyn_regime,
        rdyn_blend_label=r_result.rdyn_blend_label,
        theme_r0_pct=m_result.theme_ai_hw_weight,
        theme_rdyn_pct=r_result.theme_ai_hw_weight,
    )

    news_bits = [_anchor_news_block(qdate), excerpt_tw_briefing(m_briefing)]
    news_section = "\n\n".join(b for b in news_bits if b.strip())

    minutes = build_committee_tw_minutes(
        m_result=m_result,
        m_cfg=cfg_m,
        r_result=r_result,
        r_cfg=cfg_r,
        news_section=news_section,
        macro_section=macro,
        query_date=qdate,
    )

    stamp = qdate.replace("-", "")
    minutes_path = DESKTOP / f"committee_minutes_tw_{stamp}.txt"
    m_report_path = DESKTOP / f"report_apex_tw_m_{stamp}.txt"
    r_report_path = DESKTOP / f"report_apex_tw_rdyn_{stamp}.txt"
    m_brief_path = DESKTOP / f"briefing_apex_tw_m_{stamp}.txt"
    r_brief_path = DESKTOP / f"briefing_apex_tw_rdyn_{stamp}.txt"
    full_path = DESKTOP / f"committee_full_tw_{stamp}.txt"
    eml_path = DESKTOP / f"committee_tw_{stamp}.eml"

    minutes_path.write_text(minutes, encoding="utf-8")
    m_report_path.write_text(m_report, encoding="utf-8")
    r_report_path.write_text(r_report, encoding="utf-8")
    m_brief_path.write_text(m_briefing, encoding="utf-8")
    r_brief_path.write_text(r_briefing, encoding="utf-8")

    alloc_paths: list[Path] = []
    alloc_paths.extend(
        write_engine_allocation_csvs(m_result, cfg_m, DESKTOP, tag="apex_tw_m", stamp=stamp)
    )
    alloc_paths.extend(
        write_engine_allocation_csvs(
            r_result, cfg_r, DESKTOP, tag="apex_tw_rdyn", stamp=stamp
        )
    )
    alloc_paths.extend(
        write_committee_tw_next_csv(m_result, r_result, DESKTOP, stamp=stamp)
    )

    full_body = f"""{minutes}

══════════════════════════════════════
配置試算表（請人工填總資金／0050 袖比重）
══════════════════════════════════════
· 基準執行請用：alloc_committee_tw_{stamp}_next.csv（R0 權重＋0050 錨列）。
· 另附 Apex-TW R0／RDyn 本月與下月 CSV。

══════════════════════════════════════
附件一 · Apex-TW R0 市場簡報
══════════════════════════════════════
{m_briefing}

══════════════════════════════════════
附件二 · Apex-TW RDyn-W 市場簡報
══════════════════════════════════════
{r_briefing}
"""
    full_path.write_text(full_body, encoding="utf-8")
    print(
        f"已寫入：{minutes_path.name}, {full_path.name}, "
        f"{m_report_path.name}, {r_report_path.name}, "
        f"試算表 {len(alloc_paths)} 個檔",
        flush=True,
    )

    if args.dry_run:
        print("dry-run：略過寄信")
        return 0

    address = load_mail_address()
    mode_m = m_result.market_mode.split("(")[0].strip() if m_result.market_mode else ""
    subject = f"AI台股投資委員會日報 {qdate} | {mode_m}"
    attachments = [
        minutes_path,
        full_path,
        m_report_path,
        r_report_path,
        m_brief_path,
        r_brief_path,
        *alloc_paths,
    ]
    dispatch_email(
        via=args.via,
        address=address,
        subject=subject,
        body=full_body,
        attachments=attachments,
        eml_path=eml_path,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
