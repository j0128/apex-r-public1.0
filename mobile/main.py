#!/usr/bin/env python3
"""Apex-R 3.0 手機版 — Flet UI，可打包成 Android APK。"""

from __future__ import annotations

import bootstrap  # noqa: F401

import threading
import traceback
from datetime import date
from pathlib import Path
from typing import Any

import flet as ft

# Heavy modules (numpy/pandas/yfinance) load AFTER first frame — avoids black/blank boot.
APP_VERSION = "3.0.0"
BASE_DIR = Path(__file__).resolve().parent
_core: dict[str, Any] = {"ready": False, "error": ""}


def _load_core() -> None:
    if _core["ready"]:
        return
    try:
        from apex_core import ApexConfig, format_report, run_monitor
        from config_io import default_config_path, load_config, save_config
        from strategy_presets import (
            APP_VERSION as _VER,
            STRATEGY_CUSTOM,
            apply_preset,
            normalize_strategy_id,
            preset_choices,
        )
        from universe_builder import build_universe, parse_ticker_csv

        _core.update(
            ApexConfig=ApexConfig,
            format_report=format_report,
            run_monitor=run_monitor,
            default_config_path=default_config_path,
            load_config=load_config,
            save_config=save_config,
            STRATEGY_CUSTOM=STRATEGY_CUSTOM,
            apply_preset=apply_preset,
            normalize_strategy_id=normalize_strategy_id,
            preset_choices=preset_choices,
            build_universe=build_universe,
            parse_ticker_csv=parse_ticker_csv,
            APP_VERSION=_VER,
            ready=True,
            error="",
        )
    except Exception as ex:
        _core["error"] = f"{ex}\n{traceback.format_exc()}"
        raise


