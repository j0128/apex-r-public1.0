"""關注清單標的的當日漲跌 + 精簡總經一行。

只做一次 ``yf.download`` 取回所有標的近日收盤，計算單日 % 變化，
供簡報「持倉一行」與「±10% 大波動偵測」使用。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd
log = logging.getLogger("apex_r")

# 總經一行使用的指標（美股簡報精簡版）
MACRO_SYMBOLS = {
    "美元指數": "DX-Y.NYB",
    "美債10Y": "^TNX",
    "台幣匯率": "USDTWD=X",
}

# 台股委員會擴充儀表
TW_MACRO_SYMBOLS = {
    "0050": "0050.TW",
    "加權": "^TWII",
    "台幣": "USDTWD=X",
    "美元指數": "DX-Y.NYB",
    "美債10Y": "^TNX",
    "VIX": "^VIX",
    "那斯達克": "^IXIC",
}


@dataclass
class PriceChange:
    ticker: str
    last: float
    prev: float
    pct: float  # 單日漲跌百分比（+1.2 表示 +1.2%）


def _extract_close(raw: pd.DataFrame) -> pd.DataFrame:
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            return raw["Close"]
        return raw.xs(raw.columns.get_level_values(0)[0], axis=1, level=0)
    return raw[["Close"]] if "Close" in raw.columns else raw


def fetch_daily_changes(tickers: Iterable[str]) -> Dict[str, PriceChange]:
    """回傳 {ticker: PriceChange}，抓取失敗的標的會被略過。"""
    syms = list(dict.fromkeys([t.strip().upper() for t in tickers if t and t.strip()]))
    if not syms:
        return {}

    import yfinance as yf

    try:
        raw = yf.download(
            syms,
            period="7d",
            interval="1d",
            progress=False,
            auto_adjust=True,
            group_by="column",
        )
    except Exception as exc:
        log.warning("market snapshot download failed: %s", exc)
        return {}

    if raw is None or raw.empty:
        return {}

    close = _extract_close(raw)
    if isinstance(close, pd.Series):
        close = close.to_frame(name=syms[0])

    out: Dict[str, PriceChange] = {}
    for sym in syms:
        if sym not in close.columns:
            continue
        series = close[sym].dropna()
        if len(series) < 2:
            continue
        last = float(series.iloc[-1])
        prev = float(series.iloc[-2])
        if prev <= 0 or np.isnan(prev) or np.isnan(last):
            continue
        pct = (last / prev - 1.0) * 100.0
        out[sym] = PriceChange(ticker=sym, last=last, prev=prev, pct=pct)
    return out


def format_macro_line() -> str:
    """回傳精簡總經一行；抓取失敗時回傳空字串。"""
    changes = fetch_daily_changes(list(MACRO_SYMBOLS.values()))
    parts: List[str] = []
    for label, sym in MACRO_SYMBOLS.items():
        ch = changes.get(sym)
        if not ch:
            continue
        if sym == "^TNX":
            parts.append(f"{label} {ch.last:.2f}%")
        elif sym == "USDTWD=X":
            parts.append(f"{label} {ch.last:.2f}")
        else:
            parts.append(f"{label} {ch.last:.1f}")
    return " | ".join(parts)


def _dist_ma200(symbol: str) -> Optional[float]:
    """價格相對 200 日均線距離（%）；失敗回 None。"""
    import yfinance as yf

    try:
        raw = yf.download(
            symbol,
            period="1y",
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
    except Exception as exc:
        log.warning("200MA download failed for %s: %s", symbol, exc)
        return None
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        if "Close" in raw.columns.get_level_values(0):
            close = raw["Close"]
        else:
            close = raw.xs(raw.columns.get_level_values(0)[0], axis=1, level=0)
    elif "Close" in raw.columns:
        close = raw["Close"]
    else:
        close = raw.iloc[:, 0]
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    series = close.dropna()
    if len(series) < 200:
        return None
    last = float(series.iloc[-1])
    ma = float(series.iloc[-200:].mean())
    if ma <= 0:
        return None
    return (last / ma - 1.0) * 100.0


def format_macro_analysis(
    *,
    rdyn_regime: str = "",
    rdyn_blend_label: str = "",
    theme_r0_pct: float = 0.0,
    theme_rdyn_pct: float = 0.0,
) -> str:
    """台股委員會用：總經短分析（數字列 + 解讀 + 對三席意涵）。"""
    changes = fetch_daily_changes(list(TW_MACRO_SYMBOLS.values()))
    gauge: List[str] = []
    for label, sym in TW_MACRO_SYMBOLS.items():
        ch = changes.get(sym)
        if not ch:
            continue
        if sym == "^TNX":
            gauge.append(f"{label} {ch.last:.2f}% ({pct_str(ch.pct)})")
        elif sym == "USDTWD=X":
            gauge.append(f"{label} {ch.last:.2f} ({pct_str(ch.pct)})")
        elif sym in ("0050.TW", "^TWII", "^IXIC"):
            gauge.append(f"{label} {pct_str(ch.pct)}")
        else:
            gauge.append(f"{label} {ch.last:.1f} ({pct_str(ch.pct)})")

    dist_0050 = _dist_ma200("0050.TW")
    if dist_0050 is not None:
        gauge.append(f"0050 vs 200MA {dist_0050:+.0f}%")

    usd_twd = changes.get("USDTWD=X")
    vix = changes.get("^VIX")
    ixic = changes.get("^IXIC")

    global_bits: List[str] = []
    if ixic:
        global_bits.append(f"那斯達克 {pct_str(ixic.pct)}")
    if vix:
        global_bits.append(f"VIX {vix.last:.1f}")
    tnx = changes.get("^TNX")
    if tnx:
        global_bits.append(f"美債10Y {tnx.last:.2f}%")

    fx_note = "匯率資料暫缺"
    if usd_twd:
        if usd_twd.pct >= 0.3:
            fx_note = "台幣偏弱（美元升值）——出口／電子報價環境相對有利，外資動向需另觀"
        elif usd_twd.pct <= -0.3:
            fx_note = "台幣偏強——進口成本壓力較輕，短線外資匯兌損益可能波動"
        else:
            fx_note = "台幣匯率大致持穩"

    board_note = "0050 相對均線資料暫缺"
    if dist_0050 is not None:
        if dist_0050 >= 5:
            board_note = f"0050 站上 200MA 約 {dist_0050:+.0f}%——中期趨勢偏多，動能袖可維持"
        elif dist_0050 >= 0:
            board_note = f"0050 略高於 200MA（{dist_0050:+.0f}%）——偏多但緩衝有限"
        else:
            board_note = f"0050 低於 200MA（{dist_0050:+.0f}%）——趨勢轉弱，宜提高錨定袖比重"

    regime = (rdyn_regime or "").strip() or "n/a"
    blend = (rdyn_blend_label or "").strip() or "（無）"
    theme_hi = max(theme_r0_pct, theme_rdyn_pct)

    sleeve_anchor = "維持核心袖"
    sleeve_mom = "動能袖可依 R0 名單執行"
    if dist_0050 is not None and dist_0050 < 0:
        sleeve_anchor = "建議提高 0050 袖比重"
        sleeve_mom = "動能袖宜保守，勿因單日反彈加碼"
    elif "defensive" in regime.lower() or "cash" in regime.lower():
        sleeve_anchor = "RDyn 偏防禦——提高 0050 袖"
        sleeve_mom = "動能袖降曝險／觀察為主"
    elif theme_hi >= 0.40:
        sleeve_mom = "半導／AI 主題偏高——執行名單但禁止同主題再加碼"

    lines = [
        "〔全球〕" + ("｜".join(global_bits) if global_bits else "隔夜指標暫缺"),
        f"〔匯率／資金〕{fx_note}",
        f"〔台股盤態〕{board_note}",
        f"〔RDyn 盤態〕regime={regime}｜{blend}",
        f"〔主題〕R0 {theme_r0_pct * 100:.0f}%｜RDyn {theme_rdyn_pct * 100:.0f}%",
        "",
        "【總經儀表】",
        " | ".join(gauge) if gauge else "（儀表抓取失敗）",
        "",
        "【對三席的意涵】",
        f"· 0050錨：{sleeve_anchor}",
        f"· Apex-TW R0：{sleeve_mom}",
        f"· Apex-TW RDyn：壓力測試／集中度對照；blend={blend}",
    ]
    return "\n".join(lines)


def pct_str(pct: Optional[float]) -> str:
    if pct is None:
        return "—"
    sign = "+" if pct >= 0 else ""
    return f"{sign}{pct:.1f}%"
