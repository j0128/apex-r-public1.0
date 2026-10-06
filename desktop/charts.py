"""Matplotlib charts for the desktop GUI (no pyplot, no Tk — testable headless).

WeightsChart : donut of the locked book weights (+ cash) with a ticker legend.
StockChart   : daily dot-line of one ticker, open/close switch, 200MA, buy price,
               crosshair tooltip on hover.
"""

from __future__ import annotations

import sys
from typing import Dict, Optional

import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
import pandas as pd

from theme import Palette, font_families

_CAT_DARK = ["#5aa9e6", "#f4a259", "#7bc67e", "#e06c75", "#b48ead", "#e5c07b",
             "#56b6c2", "#d19a66", "#98c379", "#c678dd", "#61afef", "#be5046"]
_CAT_LIGHT = ["#1f77b4", "#d9691f", "#2f9e44", "#c92a3a", "#7b4fa3", "#a77a0b",
              "#0e8a9b", "#a8541a", "#5c8a1e", "#9c2fb0", "#2f6fd1", "#8f2d20"]


def is_dark(p: Palette) -> bool:
    return p.name.endswith("深色")


def categorical(p: Palette) -> list:
    return _CAT_DARK if is_dark(p) else _CAT_LIGHT


_FONT_CHOICE: Optional[str] = None


def _font_stack() -> str:
    """First installed CJK-capable font (avoids matplotlib's per-glyph fallback warnings)."""
    global _FONT_CHOICE
    if _FONT_CHOICE is None:
        from matplotlib import font_manager

        have = {f.name for f in font_manager.fontManager.ttflist}
        ui, _mono = font_families()
        for name in (ui, "Microsoft JhengHei", "PingFang TC", "Noto Sans CJK TC",
                     "Noto Sans TC", "WenQuanYi Zen Hei", "DejaVu Sans"):
            if name in have:
                _FONT_CHOICE = name
                break
        else:
            _FONT_CHOICE = "DejaVu Sans"
    return _FONT_CHOICE


def style_axes(fig, ax, p: Palette) -> None:
    fig.set_facecolor(p.surface)
    ax.set_facecolor(p.surface)
    for side, spine in ax.spines.items():
        spine.set_color(p.border)
        spine.set_visible(side in ("left", "bottom"))
    ax.tick_params(colors=p.muted, labelsize=8, length=3)
    ax.grid(True, color=p.border, linewidth=0.6, linestyle=":", alpha=0.9)
    ax.set_axisbelow(True)


class WeightsChart:
    def __init__(self, fig) -> None:
        self.fig = fig

    def render(self, p: Palette, weights: Dict[str, float], buffer_zone: float = 0.97) -> None:
        fig = self.fig
        fig.clear()
        fig.set_facecolor(p.surface)
        fonts = _font_stack()
        ax = fig.add_axes([0.0, 0.04, 0.46, 0.92])
        leg = fig.add_axes([0.47, 0.04, 0.53, 0.92])
        leg.axis("off")
        ax.set_facecolor(p.surface)
        if not weights:
            ax.axis("off")
            leg.text(0.0, 0.5, "尚無資料", color=p.muted, fontsize=10, family=fonts)
            return

        items = sorted(weights.items(), key=lambda kv: kv[1], reverse=True)
        invested = sum(w for _, w in items)
        cash = max(1.0 - invested, 0.0)
        cols = categorical(p)
        colors = [cols[i % len(cols)] for i in range(len(items))]
        values = [w for _, w in items]
        labels = [t for t, _ in items]
        if cash > 1e-6:
            values.append(cash)
            labels.append("現金")
            colors.append(p.border)
        ax.pie(values, colors=colors, startangle=90, counterclock=False,
               wedgeprops=dict(width=0.36, edgecolor=p.surface, linewidth=1.5))
        ax.set_aspect("equal")
        ax.text(0, 0.08, f"{invested * 100:.0f}%", ha="center", va="center", color=p.text,
                fontsize=17, fontweight="bold", family=fonts)
        ax.text(0, -0.2, "已投入", ha="center", va="center", color=p.muted, fontsize=8, family=fonts)

        n = len(labels)
        step = min(0.085, 0.94 / max(n, 1))
        y = 0.97
        for lab, val, col in zip(labels, values, colors):
            leg.add_patch(Rectangle(
                (0.0, y - step * 0.62), 0.05, step * 0.5, transform=leg.transAxes, color=col, lw=0))
            leg.text(0.09, y - step * 0.37, lab, color=p.text, fontsize=9, va="center", family=fonts)
            leg.text(0.78, y - step * 0.37, f"{val * 100:.1f}%", color=p.muted, fontsize=9,
                     va="center", ha="right", family=fonts)
            y -= step


