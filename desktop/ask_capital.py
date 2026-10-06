#!/usr/bin/env python3
"""Monthly first-trading-day capital dialog for Apex-R daily email."""

from __future__ import annotations

import json
import logging
import tkinter as tk
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from tkinter import messagebox, ttk

DESKTOP = Path(__file__).resolve().parent
STATE_PATH = DESKTOP / "capital_state.json"


@dataclass
class CapitalDecision:
    """Result of the monthly first-day dialog."""

    month_key: str
    current_month_capital_twd: float
    next_month_injection_twd: float
    run_enabled: bool
    answered: bool  # False if dialog could not be shown / unexpected abort


def month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def is_first_us_trading_day(d: date) -> bool:
    """True if d (Mon–Fri) is the first weekday of its calendar month."""
    if d.weekday() >= 5:
        return False
    prev = d - timedelta(days=1)
    while prev.month == d.month and prev.year == d.year:
        if prev.weekday() < 5:
            return False
        prev -= timedelta(days=1)
    return True


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logging.getLogger("apex_r").warning("capital state %s unreadable, ignoring: %s", STATE_PATH, exc)
        return {}


def save_state(data: dict) -> None:
    STATE_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def needs_monthly_ask(query_date: date, *, force: bool = False) -> bool:
    if force:
        return True
    if not is_first_us_trading_day(query_date):
        return False
    state = load_state()
    return state.get("confirmed_month") != month_key(query_date)


def is_run_enabled_for_month(query_date: date) -> bool:
    """Whether automatic analyze+email should run for query_date's month."""
    state = load_state()
    mk = month_key(query_date)
    if state.get("confirmed_month") == mk:
        return bool(state.get("run_enabled"))
    # Not confirmed this month yet
    if is_first_us_trading_day(query_date):
        return False  # must complete the dialog first
    # Started mid-month with no state: allow daily runs until next first-day ask
    return True


def _parse_money(text: str) -> float:
    cleaned = (text or "").replace(",", "").replace(" ", "").strip()
    if not cleaned:
        raise ValueError("金額不可空白")
    value = float(cleaned)
    if value < 0:
        raise ValueError("金額不可為負")
    return value


def ask_monthly_capital(
    *,
    query_date: date,
    default_capital: float,
    default_inject: float,
    force: bool = False,
) -> CapitalDecision | None:
    """Show dialog when needed. Returns None if no dialog required."""
    if not needs_monthly_ask(query_date, force=force):
        return None

    mk = month_key(query_date)
    result: dict = {"done": False}

    root = tk.Tk()
    root.title(f"Apex-R 本月設定 · {mk}")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frame = ttk.Frame(root, padding=16)
    frame.grid(row=0, column=0)

    ttk.Label(
        frame,
        text=f"本月第一個投資日（查詢日 {query_date.isoformat()}）\n請確認資金，並決定是否繼續自動分析＋寄信。",
        justify=tk.LEFT,
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))

    ttk.Label(frame, text="本月起始資金 (TWD)").grid(row=1, column=0, sticky="w")
    var_capital = tk.StringVar(value=str(int(default_capital)))
    ttk.Entry(frame, textvariable=var_capital, width=18).grid(
        row=1, column=1, sticky="ew", padx=(8, 0), pady=4
    )

    ttk.Label(frame, text="下月加碼 (TWD)").grid(row=2, column=0, sticky="w")
    var_inject = tk.StringVar(value=str(int(default_inject)))
    ttk.Entry(frame, textvariable=var_inject, width=18).grid(
        row=2, column=1, sticky="ew", padx=(8, 0), pady=4
    )

    var_continue = tk.BooleanVar(value=True)
    ttk.Checkbutton(
        frame,
        text="本月繼續自動「分析＋寄信」",
        variable=var_continue,
    ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(12, 8))

    def finish(run_enabled: bool, require_valid: bool) -> None:
        try:
            capital = _parse_money(var_capital.get())
            inject = _parse_money(var_inject.get())
        except ValueError as e:
            if require_valid:
                messagebox.showerror("輸入錯誤", str(e), parent=root)
                return
            capital = float(default_capital)
            inject = float(default_inject)
        result["decision"] = CapitalDecision(
            month_key=mk,
            current_month_capital_twd=capital,
            next_month_injection_twd=inject,
            run_enabled=run_enabled,
            answered=True,
        )
        result["done"] = True
        root.destroy()

    btn_row = ttk.Frame(frame)
    btn_row.grid(row=4, column=0, columnspan=2, sticky="e", pady=(8, 0))
    ttk.Button(
        btn_row,
        text="本月略過",
        command=lambda: finish(False, True),
    ).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        btn_row,
        text="確定",
        command=lambda: finish(bool(var_continue.get()), True),
    ).pack(side=tk.LEFT)

    def on_close() -> None:
        # Closing window = skip month auto reports (plan default)
        try:
            capital = _parse_money(var_capital.get())
            inject = _parse_money(var_inject.get())
        except ValueError:
            capital = float(default_capital)
            inject = float(default_inject)
        result["decision"] = CapitalDecision(
            month_key=mk,
            current_month_capital_twd=capital,
            next_month_injection_twd=inject,
            run_enabled=False,
            answered=True,
        )
        result["done"] = True
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.update_idletasks()
    w, h = root.winfo_width(), root.winfo_height()
    x = (root.winfo_screenwidth() - w) // 2
    y = (root.winfo_screenheight() - h) // 3
    root.geometry(f"+{x}+{y}")
    root.mainloop()

    if not result.get("done"):
        return CapitalDecision(
            month_key=mk,
            current_month_capital_twd=float(default_capital),
            next_month_injection_twd=float(default_inject),
            run_enabled=False,
            answered=False,
        )
    return result["decision"]


def persist_decision(decision: CapitalDecision, config_path: Path) -> None:
    """Write amounts into config.yaml and update capital_state.json."""
    from dataclasses import replace

    from config_io import load_config, save_config

    cfg = load_config(config_path)
    cfg = replace(
        cfg,
        current_month_capital_twd=decision.current_month_capital_twd,
        next_month_injection_twd=decision.next_month_injection_twd,
    )
    save_config(config_path, cfg)
    save_state(
        {
            "confirmed_month": decision.month_key,
            "run_enabled": decision.run_enabled,
            "current_month_capital_twd": decision.current_month_capital_twd,
            "next_month_injection_twd": decision.next_month_injection_twd,
        }
    )
