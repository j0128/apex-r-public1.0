"""Pure view logic for the desktop GUI (no tkinter): badges, rows, warnings."""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from apex_core import THEME_WARN_HARD, THEME_WARN_SOFT, MonitorResult
from strategy_presets import STRATEGY_CUSTOM, STRATEGY_RDYN_W, get_preset, normalize_strategy_id

# Parameters validated by backtests (U60 / ROC120 / Top10 / 97% invested).
STANDARD_PARAMS: Dict[str, float] = {
    "universe_size": 60,
    "momentum_days": 120,
    "top_n_limit": 10,
    "buffer_zone": 0.97,
}
_LABELS = {
    "universe_size": "宇宙數",
    "momentum_days": "動能日",
    "top_n_limit": "Top N",
    "buffer_zone": "Buffer",
}

OK, WARN, BAD, INFO = "ok", "warn", "bad", "info"


def param_deviations(
    strategy_id: str,
    *,
    universe_size: int,
    momentum_days: int,
    top_n_limit: int,
    buffer_zone: float,
) -> List[str]:
    """Human-readable differences from the reference parameters.

    The RDyn-W line (and custom parameters) are compared with the validated
    standard U60/M120/Top10; other presets (e.g. Apex-M) with their own values.
    """
    sid = normalize_strategy_id(strategy_id)
    if sid in (STRATEGY_CUSTOM, STRATEGY_RDYN_W):
        ref = dict(STANDARD_PARAMS)
    else:
        p = get_preset(sid)
        ref = {
            "universe_size": p.universe_size,
            "momentum_days": p.momentum_days,
            "top_n_limit": p.top_n_limit,
            "buffer_zone": p.buffer_zone,
        }
    cur = {
        "universe_size": universe_size,
        "momentum_days": momentum_days,
        "top_n_limit": top_n_limit,
        "buffer_zone": buffer_zone,
    }
    out = []
    for k, label in _LABELS.items():
        if abs(float(cur[k]) - float(ref[k])) > 1e-9:
            out.append(f"{label} {cur[k]}（標準 {ref[k]}）")
    return out


def lock_badge(result: MonitorResult) -> Tuple[str, str]:
    st = result.book_lock_status
    if not st:
        return "🔓 未啟用月度鎖定", WARN
    stamp = (result.book_locked_at or "").replace("T", " ")
    ym = result.rebalance_execution_date.strftime("%Y-%m")
    if st == "reused":
        return f"🔒 {ym} 持倉已鎖定（{stamp}），月內不變", OK
    if st == "relocked":
        return f"🔒 {ym} 已重新鎖定（{stamp}）", WARN
    return f"🔒 {ym} 持倉剛鎖定（{stamp}），月內不變", OK


def regime_badge(result: MonitorResult) -> Tuple[str, str]:
    text = result.market_mode or "—"
    if result.rdyn_blend_label:
        text += f"｜下月混合 {result.rdyn_blend_label}"
    level = OK if "晴空" in text else BAD if "避難" in text else WARN if "虛胖" in text else INFO
    return text, level


def theme_badge(result: MonitorResult) -> Tuple[str, str]:
    w = result.theme_ai_hw_weight
    level = BAD if w >= THEME_WARN_HARD else WARN if w >= THEME_WARN_SOFT else OK
    return f"題材集中度 {w * 100:.0f}%", level


def exposure_line(result: MonitorResult) -> str:
    return (
        f"查詢日 {result.query_date.strftime('%Y-%m-%d')}｜匯率 {result.fx_rate:.2f}｜"
        f"有效曝險 {result.effective_exposure * 100:.1f}%｜現金 {result.cash_drag_pct:.1f}%｜"
        f"估值 NT${result.final_assets_twd:,.0f}"
    )


def weight_bar(w: float, w_max: float = 0.10, width: int = 10) -> str:
    if w_max <= 0:
        return ""
    n = max(0, min(width, int(round(w / w_max * width))))
    return "█" * n + "·" * (width - n)


def row_tag(alert: str, dist_ma: float) -> str:
    if dist_ma < 0:
        return "below_ma"
    return "brake" if "煞車" in alert else "accel"


