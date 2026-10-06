#!/usr/bin/env python3
"""Apex-R daily report → Gmail.

Usage:
  py -3.13 daily_email_report.py
  py -3.13 daily_email_report.py --dry-run
  py -3.13 daily_email_report.py --date 2026-10-01 --force-ask
  py -3.13 daily_email_report.py --via gmail

Gmail API OAuth token: %USERPROFILE%\\.config\\apex-gmail\\token.json
"""

from __future__ import annotations

import bootstrap  # noqa: F401

import argparse
import os
import re
import smtplib
import sys
from dataclasses import replace
from datetime import date, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

import pytz
from dotenv import load_dotenv

from allocation_sheet import write_engine_allocation_csvs
from apex_core import format_report, run_monitor
from book_store import default_store
from ask_capital import (
    ask_monthly_capital,
    is_run_enabled_for_month,
    needs_monthly_ask,
    persist_decision,
)
from briefing import build_briefing
from config_io import load_config, save_config
from gmail_api_send import send_gmail_api
from strategy_presets import product_name, report_header_cfg

DESKTOP = Path(__file__).resolve().parent
TW = pytz.timezone("Asia/Taipei")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _reconfigure_stdio() -> None:
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


def last_us_session_date(as_of: date | None = None) -> date:
    """Most recent Mon–Fri on or before yesterday (TW), for morning-after-close runs."""
    today = as_of or datetime.now(TW).date()
    d = today - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def load_mail_address() -> str:
    load_dotenv(DESKTOP / ".env")
    addr = (os.getenv("GMAIL_ADDRESS") or "").strip()
    if not addr:
        raise SystemExit("請在 desktop/.env 設定 GMAIL_ADDRESS=你的信箱（可參考 .env.example）。")
    return addr


def load_mail_creds() -> tuple[str, str]:
    load_dotenv(DESKTOP / ".env")
    addr = load_mail_address()
    pwd = (os.getenv("GMAIL_APP_PASSWORD") or "").strip().replace(" ", "")
    if not pwd:
        raise SystemExit(
            "SMTP 模式需要應用程式密碼。請改用 --via gmail（OAuth）或設定 GMAIL_APP_PASSWORD。"
        )
    return addr, pwd


def build_email_message(
    *,
    address: str,
    subject: str,
    body: str,
    attachments: list[Path],
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = address
    msg["To"] = address
    msg["Subject"] = subject
    msg.set_content(body, charset="utf-8")
    for path in attachments:
        data = path.read_bytes()
        name = path.name.lower()
        if name.endswith(".csv"):
            msg.add_attachment(
                data, maintype="text", subtype="csv", filename=path.name
            )
        else:
            msg.add_attachment(
                data, maintype="text", subtype="plain", filename=path.name
            )
    return msg


def send_gmail_smtp(
    *,
    address: str,
    app_password: str,
    subject: str,
    body: str,
    attachments: list[Path],
) -> None:
    msg = build_email_message(
        address=address, subject=subject, body=body, attachments=attachments
    )
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=60) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(address, app_password)
        smtp.send_message(msg)


def open_gmail_draft(
    *,
    address: str,
    subject: str,
    body: str,
    attachments: list[Path],
    eml_path: Path,
) -> None:
    msg = build_email_message(
        address=address, subject=subject, body=body, attachments=attachments
    )
    msg["X-Unsent"] = "1"
    eml_path.write_bytes(msg.as_bytes())
    print(f"草稿已寫入：{eml_path}")
    try:
        os.startfile(str(eml_path))  # type: ignore[attr-defined]
        print("已開啟郵件草稿，請按「傳送」。")
    except OSError as e:
        print(f"無法自動開啟 .eml：{e}\n請手動開啟：{eml_path}")


def extract_market_mode(report: str) -> str:
    m = re.search(r"戰略狀態:\s*([^\n|]+)", report)
    return m.group(1).strip() if m else "N/A"


def build_full_body(
    query_date: str,
    strategy: str,
    market_mode: str,
    valuation_line: str,
    briefing: str,
    report: str,
    *,
    product: str = "Apex-R",
) -> str:
    return f"""{product} 投資標的分析 · {query_date}
策略：{strategy}
戰略狀態：{market_mode}
{valuation_line}

══════════════════════════════════════
一、{product} 市場簡報
══════════════════════════════════════
{briefing}

══════════════════════════════════════
二、完整引擎報告
══════════════════════════════════════
{report}

※ 本郵件由 {product} 本機排程產生，僅供參考，非投資建議。
"""


def dispatch_email(
    *,
    via: str,
    address: str,
    subject: str,
    body: str,
    attachments: list[Path],
    eml_path: Path,
) -> None:
    if via == "gmail":
        print(f"Gmail API 寄送至 {address} …", flush=True)
        mid = send_gmail_api(
            address=address, subject=subject, body=body, attachments=attachments
        )
        print(f"寄送完成。message_id={mid}")
    elif via == "smtp":
        _, password = load_mail_creds()
        print(f"SMTP 寄送至 {address} …", flush=True)
        send_gmail_smtp(
            address=address,
            app_password=password,
            subject=subject,
            body=body,
            attachments=attachments,
        )
        print("寄送完成。")
    else:
        print(f"開啟草稿：{address}", flush=True)
        open_gmail_draft(
            address=address,
            subject=subject,
            body=body,
            attachments=attachments,
            eml_path=eml_path,
        )