class StockChart:
    """Daily price dots+line for one ticker with optional 200MA / buy markers."""

    def __init__(self, fig) -> None:
        self.fig = fig
        self.ax = None
        self._x = None
        self._y = None
        self._hover = None
        self._p: Optional[Palette] = None

    def render(
        self,
        p: Palette,
        ticker: Optional[str],
        close: Optional[pd.Series],
        open_: Optional[pd.Series],
        ma: Optional[pd.Series],
        *,
        field: str = "close",
        show_ma: bool = True,
        buy_date: Optional[pd.Timestamp] = None,
    ) -> None:
        fig = self.fig
        fig.clear()
        self._p = p
        fonts = _font_stack()
        ax = fig.add_axes([0.075, 0.13, 0.905, 0.70])
        self.ax = ax
        style_axes(fig, ax, p)
        self._hover = None
        self._x = self._y = None

        if ticker is None or close is None or close.dropna().empty:
            ax.axis("off")
            ax.text(0.5, 0.5, "點選上方表格的股票以顯示近 200 日走勢", ha="center", va="center",
                    color=p.muted, fontsize=10, family=fonts, transform=ax.transAxes)
            return

        series = (open_ if field == "open" and open_ is not None else close).dropna()
        label = "開盤價" if field == "open" and open_ is not None else "收盤價"
        self._x, self._y = series.index, series.values
        ax.plot(series.index, series.values, color=p.accent, linewidth=1.3, marker="o",
                markersize=2.6, markerfacecolor=p.accent, markeredgewidth=0, label=label, zorder=3)

        ma_last = None
        if show_ma and ma is not None and not ma.dropna().empty:
            m = ma.dropna()
            ax.plot(m.index, m.values, color=p.text, alpha=0.75, linewidth=1.2, linestyle="--", zorder=2)
            ma_last = float(m.iloc[-1])
            ax.annotate(f"200MA {ma_last:,.2f}", (m.index[-1], ma_last), xytext=(-4, -12),
                        textcoords="offset points", ha="right", va="top", fontsize=8,
                        color=p.text, family=fonts)

        buy_px = None
        if buy_date is not None and open_ is not None:
            try:
                buy_px = float(open_.loc[buy_date])
            except (KeyError, TypeError, ValueError):
                buy_px = None
        if buy_px and buy_px > 0:
            ax.axhline(buy_px, color=p.muted, linewidth=1.0, linestyle=(0, (1, 2)), zorder=1)
            ax.axvline(buy_date, color=p.muted, linewidth=0.8, linestyle=(0, (1, 3)), zorder=1)
            ax.annotate(f"月初買入 {buy_px:,.2f}", (series.index[0], buy_px), xytext=(4, 3),
                        textcoords="offset points", ha="left", va="bottom", fontsize=8,
                        color=p.muted, family=fonts)

        last = float(close.dropna().iloc[-1])
        parts = [f"{ticker}", f"最新 {last:,.2f}"]
        if ma_last:
            parts.append(f"距200MA {(last / ma_last - 1) * 100:+.1f}%")
        if buy_px:
            parts.append(f"距買入 {(last / buy_px - 1) * 100:+.1f}%")
        ax.set_title("　｜　".join(parts), loc="left", color=p.text, fontsize=10,
                     fontweight="bold", family=fonts, pad=10)

        loc = mdates.AutoDateLocator(minticks=4, maxticks=8)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
        lo, hi = float(min(series.min(), ma.dropna().min() if (show_ma and ma is not None and not ma.dropna().empty) else series.min())), float(series.max())
        pad = (hi - lo) * 0.08 or 1.0
        ax.set_ylim(lo - pad, hi + pad)
        ax.margins(x=0.01)
        # hover artists
        self._vline = ax.axvline(series.index[-1], color=p.text, linewidth=0.7, alpha=0.0, zorder=4)
        self._dot, = ax.plot([series.index[-1]], [series.values[-1]], marker="o", markersize=6,
                             color=p.text, alpha=0.0, zorder=5)
        self._tip = ax.annotate("", xy=(0, 0), xytext=(10, 12), textcoords="offset points",
                                fontsize=8, color=p.text, family=fonts, zorder=6,
                                bbox=dict(boxstyle="round,pad=0.35", fc=p.surface2, ec=p.border, lw=0.8),
                                annotation_clip=False)
        self._tip.set_visible(False)

    # ---- hover -----------------------------------------------------------
    def on_move(self, event) -> bool:
        """Show crosshair + tooltip nearest to the cursor. Returns True if redraw needed."""
        if self._x is None or event.inaxes is not self.ax or event.xdata is None:
            return self._hide()
        xs = mdates.date2num(self._x)
        i = int(abs(xs - event.xdata).argmin())
        x, y = self._x[i], float(self._y[i])
        self._vline.set_xdata([x, x])
        self._vline.set_alpha(0.35)
        self._dot.set_data([x], [y])
        self._dot.set_alpha(1.0)
        self._tip.xy = (x, y)
        self._tip.set_text(f"{pd.Timestamp(x):%Y-%m-%d}\n{y:,.2f}")
        flip = i > len(xs) * 0.7
        self._tip.set_position((-70 if flip else 10, 12))
        self._tip.set_visible(True)
        return True

    def _hide(self) -> bool:
        if getattr(self, "_tip", None) is None or not self._tip.get_visible():
            return False
        self._tip.set_visible(False)
        self._vline.set_alpha(0.0)
        self._dot.set_alpha(0.0)
        return True