def holding_rows(result: MonitorResult, w_max: float = 0.10) -> List[tuple]:
    """(ticker, values, tag, bar_ratio) per row; values follow VALUE_COLUMNS."""
    rows = []
    for h in result.holdings:
        w = result.locked_weights.get(h.ticker, 0.0)
        rows.append(
            (
                h.ticker,
                (
                    f"{w * 100:.1f}",
                    f"{h.roc_long:.1f}%",
                    f"{h.roc_short:.1f}%",
                    f"{h.dist_ma:.1f}%",
                    f"{h.est_value_twd:,.0f}",
                    ("⚠ 跌破均線" if h.dist_ma < 0 else h.alert),
                ),
                row_tag(h.alert, h.dist_ma),
                w / w_max if w_max else 0.0,
            )
        )
    return rows


def next_rows(result: MonitorResult, w_max: float = 0.10) -> List[tuple]:
    rows = []
    for r in result.next_month_rows:
        rows.append(
            (
                r.ticker,
                (
                    f"{r.est_weight * 100:.1f}",
                    f"{r.roc_long:.1f}%",
                    f"{r.roc_short:.1f}%",
                    f"{r.dist_ma:.1f}%",
                    f"{r.est_amount_twd:,.0f}",
                    r.status,
                ),
                "new" if "新標的" in r.status else row_tag(r.alert, r.dist_ma),
                r.est_weight / w_max if w_max else 0.0,
            )
        )
    return rows


def other_rows(result: MonitorResult) -> List[tuple]:
    return [
        (
            r.ticker,
            ("", f"{r.roc_long:.1f}%", f"{r.roc_short:.1f}%", f"{r.dist_ma:.1f}%", "", r.status),
            row_tag(r.alert, r.dist_ma),
            None,
        )
        for r in result.other_rows
    ]


VALUE_COLUMNS = ("權重%", "動能", "20日", "距200MA", "金額(TWD)", "狀態")


def sort_key(value: str):
    """Numeric-aware key for Treeview column sorting."""
    s = value.replace(",", "").replace("%", "").strip()
    try:
        return (0, float(s))
    except ValueError:
        return (1, value)


def _clean(text: str) -> str:
    """Drop leading emoji/symbols and any trailing parenthesised note."""
    text = re.sub(r"^[^\w\u4e00-\u9fff]+", "", text or "")
    return re.sub(r"\s*[(（].*$", "", text).strip() or "—"


def kpi_cards(result: MonitorResult, start_capital: float) -> List[dict]:
    """Dashboard cards: dicts of label / value / sub / tone."""
    pnl = result.final_assets_twd - start_capital
    pct = pnl / start_capital * 100 if start_capital else 0.0
    sign_tone = "up" if pnl > 0 else "down" if pnl < 0 else "text"
    theme_text, theme_level = theme_badge(result)
    lock_text, lock_level = lock_badge(result)
    stamp = (result.book_locked_at or "").replace("T", " ")[5:16]
    status = result.book_lock_status
    regime_text, regime_level = regime_badge(result)
    regime_tone = {OK: "ok", WARN: "warn", BAD: "danger"}.get(regime_level, "text")
    lock_tone = {OK: "ok", WARN: "warn"}.get(lock_level, "muted")
    theme_tone = {OK: "ok", WARN: "warn", BAD: "danger"}[theme_level]
    return [
        dict(label="預估總資產 TWD", value=f"{result.final_assets_twd:,.0f}",
             sub=f"月初 {start_capital:,.0f}", tone="text"),
        dict(label="本月損益", value=f"{pct:+.2f}%", sub=f"{pnl:+,.0f} TWD", tone=sign_tone),
        dict(label="曝險 / 現金", value=f"{result.effective_exposure * 100:.1f}%",
             sub=f"現金 {result.cash_drag_pct:.1f}%", tone="text"),
        dict(label="大盤狀態", value=_clean(result.market_mode),
             sub=(f"下月 {result.rdyn_blend_label.replace('%', '').replace(' / ', '｜')}" if result.rdyn_blend_label else "—"),
             tone=regime_tone),
        dict(label="題材集中度", value=f"{result.theme_ai_hw_weight * 100:.0f}%",
             sub="AI／半導體曝險", tone=theme_tone),
        dict(label="月度鎖定", value=result.rebalance_execution_date.strftime("%Y-%m"),
             sub=("已鎖定 " + stamp) if status else "未啟用", tone=lock_tone),
    ]