def main() -> int:
    _reconfigure_stdio()
    parser = argparse.ArgumentParser(description="Apex-R daily report → Gmail")
    parser.add_argument("--config", type=Path, default=DESKTOP / "config.yaml")
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD query date")
    parser.add_argument("--dry-run", action="store_true", help="Write files only, do not email")
    parser.add_argument(
        "--via",
        choices=["gmail", "draft", "smtp"],
        default="gmail",
        help="gmail=OAuth API（預設）| draft=開啟 .eml | smtp=App Password",
    )
    parser.add_argument(
        "--force-ask",
        action="store_true",
        help="強制彈出本月資金／是否繼續視窗（測試用）",
    )
    parser.add_argument(
        "--no-save-config",
        action="store_true",
        help="Do not persist query_date back into config.yaml",
    )
    args = parser.parse_args()

    if args.date:
        qdate = args.date
        qdate_obj = date.fromisoformat(qdate)
    else:
        qdate_obj = last_us_session_date()
        qdate = qdate_obj.isoformat()

    cfg = load_config(args.config)
    cfg = replace(cfg, query_date=qdate)

    # --- monthly first-day capital / continue gate ---
    if needs_monthly_ask(qdate_obj, force=args.force_ask):
        print("本月第一投資日：彈出資金與是否繼續視窗…", flush=True)
        decision = ask_monthly_capital(
            query_date=qdate_obj,
            default_capital=cfg.current_month_capital_twd,
            default_inject=cfg.next_month_injection_twd,
            force=args.force_ask,
        )
        if decision is None:
            pass
        else:
            persist_decision(decision, args.config)
            cfg = load_config(args.config)
            cfg = replace(cfg, query_date=qdate)
            print(
                f"本月設定已存：資金 NT${decision.current_month_capital_twd:,.0f}｜"
                f"加碼 NT${decision.next_month_injection_twd:,.0f}｜"
                f"繼續分析寄信={decision.run_enabled}",
                flush=True,
            )
            if not decision.run_enabled:
                if not args.no_save_config:
                    save_config(args.config, cfg)
                msg = (
                    f"Apex-R：{decision.month_key} 已設定為「本月略過自動分析＋寄信」。\n"
                    f"資金已更新為 NT${decision.current_month_capital_twd:,.0f}／"
                    f"加碼 NT${decision.next_month_injection_twd:,.0f}。\n"
                    f"下月第一投資日會再次詢問。"
                )
                print(msg, flush=True)
                if not args.dry_run:
                    try:
                        dispatch_email(
                            via=args.via,
                            address=load_mail_address(),
                            subject=f"Apex-R {decision.month_key} 已略過自動日報",
                            body=msg,
                            attachments=[],
                            eml_path=DESKTOP / f"skip_{decision.month_key}.eml",
                        )
                    except Exception as e:
                        print(f"略過確認信寄送失敗（可忽略）：{e}", flush=True)
                return 0

    if not is_run_enabled_for_month(qdate_obj) and not args.force_ask:
        from ask_capital import load_state, month_key

        st = load_state()
        print(
            f"本月（{month_key(qdate_obj)}）不執行自動日報"
            f"（confirmed={st.get('confirmed_month')} run_enabled={st.get('run_enabled')}）。",
            flush=True,
        )
        return 0

    if not args.no_save_config:
        save_config(args.config, cfg)

    strategy = report_header_cfg(cfg)
    product = product_name(cfg.strategy_id)
    print(f"產品：{product}")
    print(f"策略：{strategy}")
    print(f"查詢日：{qdate}")
    print(
        f"資金：NT${cfg.current_month_capital_twd:,.0f}｜加碼 NT${cfg.next_month_injection_twd:,.0f}",
        flush=True,
    )
    print("執行 monitor…", flush=True)

    result = run_monitor(cfg, book_store=default_store())
    report = format_report(result, strategy_id=cfg.strategy_id, cfg=cfg)

    print("產生市場簡報…", flush=True)
    briefing = build_briefing(result, cfg, progress=lambda m: print(f"  {m}", flush=True))

    stamp = qdate.replace("-", "")
    tag = "apex_m" if product == "Apex-M" else "apex_r"
    report_path = DESKTOP / f"report_{tag}_{stamp}.txt"
    briefing_path = DESKTOP / f"briefing_{tag}_{stamp}.txt"
    full_path = DESKTOP / f"daily_full_{tag}_{stamp}.txt"
    eml_path = DESKTOP / f"daily_{tag}_{stamp}.eml"

    report_path.write_text(report, encoding="utf-8")
    briefing_path.write_text(briefing, encoding="utf-8")

    alloc_paths = write_engine_allocation_csvs(
        result, cfg, DESKTOP, tag=tag, stamp=stamp
    )

    market_mode = extract_market_mode(report)
    valuation_line = "金額：見附件配置試算表（權重已填，總資金由人填入）"

    full_body = build_full_body(
        qdate,
        strategy,
        market_mode,
        valuation_line,
        briefing,
        report,
        product=product,
    )
    full_path.write_text(full_body, encoding="utf-8")
    print(
        f"已寫入：{report_path.name}, {briefing_path.name}, {full_path.name}, "
        f"試算表 {len(alloc_paths)} 個檔"
    )

    if args.dry_run:
        print("dry-run：略過寄信")
        return 0

    address = load_mail_address()
    subject = f"{product} 日報 {qdate} | {market_mode}"
    attachments = [report_path, briefing_path, full_path, *alloc_paths]
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
