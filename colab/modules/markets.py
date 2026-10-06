"""Market identity for Apex — US vs Taiwan adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Set


@dataclass(frozen=True)
class MarketContext:
    market_id: str
    label: str
    benchmark: str
    fx_symbol: Optional[str]  # None = native currency (prices already in reporting FX)
    fx_fallback: float
    currency_label: str
    timezone: str
    # Theme concentration set (AI / semiconductor hardware)
    theme_ai_hw: frozenset
    session_morning_label: str
    session_night_label: str
    query_date_label: str


THEME_AI_HW_US: Set[str] = {
    "NVDA", "AMD", "INTC", "MU", "MRVL", "AVGO", "QCOM", "TXN", "ARM", "TSM",
    "AMAT", "LRCX", "ASML", "KLAC", "ON", "ADI", "MPWR", "MCHP", "NXPI",
    "DELL", "SMCI", "IBM", "SNDK", "STX", "WDC",
}

# Taiwan semiconductor / AI hardware supply chain (Yahoo .TW / .TWO)
THEME_AI_HW_TW: Set[str] = {
    "2330.TW", "2454.TW", "2303.TW", "3711.TW", "2379.TW", "2308.TW",
    "2382.TW", "3034.TW", "6669.TW", "3661.TW", "3443.TW", "3037.TW",
    "2327.TW", "2345.TW", "3008.TW", "6488.TW", "8299.TWO", "5269.TW",
    "8046.TW", "3105.TWO", "4966.TW", "6531.TW", "6770.TW", "2408.TW",
    "2344.TW", "2449.TW", "3189.TW", "3653.TW", "3017.TW", "2301.TW",
    "2357.TW", "2395.TW", "3231.TW", "2313.TW", "2409.TW", "3481.TW",
    "3532.TW", "6182.TWO", "6415.TW", "8069.TWO",
}

MARKETS: Dict[str, MarketContext] = {
    "us": MarketContext(
        market_id="us",
        label="美股",
        benchmark="SPY",
        fx_symbol="USDTWD=X",
        fx_fallback=31.50,
        currency_label="TWD",
        timezone="Asia/Taipei",
        theme_ai_hw=frozenset(THEME_AI_HW_US),
        session_morning_label="🌅 【早盤動態檢視】",
        session_night_label="🌃 【夜盤常規檢視】",
        query_date_label="查詢日（美股）",
    ),
    "tw": MarketContext(
        market_id="tw",
        label="台股",
        benchmark="0050.TW",
        fx_symbol=None,
        fx_fallback=1.0,
        currency_label="TWD",
        timezone="Asia/Taipei",
        theme_ai_hw=frozenset(THEME_AI_HW_TW),
        session_morning_label="🌅 【台股盤中／收盤後檢視】",
        session_night_label="🌃 【台股收盤後檢視】",
        query_date_label="查詢日（台股）",
    ),
}


def normalize_market_id(raw: str | None) -> str:
    key = (raw or "us").strip().lower()
    aliases = {
        "us": "us",
        "usa": "us",
        "spy": "us",
        "美股": "us",
        "tw": "tw",
        "taiwan": "tw",
        "tpe": "tw",
        "twse": "tw",
        "台股": "tw",
        "apex_tw": "tw",
        "apex-tw": "tw",
    }
    return aliases.get(key, "us" if key not in MARKETS else key)


def get_market(
    market_id: str | None = "us",
    *,
    benchmark: str | None = None,
) -> MarketContext:
    mid = normalize_market_id(market_id)
    base = MARKETS[mid]
    b = (benchmark or "").strip().upper()
    if b and b != base.benchmark:
        return MarketContext(
            market_id=base.market_id,
            label=base.label,
            benchmark=b,
            fx_symbol=base.fx_symbol,
            fx_fallback=base.fx_fallback,
            currency_label=base.currency_label,
            timezone=base.timezone,
            theme_ai_hw=base.theme_ai_hw,
            session_morning_label=base.session_morning_label,
            session_night_label=base.session_night_label,
            query_date_label=base.query_date_label,
        )
    return base


def is_tw_market(market_id: str | None) -> bool:
    return normalize_market_id(market_id) == "tw"