def main(page: ft.Page) -> None:
    page.title = f"Apex-R {APP_VERSION}"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.bgcolor = ft.Colors.WHITE
    page.scroll = ft.ScrollMode.AUTO
    page.padding = 12

    boot = ft.Text("正在啟動 Apex-R…", size=16, color=ft.Colors.BLUE_GREY_800)
    boot_detail = ft.Text(
        "首次開啟會載入計算套件，約需數秒，請稍候。",
        size=12,
        color=ft.Colors.GREY_600,
    )
    page.add(boot, boot_detail)
    page.update()

    def build_ui() -> None:
        # Assumes _load_core() already succeeded (called off UI thread).
        ApexConfig = _core["ApexConfig"]
        format_report = _core["format_report"]
        run_monitor = _core["run_monitor"]
        default_config_path = _core["default_config_path"]
        load_config = _core["load_config"]
        save_config = _core["save_config"]
        STRATEGY_CUSTOM = _core["STRATEGY_CUSTOM"]
        apply_preset = _core["apply_preset"]
        normalize_strategy_id = _core["normalize_strategy_id"]
        preset_choices = _core["preset_choices"]
        build_universe = _core["build_universe"]
        parse_ticker_csv = _core["parse_ticker_csv"]
        ver = _core.get("APP_VERSION", APP_VERSION)
        config_path = default_config_path(BASE_DIR)

        strategy_map = {label: sid for sid, label in preset_choices()}
        loaded_cfg = {"cfg": None}
        last_report = {"text": ""}
        running = {"flag": False}

        status = ft.Text("就緒", size=13, color=ft.Colors.GREY_700)
        report = ft.TextField(
            value="",
            multiline=True,
            read_only=True,
            min_lines=16,
            max_lines=24,
            text_size=11,
            expand=True,
            bgcolor=ft.Colors.GREY_50,
        )

        dd_strategy = ft.Dropdown(
            label="策略版本",
            options=[ft.dropdown.Option(label) for _, label in preset_choices()],
            expand=True,
        )
        if dd_strategy.options:
            dd_strategy.value = dd_strategy.options[0].key

        tf_date = ft.TextField(label="查詢日期", value=str(date.today()), width=160)
        tf_capital = ft.TextField(
            label="本月初始資金 (TWD)", value="1000000", keyboard_type=ft.KeyboardType.NUMBER
        )
        tf_inject = ft.TextField(
            label="下月預計加碼 (TWD)", value="0", keyboard_type=ft.KeyboardType.NUMBER
        )
        tf_universe = ft.TextField(label="宇宙數", value="65", width=100, keyboard_type=ft.KeyboardType.NUMBER)
        tf_momentum = ft.TextField(label="動能日", value="120", width=100, keyboard_type=ft.KeyboardType.NUMBER)
        tf_topn = ft.TextField(label="Top N", value="10", width=90, keyboard_type=ft.KeyboardType.NUMBER)
        tf_buffer = ft.TextField(label="Buffer", value="0.97", width=90)
        tf_us = ft.TextField(label="美股宇宙", multiline=True, min_lines=2, max_lines=4)
        tf_tw = ft.TextField(label="台股標的", multiline=True, min_lines=2, max_lines=3)

        def strategy_id() -> str:
            label = dd_strategy.value or ""
            return normalize_strategy_id(strategy_map.get(label, label))

        def cfg_from_form():
            base = loaded_cfg["cfg"] or ApexConfig()
            return ApexConfig(
                query_date=tf_date.value.strip(),
                current_month_capital_twd=float((tf_capital.value or "0").replace(",", "")),
                next_month_injection_twd=float((tf_inject.value or "0").replace(",", "")),
                user_tickers=(tf_us.value or "").replace("\n", " ").strip(),
                tw_tickers=(tf_tw.value or "").replace("\n", " ").strip(),
                strategy_id=strategy_id(),
                universe_size=int(tf_universe.value or base.universe_size),
                universe_mode=base.universe_mode,
                universe_momentum_days=base.universe_momentum_days,
                universe_last_updated=base.universe_last_updated,
                top_n_limit=int(tf_topn.value or base.top_n_limit),
                buffer_zone=float(tf_buffer.value or base.buffer_zone),
                momentum_days=int(tf_momentum.value or base.momentum_days),
                transaction_cost=base.transaction_cost,
                max_weight_cap=base.max_weight_cap,
                volatility_days=base.volatility_days,
                ma_days=base.ma_days,
                breadth_threshold=base.breadth_threshold,
                show_market_mode=base.show_market_mode,
            )

        def form_from_cfg(cfg) -> None:
            loaded_cfg["cfg"] = cfg
            for sid, label in preset_choices():
                if sid == cfg.strategy_id:
                    dd_strategy.value = label
                    break
            tf_date.value = cfg.query_date
            tf_capital.value = str(int(cfg.current_month_capital_twd))
            tf_inject.value = str(int(cfg.next_month_injection_twd))
            tf_universe.value = str(cfg.universe_size)
            tf_topn.value = str(cfg.top_n_limit)
            tf_momentum.value = str(cfg.momentum_days)
            tf_buffer.value = str(cfg.buffer_zone)
            tf_us.value = ", ".join(parse_ticker_csv(cfg.user_tickers))
            tf_tw.value = ", ".join(parse_ticker_csv(cfg.tw_tickers))
            page.update()

        def on_strategy_change(_e) -> None:
            base = cfg_from_form()
            sid = base.strategy_id
            if sid == STRATEGY_CUSTOM:
                loaded_cfg["cfg"] = base
                status.value = "自訂參數"
                page.update()
                return
            cfg = apply_preset(base, sid)
            tf_universe.value = str(cfg.universe_size)
            tf_topn.value = str(cfg.top_n_limit)
            tf_momentum.value = str(cfg.momentum_days)
            tf_buffer.value = str(cfg.buffer_zone)
            loaded_cfg["cfg"] = cfg
            status.value = f"已切換 → {cfg.strategy_id}"
            page.update()

        dd_strategy.on_change = on_strategy_change

        def snack(msg: str) -> None:
            page.snack_bar = ft.SnackBar(ft.Text(msg))
            page.snack_bar.open = True
            page.update()

        def load_config_file(_e=None) -> None:
            if not config_path.exists():
                snack(f"找不到 {config_path.name}，請先儲存設定")
                return
            try:
                form_from_cfg(load_config(config_path))
                status.value = f"已載入 {config_path.name}"
                page.update()
            except Exception as ex:
                snack(f"載入失敗: {ex}")

        def save_config_file(_e) -> None:
            try:
                cfg = cfg_from_form()
                save_config(config_path, cfg)
                status.value = "設定已儲存"
                snack(f"已儲存至 {config_path.name}")
            except Exception as ex:
                snack(f"儲存失敗: {ex}")

        def set_busy(busy: bool, msg: str) -> None:
            running["flag"] = busy
            btn_run.disabled = busy
            btn_refresh.disabled = busy
            status.value = msg
            page.update()

        def show_report(text: str, cfg) -> None:
            last_report["text"] = text
            report.value = text
            set_busy(False, f"完成 | 宇宙 {len(cfg.ticker_list())} 檔")

        def show_error(msg: str) -> None:
            report.value = f"錯誤：\n{msg}"
            set_busy(False, "執行失敗")
            snack(msg)

        def on_run(_e) -> None:
            if running["flag"]:
                return
            report.value = "正在連線 Yahoo Finance 並計算，約需 10～30 秒…"
            set_busy(True, "下載行情中…")

            def worker() -> None:
                try:
                    cfg = cfg_from_form()
                    result = run_monitor(cfg)
                    text = format_report(result, strategy_id=cfg.strategy_id, cfg=cfg)
                    page.run_thread(lambda: show_report(text, cfg))
                except Exception as ex:
                    page.run_thread(lambda: show_error(str(ex)))

            threading.Thread(target=worker, daemon=True).start()

        def on_refresh(_e) -> None:
            if running["flag"]:
                return
            report.value = "更新美股宇宙中… (約 1～3 分鐘)"
            set_busy(True, "更新宇宙中…")

            def worker() -> None:
                try:
                    cfg = cfg_from_form()
                    tw = parse_ticker_csv(cfg.tw_tickers)
                    result = build_universe(
                        as_of=cfg.query_date,
                        top_n=cfg.universe_size or 65,
                        tw_tickers=tw,
                        mode=cfg.universe_mode or "dollar_volume",
                        momentum_days=cfg.universe_momentum_days or 504,
                    )
                    cfg.user_tickers = ", ".join(result.us_tickers)
                    cfg.universe_last_updated = result.as_of
                    summary = "\n".join(result.summary_lines())

                    def done() -> None:
                        form_from_cfg(cfg)
                        report.value = summary + "\n\n請按「儲存設定」寫入 config.yaml。"
                        set_busy(False, f"宇宙已更新 | {len(result.us_tickers)} 美股")

                    page.run_thread(done)
                except Exception as ex:
                    page.run_thread(lambda: show_error(str(ex)))

            threading.Thread(target=worker, daemon=True).start()

        btn_run = ft.ElevatedButton("執行監控", icon=ft.Icons.PLAY_ARROW, on_click=on_run)
        btn_refresh = ft.OutlinedButton("更新宇宙", icon=ft.Icons.REFRESH, on_click=on_refresh)
        btn_save = ft.OutlinedButton("儲存", icon=ft.Icons.SAVE, on_click=save_config_file)
        btn_load = ft.OutlinedButton("載入", icon=ft.Icons.FOLDER_OPEN, on_click=load_config_file)

        page.controls.clear()
        page.add(
            ft.Text(f"Apex-R {ver} 手機版", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_GREY_900),
            ft.Text("與桌面版共用核心邏輯", size=12, color=ft.Colors.GREY_600),
            dd_strategy,
            ft.Row([tf_date, tf_capital], wrap=True),
            tf_inject,
            ft.Row([tf_universe, tf_momentum, tf_topn, tf_buffer], wrap=True),
            tf_us,
            tf_tw,
            ft.Row([btn_run, btn_refresh, btn_save, btn_load], wrap=True),
            status,
            report,
        )
        page.update()
        if config_path.exists():
            try:
                form_from_cfg(load_config(config_path))
                status.value = f"已載入 {config_path.name}"
                page.update()
            except Exception as ex:
                status.value = f"設定載入略過: {ex}"
                page.update()

    def boot_worker() -> None:
        try:
            _load_core()
            page.run_thread(build_ui)
        except Exception as ex:
            detail = _core.get("error") or traceback.format_exc()

            def fail() -> None:
                page.controls.clear()
                page.bgcolor = ft.Colors.WHITE
                page.add(
                    ft.Text("啟動失敗", size=20, weight=ft.FontWeight.BOLD, color=ft.Colors.RED_700),
                    ft.Text(str(ex), size=13, color=ft.Colors.RED_600),
                    ft.TextField(value=detail, multiline=True, read_only=True, min_lines=12, expand=True),
                )
                page.update()

            page.run_thread(fail)

    threading.Thread(target=boot_worker, daemon=True).start()


if __name__ == "__main__":
    ft.app(target=main)
