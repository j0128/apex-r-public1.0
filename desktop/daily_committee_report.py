#!/usr/bin/env python3
"""AI 投資委員會日報 → Gmail（固定格式紀要 + M/R 雙引擎）。

每日例會：Apex-M（基準）× Apex-R（衛星）→ 委員會紀要 → 寄信。

Usage:
  py -3.13 daily_committee_report.py
  py -3.13 daily_committee_report.py --dry-run
  py -3.13 daily_committee_report.py --date 2026-09-23 --via gmail
"""

from __future__ import annotations

import bootstrap  # noqa: F401

import argparse
import os
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytz
from dotenv import load_dotenv

from allocation_sheet import write_committee_next_csv, write_engine_allocation_csvs
from apex_core import format_report, run_monitor
from book_store import default_store
from ask_capital import (
    ask_monthly_capital,
    is_run_enabled_for_month,
    needs_monthly_ask,
    persist_decision,
)
from briefing import build_briefing
from committee import build_committee_minutes, excerpt_briefing
from config_io import load_config, save_config
from daily_email_report import (
    DESKTOP,
    dispatch_email,
    last_us_session_date,
    load_mail_address,
)
from strategy_presets import report_header_cfg

TW = pytz.timezone("Asia/Taipei")


def _reconfigure_stdio() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def main() -> int:
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(description="AI 投資委員會日報 → Gmail")
    parser.add_argument(
        "--config-m",
        type=Path,
        default=DESKTOP / "config_apex_m.yaml",
        help="Apex-M (R0) 設定",
    )
    parser.add_argument(
        "--config-r",
        type=Path,
        default=DESKTOP / "config.yaml",
        help="Apex-R (RDyn-W) 設定",
    )
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--via", choices=["gmail", "draft", "smtp"], default="gmail")
    parser.add_argument("--force-ask", action="store_true")
    parser.add_argument("--no-save-config", action="store_true")
    args = parser.parse_args()

    if args.date:
        qdate = args.date
        qdate_obj = date.fromisoformat(qdate)
    else:
        qdate_obj = last_us_session_date()
        qdate = qdate_obj.isoformat()

    cfg_m = replace(load_config(args.config_m), query_date=qdate)
    cfg_r = replace(load_config(args.config_r), query_date=qdate)

    # Monthly gate uses Apex-R config path (existing capital state)
    if needs_monthly_ask(qdate_obj, force=args.force_ask):
        print("本月第一投資日：彈出資金與是否繼續視窗…", flush=True)
        decision = ask_monthly_capital(
            query_date=qdate_obj,
            default_capital=cfg_r.current_month_capital_twd,
            default_inject=cfg_r.next_month_injection_twd,
            force=args.force_ask,
        )
        if decision is not None:
            persist_decision(decision, args.config_r)
            # Mirror capital into Apex-M config for consistent valuation base
            cfg_r = replace(load_config(args.config_r), query_date=qdate)
            cfg_m = replace(
                cfg_m,
                current_month_capital_twd=cfg_r.current_month_capital_twd,
                next_month_injection_twd=cfg_r.next_month_injection_twd,
                query_date=qdate,
            )
            if not decision.run_enabled:
                if not args.no_save_config:
                    save_config(args.config_r, cfg_r)
                    save_config(args.config_m, cfg_m)
                print("本月略過委員會日報。", flush=True)
                return 0

    if not is_run_enabled_for_month(qdate_obj) and not args.force_ask:
        print(f"本月不執行委員會日報（{qdate}）。", flush=True)
        return 0

    if not args.no_save_config:
        save_config(args.config_m, cfg_m)
        save_config(args.config_r, cfg_r)

    print(f"查詢日：{qdate}", flush=True)
    print(f"基準：{report_header_cfg(cfg_m)}", flush=True)
    print(f"衛星：{report_header_cfg(cfg_r)}", flush=True)

    print("執行 Apex-M monitor…", flush=True)
    m_result = run_monitor(cfg_m, book_store=default_store())
    m_report = format_report(m_result, strategy_id=cfg_m.strategy_id, cfg=cfg_m)

    print("執行 Apex-R monitor…", flush=True)
    r_result = run_monitor(cfg_r, book_store=default_store())
    r_report = format_report(r_result, strategy_id=cfg_r.strategy_id, cfg=cfg_r)

    print("產生 Apex-M 市場簡報（秘書處）…", flush=True)
    m_briefing = build_briefing(
        m_result, cfg_m, progress=lambda s: print(f"  {s}", flush=True)
    )
    print("產生 Apex-R 市場簡報…", flush=True)
    r_briefing = build_briefing(
        r_result, cfg_r, progress=lambda s: print(f"  {s}", flush=True)
    )

    minutes = build_committee_minutes(
        m_result=m_result,
        m_cfg=cfg_m,
        r_result=r_result,
        r_cfg=cfg_r,
        briefing_excerpt=excerpt_briefing(m_briefing),
        query_date=qdate,
    )

    stamp = qdate.replace("-", "")
    minutes_path = DESKTOP / f"committee_minutes_{stamp}.txt"
    m_report_path = DESKTOP / f"report_apex_m_{stamp}.txt"
    r_report_path = DESKTOP / f"report_apex_r_{stamp}.txt"
    m_brief_path = DESKTOP / f"briefing_apex_m_{stamp}.txt"
    r_brief_path = DESKTOP / f"briefing_apex_r_{stamp}.txt"
    full_path = DESKTOP / f"committee_full_{stamp}.txt"
    eml_path = DESKTOP / f"committee_{stamp}.eml"

    minutes_path.write_text(minutes, encoding="utf-8")
    m_report_path.write_text(m_report, encoding="utf-8")
    r_report_path.write_text(r_report, encoding="utf-8")
    m_brief_path.write_text(m_briefing, encoding="utf-8")
    r_brief_path.write_text(r_briefing, encoding="utf-8")

    alloc_paths: list[Path] = []
    alloc_paths.extend(
        write_engine_allocation_csvs(m_result, cfg_m, DESKTOP, tag="apex_m", stamp=stamp)
    )
    alloc_paths.extend(
        write_engine_allocation_csvs(r_result, cfg_r, DESKTOP, tag="apex_r", stamp=stamp)
    )
    alloc_paths.extend(
        write_committee_next_csv(m_result, r_result, DESKTOP, stamp=stamp)
    )

    full_body = f"""{minutes}

══════════════════════════════════════
配置試算表（請人工填總資金）
══════════════════════════════════════
· 權重已由系統填入；金額欄空白／含 Excel 公式。
· 基準執行請用：alloc_committee_{stamp}_next.csv（Apex-M 權重）。
· 另附 Apex-M／Apex-R 本月與下月 CSV，以及 readme 說明。

══════════════════════════════════════
附件一 · Apex-M 市場簡報
══════════════════════════════════════
{m_briefing}

══════════════════════════════════════
附件二 · Apex-R 市場簡報
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
    subject = f"AI投資委員會日報 {qdate} | {mode_m}"
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
