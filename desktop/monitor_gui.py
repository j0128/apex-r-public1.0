#!/usr/bin/env python3
"""Apex 桌面監控 — Apex-R（RDyn-W）或 Apex-M（R0）。"""

from __future__ import annotations

import bootstrap  # noqa: F401 — shared modules on sys.path

import json

import pandas as pd
import sys
import threading
import tkinter as tk
from datetime import date
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import backtest_engine as be
import charts
import theme
import view_model as vm
from widgets import KpiCard, bar_image, scrolled_text

try:  # charts are optional: the monitor still works without matplotlib
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    from matplotlib.figure import Figure
except ImportError:  # pragma: no cover
    FigureCanvasTkAgg = Figure = None
from apex_core import ApexConfig, format_report, run_monitor
from book_store import default_store
from config_io import default_config_path, load_config, save_config
from strategy_presets import (
    APP_VERSION,
    STRATEGY_CUSTOM,
    STRATEGY_M,
    apply_preset,
    normalize_strategy_id,
    preset_choices,
    product_name,
    product_version,
)
from universe_builder import (
    build_universe,
    can_refresh_universe,
    ensure_universe_cycle_stamp,
    parse_ticker_csv,
    universe_refresh_status,
)


def app_base_dir() -> Path:
    """程式所在目錄（支援 PyInstaller 打包後）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


class ApexRApp(tk.Tk):
    def __init__(self, config_path: Path | None = None) -> None:
        theme.enable_hidpi()
        super().__init__()
        self.geometry("1320x920")
        self.minsize(1100, 760)
        self.base_dir = app_base_dir()
        self.prefs = self._load_prefs()
        self.palette = theme.get_palette(self.prefs["style"], self.prefs["mode"], self.prefs["red_up"])
        self.config_path = config_path or default_config_path(self.base_dir)
        self._last_report = ""
        self._loaded_cfg: ApexConfig | None = None
        self._suppress_param_trace = False

        self._build_ui()
        self._apply_theme()
        if not self.var_strategy.get() and self.cmb_strategy["values"]:
            self.cmb_strategy.current(0)
        self._load_from_file(silent=True)
        self._refresh_window_title()

    def _refresh_window_title(self) -> None:
        try:
            sid = self._strategy_id_from_form()
        except Exception:
            sid = STRATEGY_M if "apex_m" in self.config_path.name.lower() else "apex_rdyn_w"
        brand = product_name(sid)
        ver = product_version(sid)
        self.title(f"{brand} v{ver} 實戰監控中心")
        if hasattr(self, "lbl_title"):
            self.lbl_title.config(text=f"{brand} {ver}　實戰監控中心")

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        self._themed_text: list = []  # main-area Text widgets
        self._themed_inputs: list = []  # sidebar Text widgets
        self._bar_imgs: dict = {}
        self.cards: dict = {}
        self._trees: list = []

        self._build_header()
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.tab_monitor = ttk.Frame(self.notebook)
        self.tab_perf = ttk.Frame(self.notebook)
        self.tab_briefing = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_monitor, text="  📈 監控中心  ")
        self.notebook.add(self.tab_perf, text="  📊 績效曲線  ")
        self.notebook.add(self.tab_briefing, text="  📰 市場簡報  ")

        self._build_monitor_tab(self.tab_monitor)
        self._build_perf_tab(self.tab_perf)
        self._build_briefing_tab(self.tab_briefing)

        self.status = tk.StringVar(value="就緒")
        bar = ttk.Frame(self, style="Side.TFrame")
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        ttk.Label(bar, textvariable=self.status, style="SideMuted.TLabel").pack(
            side=tk.LEFT, padx=12, pady=4
        )
        self.lbl_exposure = ttk.Label(bar, text="", style="SideMuted.TLabel")
        self.lbl_exposure.pack(side=tk.RIGHT, padx=12, pady=4)

    def _build_header(self) -> None:
        head = ttk.Frame(self, style="Side.TFrame")
        head.pack(fill=tk.X)
        self.lbl_title = ttk.Label(head, text="Apex", style="Side.TLabel")
        self.lbl_title.pack(side=tk.LEFT, padx=16, pady=10)

        right = ttk.Frame(head, style="Side.TFrame")
        right.pack(side=tk.RIGHT, padx=12)
        self.var_style = tk.StringVar(value=self.prefs["style"])
        cmb = ttk.Combobox(right, textvariable=self.var_style, values=list(theme.STYLES),
                           state="readonly", width=11)
        cmb.pack(side=tk.LEFT, padx=4, pady=8)
        cmb.bind("<<ComboboxSelected>>", lambda _e: self._set_pref(style=self.var_style.get()))
        self.btn_mode = ttk.Button(right, command=self._toggle_mode)
        self.btn_mode.pack(side=tk.LEFT, padx=4)
        self.btn_updown = ttk.Button(right, command=self._toggle_updown)
        self.btn_updown.pack(side=tk.LEFT, padx=4)
        self.btn_sidebar = ttk.Button(right, text="⇤ 設定", command=self._toggle_sidebar)
        self.btn_sidebar.pack(side=tk.LEFT, padx=4)

    def _build_monitor_tab(self, parent) -> None:
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        # ---- left sidebar: all inputs
        self.sidebar = ttk.Frame(parent, style="Side.TFrame", width=330)
        self.sidebar.grid(row=0, column=0, sticky="ns")
        self.sidebar.grid_propagate(False)
        sb = self.sidebar
        pad = {"padx": 14}
        self._strategy_map = {label: sid for sid, label in preset_choices()}
        self._strategy_ids = list(self._strategy_map.values())

        def section(text, top=12):
            ttk.Label(sb, text=text, style="Section.TLabel").pack(anchor=tk.W, pady=(top, 4), **pad)

        section("策略", top=14)
        self.var_strategy = tk.StringVar()
        self.cmb_strategy = ttk.Combobox(
            sb, textvariable=self.var_strategy, values=list(self._strategy_map.keys()), state="readonly"
        )
        self.cmb_strategy.pack(fill=tk.X, **pad)
        self.cmb_strategy.bind("<<ComboboxSelected>>", self._on_strategy_change)

        section("參數")
        grid = ttk.Frame(sb, style="Side.TFrame")
        grid.pack(fill=tk.X, **pad)
        self.var_universe = tk.StringVar(value="60")
        self.var_momentum = tk.StringVar(value="120")
        self.var_topn = tk.StringVar(value="10")
        self.var_buffer = tk.StringVar(value="0.97")
        for i, (label, var, widget) in enumerate(
            [
                ("宇宙數", self.var_universe, lambda m, v: ttk.Spinbox(m, textvariable=v, from_=20, to=150, width=6)),
                ("動能日", self.var_momentum, lambda m, v: ttk.Spinbox(m, textvariable=v, from_=20, to=504, width=6)),
                ("Top N", self.var_topn, lambda m, v: ttk.Spinbox(m, textvariable=v, from_=1, to=30, width=6)),
                ("Buffer", self.var_buffer, lambda m, v: ttk.Entry(m, textvariable=v, width=7)),
            ]
        ):
            r, c = divmod(i, 2)
            ttk.Label(grid, text=label, style="Side.TLabel").grid(row=r, column=c * 2, sticky=tk.W, pady=3)
            widget(grid, var).grid(row=r, column=c * 2 + 1, sticky=tk.W, padx=(6, 12), pady=3)
        self.lbl_param_warn = ttk.Label(sb, text="", style="SideMuted.TLabel", wraplength=300, justify=tk.LEFT)
        self.lbl_param_warn.pack(anchor=tk.W, pady=(4, 0), **pad)
        for var in (self.var_universe, self.var_momentum, self.var_topn):
            var.trace_add("write", self._on_param_edited)
        for var in (self.var_universe, self.var_momentum, self.var_topn, self.var_buffer):
            var.trace_add("write", self._update_param_warning)

        section("監控設定")
        form = ttk.Frame(sb, style="Side.TFrame")
        form.pack(fill=tk.X, **pad)
        form.columnconfigure(1, weight=1)
        self.var_date = tk.StringVar(value=str(date.today()))
        self.var_capital = tk.StringVar(value="1000000")
        self.var_inject = tk.StringVar(value="0")
        for r, (label, var) in enumerate(
            [("查詢日期", self.var_date), ("本月初始資金", self.var_capital), ("下月加碼", self.var_inject)]
        ):
            ttk.Label(form, text=label, style="Side.TLabel").grid(row=r, column=0, sticky=tk.W, pady=3)
            ttk.Entry(form, textvariable=var).grid(row=r, column=1, sticky=tk.EW, padx=(8, 0), pady=3)

        section("美股宇宙（自動／手動）")
        self.txt_tickers = self._text_box(sb, height=5)
        section("台股標的（手動）")
        self.txt_tw = self._text_box(sb, height=2)

        # ---- right: toolbar, cards, results
        main = ttk.Frame(parent)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)

        bar = ttk.Frame(main)
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 6))
        self.btn_run = ttk.Button(bar, text="▶ 執行監控", style="Accent.TButton", command=self._on_run)
        self.btn_run.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_relock = ttk.Button(bar, text="🔒 重新鎖定本月", command=self._on_relock)
        self.btn_relock.pack(side=tk.LEFT, padx=3)
        self.btn_refresh = ttk.Button(bar, text="🔄 更新宇宙", command=self._on_refresh_universe)
        self.btn_refresh.pack(side=tk.LEFT, padx=3)
        for text, cmd in (("💾 儲存設定", self._on_save_config), ("📄 儲存報告", self._on_save_report),
                          ("📂 載入設定", self._on_load_config)):
            ttk.Button(bar, text=text, style="Ghost.TButton", command=cmd).pack(side=tk.LEFT, padx=2)

        cards = ttk.Frame(main)
        cards.grid(row=1, column=0, sticky="ew", padx=14, pady=4)
        keys = ["asset", "pnl", "exposure", "regime", "theme", "lock"]
        labels = ["預估總資產 TWD", "本月損益", "曝險 / 現金", "大盤狀態", "題材集中度", "月度鎖定"]
        for i, (key, label) in enumerate(zip(keys, labels)):
            cards.columnconfigure(i, weight=1, uniform="card")
            card = KpiCard(cards, label)
            card.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            self.cards[key] = card

        self.split = ttk.PanedWindow(main, orient=tk.VERTICAL)
        self.split.grid(row=3, column=0, sticky="nsew", padx=14, pady=(8, 12))
        out = ttk.Frame(self.split)
        out.columnconfigure(0, weight=1)
        out.rowconfigure(0, weight=1)
        self.split.add(out, weight=3)
        self.result_nb = ttk.Notebook(out)
        self.result_nb.grid(row=0, column=0, sticky="nsew")

        cols = vm.VALUE_COLUMNS
        widths = (70, 80, 70, 85, 110, 220)
        self.tree_hold = self._make_tree(self.result_nb, "  本月持倉（已鎖定）  ", cols, widths)
        self.tree_next = self._make_tree(self.result_nb, "  下月預覽  ", cols, widths)
        self.tree_other = self._make_tree(self.result_nb, "  其他雷達  ", cols, widths)

        text_tab = ttk.Frame(self.result_nb)
        self.result_nb.add(text_tab, text="  完整文字報告  ")
        frame, self.txt_report = scrolled_text(text_tab, wrap="none", hscroll=True,
                                               highlightthickness=0, padx=10, pady=8)
        frame.pack(fill=tk.BOTH, expand=True)
        self._themed_text.append(self.txt_report)
        self._build_charts(self.split)
        for tree in self._trees:
            tree.bind("<<TreeviewSelect>>", lambda _e, t=tree: self._on_row_selected(t))
        self._update_param_warning()

    def _build_charts(self, split) -> None:
        self._chart_cards: list = []
        self.sel_ticker: str | None = None
        self.var_field = tk.StringVar(value="close")
        self.var_ma = tk.BooleanVar(value=True)
        if Figure is None:
            self.weights_chart = self.stock_chart = None
            return
        wrap = ttk.Frame(split)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(0, weight=1)
        split.add(wrap, weight=2)
        dpi = max(96.0, self.winfo_fpixels("1i"))

        def card(col, width=None):
            c = tk.Frame(wrap, bd=0, highlightthickness=1)
            c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 8, 0), pady=(8, 0))
            if width:
                c.config(width=width)
                c.grid_propagate(False)
            self._chart_cards.append(c)
            return c

        left = card(0, width=360)
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        self.lbl_w = tk.Label(left, text="權重分布（本月鎖定）", anchor="w")
        self.lbl_w.grid(row=0, column=0, sticky="ew", padx=12, pady=(8, 0))
        self.fig_w = Figure(figsize=(3.4, 2.4), dpi=dpi)
        self.canvas_w = FigureCanvasTkAgg(self.fig_w, master=left)
        self.canvas_w.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.weights_chart = charts.WeightsChart(self.fig_w)

        right = card(1)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        head = tk.Frame(right)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(6, 0))
        self.lbl_s = tk.Label(head, text="個股走勢（近 200 日）", anchor="w")
        self.lbl_s.pack(side=tk.LEFT)
        ctl = ttk.Frame(head, style="Card.TFrame")
        ctl.pack(side=tk.RIGHT)
        for text, val in (("收盤價", "close"), ("開盤價", "open")):
            ttk.Radiobutton(ctl, text=text, value=val, variable=self.var_field, style="Card.TRadiobutton",
                            command=self._draw_stock).pack(side=tk.LEFT, padx=4)
        ttk.Checkbutton(ctl, text="200MA", variable=self.var_ma, style="Card.TCheckbutton",
                        command=self._draw_stock).pack(side=tk.LEFT, padx=4)
        self._chart_heads = [head, ctl]
        self.fig_s = Figure(figsize=(6.5, 2.4), dpi=dpi)
        self.canvas_s = FigureCanvasTkAgg(self.fig_s, master=right)
        self.canvas_s.get_tk_widget().grid(row=1, column=0, sticky="nsew", padx=6, pady=6)
        self.stock_chart = charts.StockChart(self.fig_s)
        self.canvas_s.mpl_connect(
            "motion_notify_event",
            lambda e: self.canvas_s.draw_idle() if self.stock_chart.on_move(e) else None,
        )

    def _text_box(self, parent, height: int):
        frame, box = scrolled_text(parent, height=height, width=30, highlightthickness=1, padx=6, pady=4)
        frame.pack(fill=tk.X, padx=14)
        self._themed_inputs.append(box)
        return box

    def _make_tree(self, notebook, title, columns, widths) -> ttk.Treeview:
        frame = ttk.Frame(notebook)
        notebook.add(frame, text=title)
        tree = ttk.Treeview(frame, columns=columns, show="tree headings", height=12)
        tree.heading("#0", text="代碼", command=lambda t=tree: self._sort_tree(t, "#0"))
        tree.column("#0", width=190, stretch=False, anchor=tk.W)
        for col, w in zip(columns, widths):
            tree.heading(col, text=col, command=lambda c=col, t=tree: self._sort_tree(t, c))
            tree.column(col, width=w, anchor=tk.W if col == "狀態" else tk.E)
        vsb = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self._trees.append(tree)
        return tree

    def _sort_tree(self, tree: ttk.Treeview, col: str) -> None:
        rev = getattr(tree, "_sort_rev", {}).get(col, False)
        key = (lambda i: tree.item(i, "text")) if col == "#0" else (lambda i: tree.set(i, col))
        items = [(vm.sort_key(key(i)), i) for i in tree.get_children("")]
        items.sort(reverse=rev)
        for idx, (_k, i) in enumerate(items):
            tree.move(i, "", idx)
        tree._sort_rev = {col: not rev}

    # ---------------------------------------------------------------- charts
    def _on_row_selected(self, tree: ttk.Treeview) -> None:
        sel = tree.selection()
        if not sel:
            return
        self.sel_ticker = tree.item(sel[0], "text").strip()
        self._draw_stock()

    def _draw_weights(self) -> None:
        if getattr(self, "weights_chart", None) is None:
            return
        res = self._last_result[0] if getattr(self, "_last_result", None) else None
        self.weights_chart.render(self.palette, dict(res.locked_weights) if res else {})
        self.canvas_w.draw_idle()

    def _draw_stock(self) -> None:
        if getattr(self, "stock_chart", None) is None:
            return
        res = self._last_result[0] if getattr(self, "_last_result", None) else None
        t = self.sel_ticker
        if res is None or t is None or res.hist_close is None or t not in res.hist_close.columns:
            self.stock_chart.render(self.palette, None, None, None, None)
        else:
            self.stock_chart.render(
                self.palette, t, res.hist_close[t],
                res.hist_open[t] if res.hist_open is not None and t in res.hist_open.columns else None,
                res.hist_ma[t] if res.hist_ma is not None and t in res.hist_ma.columns else None,
                field=self.var_field.get(), show_ma=self.var_ma.get(),
                buy_date=res.rebalance_execution_date if t in res.locked_weights else None,
            )
        self.canvas_s.draw_idle()

    def _select_first_holding(self) -> None:
        kids = self.tree_hold.get_children("")
        self.sel_ticker = self.tree_hold.item(kids[0], "text").strip() if kids else None
        if kids:
            self.tree_hold.selection_set(kids[0])
        self._draw_stock()

    def _restore_selection(self) -> None:
        """Re-highlight the charted ticker after the tables were rebuilt."""
        for tree in (self.tree_hold, self.tree_next, self.tree_other):
            for iid in tree.get_children(""):
                if tree.item(iid, "text").strip() == self.sel_ticker:
                    tree.selection_set(iid)
                    return

    def _bar(self, ratio):
        """Cached accent-coloured weight bar (blank track when there is no weight)."""
        p = self.palette
        scale = max(1, round(self.winfo_fpixels("1i") / 96))
        step = 0 if ratio is None else max(0, min(20, int(round(ratio * 20))))
        key = (p.name, p.accent, p.surface2, step, scale, ratio is None)
        if key not in self._bar_imgs:
            self._bar_imgs[key] = bar_image(
                70 * scale, 8 * scale, 0 if ratio is None else step / 20,
                p.accent, p.surface2 if ratio is not None else p.surface,
            )
        return self._bar_imgs[key]

    def _fill_tree(self, tree: ttk.Treeview, rows) -> None:
        tree.delete(*tree.get_children(""))
        for ticker, values, tag, ratio in rows:
            tree.insert("", tk.END, text=" " + ticker, image=self._bar(ratio), values=values, tags=(tag,))

    def _update_param_warning(self, *_args) -> None:
        try:
            devs = vm.param_deviations(
                self._strategy_id_from_form(),
                universe_size=int(self.var_universe.get()),
                momentum_days=int(self.var_momentum.get()),
                top_n_limit=int(self.var_topn.get()),
                buffer_zone=float(self.var_buffer.get()),
            )
        except (ValueError, KeyError):
            return
        p = self.palette
        if devs:
            self.lbl_param_warn.config(
                text="⚠ 偏離已驗證設定：" + "、".join(devs) + "。改參數只影響次月，不動本月持倉。",
                foreground=p.danger,
            )
        else:
            self.lbl_param_warn.config(
                text="✓ 與已驗證設定一致（U60／M120／Top10／0.97）",
                foreground=p.ok,
            )

    def _build_briefing_tab(self, parent) -> None:
        ttk.Label(
            parent,
            text=(
                "市場簡報：以你的下月選股／雷達候選／產業同業為中心，抓取相關新聞；"
                "單日 ±10% 大波動會自動升級為深度分析。設定沿用「監控中心」分頁。"
            ),
            style="Muted.TLabel", wraplength=900, justify=tk.LEFT,
        ).pack(fill=tk.X, padx=16, pady=(12, 4))

        btn_row = ttk.Frame(parent)
        btn_row.pack(fill=tk.X, padx=14, pady=4)
        self.btn_briefing = ttk.Button(btn_row, text="▶ 產生市場簡報", style="Accent.TButton",
                                       command=self._on_generate_briefing)
        self.btn_briefing.pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_row, text="📄 儲存簡報", command=self._on_save_briefing).pack(side=tk.LEFT, padx=4)
        self.briefing_status = tk.StringVar(value="就緒")
        ttk.Label(btn_row, textvariable=self.briefing_status, style="Muted.TLabel").pack(side=tk.RIGHT, padx=8)

        frame, self.txt_briefing = scrolled_text(parent, wrap="word", highlightthickness=0, padx=14, pady=10)
        frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(4, 12))
        self._themed_text.append(self.txt_briefing)
        self._last_briefing = ""


    # ------------------------------------------------------------ performance tab
    def _build_perf_tab(self, parent) -> None:
        self.bt_df = None
        self.bt_meta: dict = {}
        self._bt_cancel = None
        self._bt_thread = None
        self._perf_swatches: dict = {}
        self.var_period = tk.StringVar(value="5")
        self.var_log = tk.BooleanVar(value=False)
        self.curve_vars = {k: tk.BooleanVar(value=True) for k in be.SERIES_LABELS}
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(2, weight=1)

        bar = ttk.Frame(parent)
        bar.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 4))
        self.btn_bt = ttk.Button(bar, text="⟳ 更新回測", style="Accent.TButton", command=self._on_update_backtest)
        self.btn_bt.pack(side=tk.LEFT)
        self.bt_status = tk.StringVar(value="")
        ttk.Label(bar, textvariable=self.bt_status, style="Muted.TLabel").pack(side=tk.LEFT, padx=12)
        right = ttk.Frame(bar)
        right.pack(side=tk.RIGHT)
        ttk.Label(right, text="期間", style="Muted.TLabel").pack(side=tk.LEFT, padx=(0, 4))
        for text, val in (("1年", "1"), ("3年", "3"), ("5年", "5"), ("全部", "all")):
            ttk.Radiobutton(right, text=text, value=val, variable=self.var_period,
                            command=self._draw_perf).pack(side=tk.LEFT, padx=3)
        ttk.Checkbutton(right, text="對數座標", variable=self.var_log, command=self._draw_perf).pack(
            side=tk.LEFT, padx=(12, 0))

        pick = ttk.Frame(parent)
        pick.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 4))
        for key, label in be.SERIES_LABELS.items():
            sw = tk.Label(pick, text="━━" if not key.endswith("_theory") else "╌╌", width=3)
            sw.pack(side=tk.LEFT, padx=(8, 0))
            self._perf_swatches[key] = sw
            ttk.Checkbutton(pick, text=label, variable=self.curve_vars[key], command=self._draw_perf).pack(
                side=tk.LEFT, padx=(0, 6))

        body = ttk.PanedWindow(parent, orient=tk.VERTICAL)
        body.grid(row=2, column=0, sticky="nsew", padx=14, pady=(0, 6))
        card = tk.Frame(body, bd=0, highlightthickness=1)
        card.columnconfigure(0, weight=1)
        card.rowconfigure(0, weight=1)
        self._chart_cards.append(card)
        body.add(card, weight=4)
        if Figure is not None:
            self.fig_p = Figure(figsize=(9, 3.6), dpi=max(96.0, self.winfo_fpixels("1i")))
            self.canvas_p = FigureCanvasTkAgg(self.fig_p, master=card)
            self.canvas_p.get_tk_widget().grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
            self.curves_chart = charts.CurvesChart(self.fig_p)
            self.canvas_p.mpl_connect(
                "motion_notify_event",
                lambda e: self.canvas_p.draw_idle() if self.curves_chart.on_move(e) else None,
            )
        else:
            self.curves_chart = None

        cols = ("總報酬", "年化", "波動", "Sharpe", "最大回撤", "Calmar", "期末(起點100)")
        tf = ttk.Frame(body)
        body.add(tf, weight=1)
        self.tree_perf = ttk.Treeview(tf, columns=cols, show="tree headings", height=6)
        self.tree_perf.heading("#0", text="策略")
        self.tree_perf.column("#0", width=200, stretch=False)
        for c in cols:
            self.tree_perf.heading(c, text=c)
            self.tree_perf.column(c, width=95, anchor=tk.E)
        self.tree_perf.pack(fill=tk.BOTH, expand=True)
        self._trees.append(self.tree_perf)

        self.lbl_notes = ttk.Label(parent, text="", style="Muted.TLabel", wraplength=1000, justify=tk.LEFT)
        self.lbl_notes.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 10))

        loaded = be.load_results(self.base_dir / "backtest_cache")
        if loaded:
            self.bt_df, self.bt_meta = loaded

    def _perf_years(self):
        v = self.var_period.get()
        return None if v == "all" else float(v)

    def _draw_perf(self) -> None:
        if getattr(self, "curves_chart", None) is None:
            return
        p = self.palette
        for key, sw in self._perf_swatches.items():
            sw.config(bg=p.bg, fg=charts.curve_style(p, key)["color"], font=self.fonts["ui_bold"])
        self.tree_perf.delete(*self.tree_perf.get_children(""))
        if self.bt_df is None:
            self.curves_chart.render(p, {}, message="尚未計算回測。按左上角「⟳ 更新回測」\n（首次需下載約 17 年行情，約 3～8 分鐘，之後存檔不用重算）")
            self.canvas_p.draw_idle()
            self.lbl_notes.config(text="")
            return
        wanted = {k: self.bt_df[k].dropna() for k in be.SERIES_LABELS
                  if k in self.bt_df.columns and self.curve_vars[k].get()}
        curves = be.slice_rebased(wanted, self._perf_years())
        self.curves_chart.render(p, curves, log=self.var_log.get(), message="請至少勾選一條曲線")
        self.canvas_p.draw_idle()
        for key, s in curves.items():
            st = be.perf_stats(s)
            self.tree_perf.insert("", tk.END, text="  " + be.SERIES_LABELS[key], values=(
                f"{st['total']:+.1f}%", f"{st['cagr']:+.1f}%", f"{st['vol']:.1f}%", f"{st['sharpe']:.2f}",
                f"{st['mdd']:.1f}%", f"{st['calmar']:.2f}", f"{st['final']:,.1f}"))
        m = self.bt_meta
        turn = {k: v.get("avg_monthly_turnover_pct") for k, v in m.get("stats", {}).items()}
        extra = f"　更新 {m.get('generated_at', '')[:16].replace('T', ' ')}，資料至 {m.get('data_end', '')}"
        if turn:
            extra += "　月均換手：" + "、".join(f"{m['specs'][k]['label']} {v}%" for k, v in turn.items())
        self.lbl_notes.config(text="；".join(m.get("notes", [])) + extra)

    def _on_update_backtest(self) -> None:
        if self._bt_thread is not None and self._bt_thread.is_alive():
            self._bt_cancel.set()
            self.bt_status.set("取消中…")
            return
        self._bt_cancel = threading.Event()
        self.btn_bt.config(text="⏹ 取消")

        def progress(msg: str) -> None:
            self.after(0, lambda m=msg: self.bt_status.set(m))

        def worker() -> None:
            try:
                from universe_builder import get_candidate_pool

                progress("取得 S&P 500 成分股…")
                pool, source = get_candidate_pool("dollar_volume")
                symbols = list(dict.fromkeys([*pool, be.BENCHMARK, be.EXTRA_BENCH]))
                end = pd.Timestamp.today().normalize()
                start = (end - pd.DateOffset(years=17, months=6)).strftime("%Y-%m-%d")
                close, opn, vol = be.download_history(
                    symbols, start, end.strftime("%Y-%m-%d"), progress=progress, cancel=self._bt_cancel.is_set)
                df, meta = be.compute_all(close, opn, vol, pool, progress=progress, cancel=self._bt_cancel.is_set)
                meta["pool_source"] = source
                be.save_results(self.base_dir / "backtest_cache", df, meta)
                self.after(0, lambda: self._bt_done(df, meta, None))
            except InterruptedError:
                self.after(0, lambda: self._bt_done(None, None, "已取消"))
            except Exception as e:  # noqa: BLE001 - surfaced to the user
                self.after(0, lambda msg=str(e): self._bt_done(None, None, msg))

        self._bt_thread = threading.Thread(target=worker, daemon=True)
        self._bt_thread.start()

    def _bt_done(self, df, meta, error) -> None:
        self.btn_bt.config(text="⟳ 更新回測")
        if error:
            self.bt_status.set(error if error == "已取消" else "回測失敗")
            if error != "已取消":
                messagebox.showerror("回測失敗", error)
            return
        self.bt_df, self.bt_meta = df, meta
        self.bt_status.set("完成")
        self._draw_perf()

    # --------------------------------------------------------------- theme
    def _load_prefs(self) -> dict:
        prefs = {"style": "Bloomberg", "mode": "dark", "red_up": True, "sidebar": True}
        try:
            prefs.update(json.loads((self.base_dir / "ui_prefs.json").read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        if prefs["style"] not in theme.STYLES:
            prefs["style"] = "Bloomberg"
        if prefs["mode"] not in theme.MODES:
            prefs["mode"] = "dark"
        return prefs

    def _set_pref(self, **changes) -> None:
        self.prefs.update(changes)
        try:
            (self.base_dir / "ui_prefs.json").write_text(json.dumps(self.prefs), encoding="utf-8")
        except OSError:
            pass
        self._apply_theme()

    def _toggle_mode(self) -> None:
        self._set_pref(mode="light" if self.prefs["mode"] == "dark" else "dark")

    def _toggle_updown(self) -> None:
        self._set_pref(red_up=not self.prefs["red_up"])

    def _toggle_sidebar(self) -> None:
        show = not self.prefs["sidebar"]
        self._set_pref(sidebar=show)

    def _apply_theme(self) -> None:
        p = theme.get_palette(self.prefs["style"], self.prefs["mode"], self.prefs["red_up"])
        self.palette = p
        self.fonts = theme.apply_ttk(self, p)
        f = self.fonts
        self.var_style.set(self.prefs["style"])
        self.btn_mode.config(text="☀ 淺色" if self.prefs["mode"] == "dark" else "☾ 深色")
        self.btn_updown.config(text="紅漲綠跌" if self.prefs["red_up"] else "綠漲紅跌")
        self.lbl_title.config(font=f["h1"], style="Side.TLabel")

        if self.prefs["sidebar"]:
            self.sidebar.grid()
            self.btn_sidebar.config(text="⇤ 收合設定")
        else:
            self.sidebar.grid_remove()
            self.btn_sidebar.config(text="⇥ 展開設定")

        for card in self.cards.values():
            card.restyle(p, f)
        for box, bg in [(b, p.surface) for b in self._themed_text] + [(b, p.surface2) for b in self._themed_inputs]:
            box.config(bg=bg, fg=p.text, insertbackground=p.text, selectbackground=p.accent,
                       selectforeground=p.accent_fg, font=f["data"],
                       highlightbackground=p.border, highlightcolor=p.accent)

        for tree in self._trees:
            tree.tag_configure("accel", background=p.surface)
            tree.tag_configure("brake", background=theme.tint(p.warn, p.surface, 0.18))
            tree.tag_configure("below_ma", background=theme.tint(p.danger, p.surface, 0.24))
            tree.tag_configure("new", background=theme.tint(p.accent, p.surface, 0.18))
        self._update_param_warning()
        self._refresh_window_title()
        for card in getattr(self, "_chart_cards", []):
            card.config(bg=p.surface, highlightbackground=p.border, highlightcolor=p.border)
        for lbl in (getattr(self, "lbl_w", None), getattr(self, "lbl_s", None)):
            if lbl is not None:
                lbl.config(bg=p.surface, fg=p.muted, font=f["small"])
        for fr in getattr(self, "_chart_heads", []):
            if isinstance(fr, tk.Frame):
                fr.config(bg=p.surface)
        if getattr(self, "_last_result", None):  # bar images embed palette colours
            self._render_trees(*self._last_result)
            self._restore_selection()
        self._draw_weights()
        self._draw_stock()
        self._draw_perf()

    def _on_param_edited(self, *_args) -> None:
        from strategy_presets import STRATEGY_CUSTOM

        if self._suppress_param_trace:
            return
        if self._strategy_id_from_form() != STRATEGY_CUSTOM:
            self._set_strategy_combo(STRATEGY_CUSTOM)
            self.status.set("已切換為自訂參數")

    def _strategy_id_from_form(self) -> str:
        label = self.var_strategy.get()
        return normalize_strategy_id(self._strategy_map.get(label, label))

    def _set_strategy_combo(self, strategy_id: str) -> None:
        sid = normalize_strategy_id(strategy_id)
        for label, id_ in self._strategy_map.items():
            if id_ == sid:
                self.var_strategy.set(label)
                return
        self.var_strategy.set(preset_choices()[0][1])

    def _on_strategy_change(self, _event=None) -> None:
        from strategy_presets import STRATEGY_CUSTOM

        base = self._loaded_cfg or ApexConfig()
        base = ApexConfig(
            query_date=self.var_date.get().strip(),
            current_month_capital_twd=float(self.var_capital.get().replace(",", "") or 0),
            next_month_injection_twd=float(self.var_inject.get().replace(",", "") or 0),
            user_tickers=self.txt_tickers.get("1.0", tk.END).replace("\n", " ").strip(),
            tw_tickers=self.txt_tw.get("1.0", tk.END).replace("\n", " ").strip(),
            strategy_id=self._strategy_id_from_form(),
            universe_size=int(self.var_universe.get() or base.universe_size),
            universe_mode=base.universe_mode,
            universe_momentum_days=base.universe_momentum_days,
            universe_last_updated=base.universe_last_updated,
            top_n_limit=int(self.var_topn.get() or base.top_n_limit),
            momentum_days=int(self.var_momentum.get() or base.momentum_days),
            buffer_zone=float(self.var_buffer.get() or base.buffer_zone),
        )
        sid = base.strategy_id
        if sid == STRATEGY_CUSTOM:
            self._loaded_cfg = base
            self._refresh_window_title()
            self.status.set("自訂參數 — 請手動調整宇宙 / 動能 / Top N")
            return
        cfg = apply_preset(base, sid)
        self._suppress_param_trace = True
        try:
            self.var_universe.set(str(cfg.universe_size))
            self.var_topn.set(str(cfg.top_n_limit))
            self.var_momentum.set(str(cfg.momentum_days))
            self.var_buffer.set(str(cfg.buffer_zone))
        finally:
            self._suppress_param_trace = False
        self._loaded_cfg = cfg
        self._refresh_window_title()
        self._update_param_warning()
        self.status.set(f"已切換 → {cfg.strategy_id}（{product_name(cfg.strategy_id)}）")

    def _cfg_from_form(self) -> ApexConfig:
        base = self._loaded_cfg or ApexConfig()
        sid = self._strategy_id_from_form()
        return ApexConfig(
            query_date=self.var_date.get().strip(),
            current_month_capital_twd=float(self.var_capital.get().replace(",", "")),
            next_month_injection_twd=float(self.var_inject.get().replace(",", "")),
            user_tickers=self.txt_tickers.get("1.0", tk.END).replace("\n", " ").strip(),
            tw_tickers=self.txt_tw.get("1.0", tk.END).replace("\n", " ").strip(),
            strategy_id=sid,
            universe_size=int(self.var_universe.get()),
            universe_mode=base.universe_mode,
            universe_momentum_days=base.universe_momentum_days,
            universe_last_updated=base.universe_last_updated,
            top_n_limit=int(self.var_topn.get()),
            buffer_zone=float(self.var_buffer.get()),
            momentum_days=int(self.var_momentum.get()),
            transaction_cost=base.transaction_cost,
            max_weight_cap=base.max_weight_cap,
            volatility_days=base.volatility_days,
            ma_days=base.ma_days,
            breadth_threshold=base.breadth_threshold,
            show_market_mode=base.show_market_mode,
        )

    def _form_from_cfg(self, cfg: ApexConfig) -> None:
        self._suppress_param_trace = True
        try:
            self._loaded_cfg = cfg
            self._set_strategy_combo(cfg.strategy_id)
            self.var_date.set(cfg.query_date)
            self.var_capital.set(str(int(cfg.current_month_capital_twd)))
            self.var_inject.set(str(int(cfg.next_month_injection_twd)))
            self.var_universe.set(str(cfg.universe_size))
            self.var_topn.set(str(cfg.top_n_limit))
            self.var_momentum.set(str(cfg.momentum_days))
            self.var_buffer.set(str(cfg.buffer_zone))
            self.txt_tickers.delete("1.0", tk.END)
            self.txt_tickers.insert(tk.END, ", ".join(parse_ticker_csv(cfg.user_tickers)))
            self.txt_tw.delete("1.0", tk.END)
            self.txt_tw.insert(tk.END, ", ".join(parse_ticker_csv(cfg.tw_tickers)))
        finally:
            self._suppress_param_trace = False
        self._refresh_window_title()

    def _load_from_file(self, silent: bool = False) -> None:
        if not self.config_path.exists():
            if not silent:
                messagebox.showwarning("提示", f"找不到 {self.config_path}\n請先填寫設定後儲存。")
            return
        try:
            self._form_from_cfg(load_config(self.config_path))
            self.status.set(f"已載入 {self.config_path.name}")
        except Exception as e:
            messagebox.showerror("載入失敗", str(e))

    def _on_load_config(self) -> None:
        path = filedialog.askopenfilename(
            title="選擇設定檔",
            filetypes=[("YAML", "*.yaml"), ("All", "*.*")],
            initialdir=str(self.base_dir),
        )
        if path:
            self.config_path = Path(path)
            self._load_from_file()

    def _on_save_config(self) -> None:
        try:
            cfg = self._cfg_from_form()
            if parse_ticker_csv(cfg.user_tickers):
                cfg.universe_last_updated = ensure_universe_cycle_stamp(
                    cfg.universe_last_updated,
                    cfg.query_date,
                )
            save_config(self.config_path, cfg)
            self._loaded_cfg = cfg
            st = universe_refresh_status(cfg.universe_last_updated, cfg.query_date)
            self.status.set(f"設定已儲存 -> {self.config_path}")
            messagebox.showinfo(
                "完成",
                f"設定已儲存至\n{self.config_path}\n\n{st['message']}",
            )
        except Exception as e:
            messagebox.showerror("儲存失敗", str(e))

    def _on_save_report(self) -> None:
        if not self._last_report:
            messagebox.showinfo("提示", "請先執行監控。")
            return
        path = filedialog.asksaveasfilename(
            title="儲存報告",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
            initialfile=f"apex_r_report_{self.var_date.get()}.txt",
            initialdir=str(self.base_dir),
        )
        if path:
            Path(path).write_text(self._last_report, encoding="utf-8")
            self.status.set(f"報告已儲存 -> {path}")

    def _on_refresh_universe(self) -> None:
        cfg = self._cfg_from_form()
        allowed, reason = can_refresh_universe(
            cfg.universe_last_updated,
            cfg.query_date,
            force=False,
        )
        if not allowed:
            force = messagebox.askyesno(
                "宇宙兩年週期未到",
                f"{reason}\n\n"
                "建議時機：滿兩年後、換倉決策日之前、盡量靠近年初再整池刷新。\n\n"
                "仍要強制更新美股宇宙？\n"
                "（不建議：會讓「鎖定持倉」與回測假設脫鉤）",
                icon="warning",
            )
            if not force:
                self.status.set("已取消宇宙更新（兩年週期保護）")
                return
            force_flag = True
        else:
            force_flag = False
            if not (cfg.universe_last_updated or "").strip():
                messagebox.showinfo(
                    "首次宇宙更新",
                    f"{reason}\n更新完成後將寫入 universe_last_updated，約兩年內預設不可再刷。",
                )

        self.btn_refresh.config(state=tk.DISABLED)
        self.btn_run.config(state=tk.DISABLED)
        self.status.set("更新美股宇宙中… (約 1～3 分鐘)")

        def worker() -> None:
            try:
                cfg_w = self._cfg_from_form()
                tw = parse_ticker_csv(cfg_w.tw_tickers)
                result = build_universe(
                    as_of=cfg_w.query_date,
                    top_n=cfg_w.universe_size or 65,
                    tw_tickers=tw,
                    mode=cfg_w.universe_mode or "dollar_volume",
                    momentum_days=cfg_w.universe_momentum_days or 504,
                )
                cfg_w.user_tickers = ", ".join(result.us_tickers)
                cfg_w.universe_last_updated = result.as_of
                summary = "\n".join(result.summary_lines())
                note = universe_refresh_status(cfg_w.universe_last_updated, cfg_w.query_date)["message"]
                if force_flag:
                    summary = f"[強制更新]\n{summary}\n\n{note}"
                else:
                    summary = f"{summary}\n\n{note}"
                self.after(0, lambda: self._show_universe_refresh(cfg_w, summary))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._show_universe_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _show_universe_refresh(self, cfg: ApexConfig, summary: str) -> None:
        self._loaded_cfg = cfg
        self._form_from_cfg(cfg)
        self.txt_report.delete("1.0", tk.END)
        self.txt_report.insert(tk.END, summary + "\n\n請按「儲存設定」以寫入 config.yaml。")
        self.result_nb.select(self.result_nb.tabs()[-1])
        self.status.set(f"宇宙已更新 | 美股 {len(parse_ticker_csv(cfg.user_tickers))} + 台股 {len(parse_ticker_csv(cfg.tw_tickers))} 檔")
        self.btn_refresh.config(state=tk.NORMAL)
        self.btn_run.config(state=tk.NORMAL)
        messagebox.showinfo("宇宙更新完成", summary)

    def _show_universe_error(self, msg: str) -> None:
        self.status.set("宇宙更新失敗")
        self.btn_refresh.config(state=tk.NORMAL)
        self.btn_run.config(state=tk.NORMAL)
        messagebox.showerror("宇宙更新失敗", msg)

    def _on_relock(self) -> None:
        if not messagebox.askyesno(
            "重新鎖定本月",
            "本月的標的與權重已寫定、月內不應變動。\n\n"
            "只有在首次鎖定時資料有誤等例外情況才應重新鎖定。\n"
            "確定要用目前的設定覆寫本月鎖定嗎？",
            default=messagebox.NO,
            icon=messagebox.WARNING,
        ):
            return
        self._on_run(relock=True)

    def _on_run(self, relock: bool = False) -> None:
        self.btn_run.config(state=tk.DISABLED)
        self.btn_relock.config(state=tk.DISABLED)
        self.status.set("下載行情中（首次可能較慢，成功後會快取）…")
        self.txt_report.delete("1.0", tk.END)
        self.txt_report.insert(tk.END, "正在連線 Yahoo Finance 並計算，約需 10～30 秒…\n")
        self.result_nb.select(self.result_nb.tabs()[-1])

        def worker() -> None:
            try:
                cfg = self._cfg_from_form()
                result = run_monitor(cfg, book_store=default_store(), relock=relock)
                report = format_report(result, strategy_id=cfg.strategy_id, cfg=cfg)
                self.after(0, lambda: self._show_report(report, cfg, result))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._show_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _show_report(self, report: str, cfg: ApexConfig, result=None) -> None:
        self._last_report = report
        self.txt_report.delete("1.0", tk.END)
        self.txt_report.insert(tk.END, report)
        if result is not None:
            self._show_result(result, cfg)
            self.result_nb.select(self.result_nb.tabs()[0])
        self.status.set(f"完成 | 宇宙 {len(cfg.ticker_list())} 檔")
        self.btn_run.config(state=tk.NORMAL)
        self.btn_relock.config(state=tk.NORMAL)

    def _render_trees(self, result, cfg: ApexConfig) -> None:
        w_max = cfg.max_weight_cap
        self._fill_tree(self.tree_hold, vm.holding_rows(result, w_max))
        self._fill_tree(self.tree_next, vm.next_rows(result, w_max))
        self._fill_tree(self.tree_other, vm.other_rows(result))

    def _show_result(self, result, cfg: ApexConfig) -> None:
        self._last_result = (result, cfg)
        self._render_trees(result, cfg)
        self._draw_weights()
        self._select_first_holding()
        keys = ["asset", "pnl", "exposure", "regime", "theme", "lock"]
        for key, spec in zip(keys, vm.kpi_cards(result, cfg.current_month_capital_twd)):
            self.cards[key].set(spec["value"], spec["sub"], spec["tone"])
        note = f"　⚠ {result.book_lock_note}" if result.book_lock_note else ""
        self.lbl_exposure.config(text=f"查詢日 {result.query_date.strftime('%Y-%m-%d')}{note}")

    def _show_error(self, msg: str) -> None:
        self.txt_report.delete("1.0", tk.END)
        self.txt_report.insert(tk.END, f"錯誤：\n{msg}")
        self.result_nb.select(self.result_nb.tabs()[-1])
        self.status.set("執行失敗")
        self.btn_run.config(state=tk.NORMAL)
        self.btn_relock.config(state=tk.NORMAL)
        messagebox.showerror("執行失敗", msg)

    def _on_generate_briefing(self) -> None:
        self.btn_briefing.config(state=tk.DISABLED)
        self.briefing_status.set("執行中…")
        self.txt_briefing.delete("1.0", tk.END)
        self.txt_briefing.insert(
            tk.END, "正在跑 Apex-R 監控並抓取相關新聞，約需 20～60 秒…\n"
        )

        def set_progress(msg: str) -> None:
            self.after(0, lambda: self.briefing_status.set(msg))

        def worker() -> None:
            try:
                from briefing import build_briefing

                cfg = self._cfg_from_form()
                result = run_monitor(cfg, book_store=default_store())
                text = build_briefing(result, cfg, progress=set_progress)
                self.after(0, lambda: self._show_briefing(text, cfg))
            except Exception as e:
                self.after(0, lambda msg=str(e): self._show_briefing_error(msg))

        threading.Thread(target=worker, daemon=True).start()

    def _show_briefing(self, text: str, cfg: ApexConfig) -> None:
        self._last_briefing = text
        self.txt_briefing.delete("1.0", tk.END)
        self.txt_briefing.insert(tk.END, text)
        self.briefing_status.set("完成")
        self.btn_briefing.config(state=tk.NORMAL)

    def _show_briefing_error(self, msg: str) -> None:
        self.txt_briefing.delete("1.0", tk.END)
        self.txt_briefing.insert(tk.END, f"產生簡報失敗：\n{msg}")
        self.briefing_status.set("失敗")
        self.btn_briefing.config(state=tk.NORMAL)
        messagebox.showerror("產生簡報失敗", msg)

    def _on_save_briefing(self) -> None:
        if not getattr(self, "_last_briefing", ""):
            messagebox.showinfo("提示", "請先產生市場簡報。")
            return
        path = filedialog.asksaveasfilename(
            title="儲存市場簡報",
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
            initialfile=f"apex_r_briefing_{date.today()}.txt",
            initialdir=str(self.base_dir),
        )
        if path:
            Path(path).write_text(self._last_briefing, encoding="utf-8")
            self.briefing_status.set(f"已儲存 -> {path}")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Apex 桌面監控（Apex-R / Apex-M）")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="設定檔路徑（預設 config.yaml；Apex-M 用 config_apex_m.yaml）",
    )
    args = parser.parse_args()
    cfg_path = args.config.resolve() if args.config else None

    try:
        app = ApexRApp(config_path=cfg_path)
        app.mainloop()
    except Exception:
        import traceback

        err = traceback.format_exc()
        log_path = app_base_dir() / "apex_r_error.log"
        try:
            log_path.write_text(err, encoding="utf-8")
        except Exception:
            pass
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Apex 啟動失敗",
                f"{err}\n\n（錯誤已寫入 {log_path.name}）",
            )
            root.destroy()
        except Exception:
            print(err, file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