# ---------------------------------------------------------------- performance curves
CURVE_LABELS = {
    "apex_r_theory": "Apex-R 理論值",
    "apex_r_net": "Apex-R 扣成本",
    "apex_m_theory": "Apex-M 理論值",
    "apex_m_net": "Apex-M 扣成本",
    "SPY": "SPY",
    "QQQ": "QQQ",
}


def curve_style(p: Palette, key: str) -> dict:
    """Colour / dash per series: theory = thin dashed, net = solid, same hue per strategy."""
    cat = categorical(p)
    hue = {"apex_r": p.accent, "apex_m": cat[4], "SPY": p.text, "QQQ": cat[2]}
    base = key.rsplit("_", 1)[0] if key.endswith(("_theory", "_net")) else key
    color = hue[base]
    if key.endswith("_theory"):
        return dict(color=color, linestyle=(0, (4, 2)), linewidth=1.1, alpha=0.95)
    if key in ("SPY", "QQQ"):
        return dict(color=color, linestyle="-", linewidth=1.2, alpha=0.6 if key == "SPY" else 0.9)
    return dict(color=color, linestyle="-", linewidth=1.9, alpha=1.0)


class CurvesChart:
    """Multi-series equity curves (base 100) with legend returns and hover tooltip."""

    def __init__(self, fig) -> None:
        self.fig = fig
        self.ax = None
        self._series: Dict[str, pd.Series] = {}
        self._tip = None

    def render(self, p: Palette, curves: Dict[str, pd.Series], *, log: bool = False,
               message: str = "") -> None:
        fig = self.fig
        fig.clear()
        fonts = _font_stack()
        ax = fig.add_axes([0.07, 0.11, 0.91, 0.84])
        self.ax = ax
        style_axes(fig, ax, p)
        self._series = {}
        self._tip = None
        if not curves:
            ax.axis("off")
            ax.text(0.5, 0.5, message or "沒有可顯示的曲線", ha="center", va="center", color=p.muted,
                    fontsize=11, family=fonts, transform=ax.transAxes)
            return
        for key, s in curves.items():
            st = curve_style(p, key)
            ret = (s.iloc[-1] / s.iloc[0] - 1) * 100
            ax.plot(s.index, s.values, label=f"{CURVE_LABELS.get(key, key)}  {ret:+.0f}%", **st)
        self._series = curves
        if log:
            ax.set_yscale("log")
            from matplotlib.ticker import FuncFormatter, NullFormatter
            ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.0f}"))
            ax.yaxis.set_minor_formatter(NullFormatter())
        ax.axhline(100, color=p.border, linewidth=0.8, zorder=1)
        loc = mdates.AutoDateLocator(minticks=4, maxticks=9)
        ax.xaxis.set_major_locator(loc)
        ax.xaxis.set_major_formatter(mdates.ConciseDateFormatter(loc))
        ax.margins(x=0.01)
        leg = ax.legend(loc="upper left", fontsize=8, frameon=True, framealpha=0.85,
                        facecolor=p.surface, edgecolor=p.border, prop={"family": fonts, "size": 8})
        for t in leg.get_texts():
            t.set_color(p.text)
        self._vline = ax.axvline(next(iter(curves.values())).index[-1], color=p.text, linewidth=0.7, alpha=0.0)
        self._tip = ax.annotate("", xy=(0, 0), xytext=(14, -14), textcoords="offset points", fontsize=8,
                                color=p.text, family=fonts, va="top", zorder=6, annotation_clip=False,
                                bbox=dict(boxstyle="round,pad=0.4", fc=p.surface2, ec=p.border, lw=0.8))
        self._tip.set_visible(False)

    def on_move(self, event) -> bool:
        if not self._series or event.inaxes is not self.ax or event.xdata is None:
            return self._hide()
        day = pd.Timestamp(mdates.num2date(event.xdata)).tz_localize(None).normalize()
        lines, anchor = [f"{day:%Y-%m-%d}"], None
        for key, s in self._series.items():
            pos = s.index.searchsorted(day)
            pos = min(max(pos, 0), len(s) - 1)
            if pos > 0 and abs((s.index[pos - 1] - day).days) < abs((s.index[pos] - day).days):
                pos -= 1
            v = float(s.iloc[pos])
            lines.append(f"{CURVE_LABELS.get(key, key):<12} {v:>8,.1f}  ({v - 100:+.0f}%)")
            if anchor is None:
                anchor = (s.index[pos], v)
        self._vline.set_xdata([anchor[0], anchor[0]])
        self._vline.set_alpha(0.35)
        self._tip.xy = anchor
        self._tip.set_text("\n".join(lines))
        x0, x1 = self.ax.get_xlim()
        flip = event.xdata > x0 + (x1 - x0) * 0.6
        self._tip.set_position((-200 if flip else 14, -14))
        self._tip.set_visible(True)
        return True

    def _hide(self) -> bool:
        if self._tip is None or not self._tip.get_visible():
            return False
        self._tip.set_visible(False)
        self._vline.set_alpha(0.0)
        return True
