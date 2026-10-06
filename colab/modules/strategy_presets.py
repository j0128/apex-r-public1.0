"""Apex strategy presets — Apex-R (RDyn-W) vs Apex-M (R0 pure momentum)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from apex_core import ApexConfig

# Apex-R line (regime blend product)
APP_VERSION = "4.0.0"
# Apex-M line (R0 pure momentum — separate product name to avoid confusion)
APEX_M_VERSION = "1.0.0"

STRATEGY_RDYN_W = "apex_rdyn_w"
STRATEGY_M = "apex_m"  # R0 pure momentum (product: Apex-M)
STRATEGY_CLASSIC = STRATEGY_M  # backward-compatible alias constant
STRATEGY_OPTIMIZED = "apex_opt"
STRATEGY_CUSTOM = "apex_custom"
STRATEGY_TW_M = "apex_tw_m"  # Taiwan R0
STRATEGY_TW_RDYN = "apex_tw_rdyn"  # Taiwan RDyn-W

DEFAULT_STRATEGY = STRATEGY_RDYN_W  # Apex-R launcher default; Apex-M uses its own config
APEX_TW_VERSION = "0.1.0"


@dataclass(frozen=True)
class StrategyPreset:
    id: str
    label: str
    summary: str
    top_n_limit: int
    momentum_days: int
    ma_days: int = 200
    buffer_zone: float = 0.97
    max_weight_cap: float = 0.10
    volatility_days: int = 20
    universe_size: int = 65
    universe_mode: str = "dollar_volume"
    universe_momentum_days: int = 504
    transaction_cost: float = 0.002
    breadth_threshold: float = 0.50
    show_market_mode: bool = True
    product: str = "Apex-R"  # window / report brand


PRESETS: Dict[str, StrategyPreset] = {
    STRATEGY_RDYN_W: StrategyPreset(
        id=STRATEGY_RDYN_W,
        label="Apex-R 4.0 RDyn-W",
        summary="Regime 動態 R0/R3 混合（實驗變體，非學術基準）",
        top_n_limit=10,
        momentum_days=120,
        universe_size=60,
        product="Apex-R",
    ),
    STRATEGY_M: StrategyPreset(
        id=STRATEGY_M,
        label="Apex-M｜R0 純動能",
        summary="固定交叉動能，無 regime 混合（學術基準／統計零模型）",
        top_n_limit=12,
        momentum_days=120,
        universe_size=65,
        product="Apex-M",
    ),
    STRATEGY_OPTIMIZED: StrategyPreset(
        id=STRATEGY_OPTIMIZED,
        label="Apex 2.0 優化",
        summary="200日動能 / Top8 / SP500 宇宙60（回測推薦）",
        top_n_limit=8,
        momentum_days=200,
        universe_size=60,
        product="Apex-R",
    ),
    STRATEGY_CUSTOM: StrategyPreset(
        id=STRATEGY_CUSTOM,
        label="自訂參數",
        summary="手動調整宇宙數 / 動能日 / Top N",
        top_n_limit=12,
        momentum_days=120,
        universe_size=60,
        product="Apex-R",
    ),
    STRATEGY_TW_M: StrategyPreset(
        id=STRATEGY_TW_M,
        label="Apex-TW｜R0 純動能",
        summary="台股宇宙 + 0050 基準；R0 無 regime 混合（實驗）",
        top_n_limit=12,
        momentum_days=120,
        universe_size=60,
        product="Apex-TW",
    ),
    STRATEGY_TW_RDYN: StrategyPreset(
        id=STRATEGY_TW_RDYN,
        label="Apex-TW RDyn-W",
        summary="台股宇宙 + 0050 regime 動態 R0/R3 混合（實驗）",
        top_n_limit=10,
        momentum_days=120,
        universe_size=60,
        product="Apex-TW",
    ),
}


def normalize_strategy_id(raw: str | None) -> str:
    key = (raw or DEFAULT_STRATEGY).strip().lower()
    if key in PRESETS:
        return key
    aliases = {
        "rdyn_w": STRATEGY_RDYN_W,
        "rdyn-w": STRATEGY_RDYN_W,
        "rdynw": STRATEGY_RDYN_W,
        "4.0": STRATEGY_RDYN_W,
        "v4": STRATEGY_RDYN_W,
        "3.0": STRATEGY_RDYN_W,
        "v3": STRATEGY_RDYN_W,
        # R0 / Apex-M
        "apex_m": STRATEGY_M,
        "apex-m": STRATEGY_M,
        "m": STRATEGY_M,
        "r0": STRATEGY_M,
        "classic": STRATEGY_M,
        "original": STRATEGY_M,
        "v1": STRATEGY_M,
        "apex_r": STRATEGY_M,  # legacy id → Apex-M
        # other
        "optimized": STRATEGY_OPTIMIZED,
        "apex2": STRATEGY_OPTIMIZED,
        "2.0": STRATEGY_OPTIMIZED,
        "opt": STRATEGY_OPTIMIZED,
        "custom": STRATEGY_CUSTOM,
        # Taiwan experimental
        "apex_tw_m": STRATEGY_TW_M,
        "apex-tw-m": STRATEGY_TW_M,
        "tw_m": STRATEGY_TW_M,
        "tw-m": STRATEGY_TW_M,
        "apex_tw_rdyn": STRATEGY_TW_RDYN,
        "apex-tw-rdyn": STRATEGY_TW_RDYN,
        "tw_rdyn": STRATEGY_TW_RDYN,
        "tw-rdyn": STRATEGY_TW_RDYN,
        "apex_tw": STRATEGY_TW_RDYN,
        "apex-tw": STRATEGY_TW_RDYN,
    }
    return aliases.get(key, DEFAULT_STRATEGY)


def get_preset(strategy_id: str) -> StrategyPreset:
    return PRESETS[normalize_strategy_id(strategy_id)]


def is_rdyn_w_strategy(strategy_id: str) -> bool:
    sid = normalize_strategy_id(strategy_id)
    return sid in (STRATEGY_RDYN_W, STRATEGY_TW_RDYN)


def is_apex_m_strategy(strategy_id: str) -> bool:
    sid = normalize_strategy_id(strategy_id)
    return sid in (STRATEGY_M, STRATEGY_TW_M)


def is_tw_strategy(strategy_id: str) -> bool:
    return normalize_strategy_id(strategy_id) in (STRATEGY_TW_M, STRATEGY_TW_RDYN)


def product_name(strategy_id: str) -> str:
    return get_preset(strategy_id).product


def product_version(strategy_id: str) -> str:
    if is_tw_strategy(strategy_id):
        return APEX_TW_VERSION
    if is_apex_m_strategy(strategy_id):
        return APEX_M_VERSION
    return APP_VERSION


def preset_choices() -> List[Tuple[str, str]]:
    """(id, display label) for UI combobox — Apex-M first for clarity when browsing."""
    order = [
        STRATEGY_M,
        STRATEGY_RDYN_W,
        STRATEGY_TW_M,
        STRATEGY_TW_RDYN,
        STRATEGY_OPTIMIZED,
        STRATEGY_CUSTOM,
    ]
    return [(sid, f"{PRESETS[sid].label} — {PRESETS[sid].summary}") for sid in order]


def apply_preset(cfg: ApexConfig, strategy_id: str) -> ApexConfig:
    """Return a copy of cfg with strategy parameters applied."""
    p = get_preset(strategy_id)
    market = cfg.market
    if is_tw_strategy(p.id):
        market = "tw"
    elif p.id in (STRATEGY_M, STRATEGY_RDYN_W, STRATEGY_OPTIMIZED) and market == "tw":
        # Switching to classic US presets keeps market unless user already set us
        market = "us"

    if p.id == STRATEGY_CUSTOM:
        return ApexConfig(
            query_date=cfg.query_date,
            current_month_capital_twd=cfg.current_month_capital_twd,
            next_month_injection_twd=cfg.next_month_injection_twd,
            user_tickers=cfg.user_tickers,
            tw_tickers=cfg.tw_tickers,
            strategy_id=p.id,
            universe_size=cfg.universe_size,
            universe_mode=cfg.universe_mode,
            universe_momentum_days=cfg.universe_momentum_days,
            universe_last_updated=cfg.universe_last_updated,
            transaction_cost=cfg.transaction_cost,
            max_weight_cap=cfg.max_weight_cap,
            top_n_limit=cfg.top_n_limit,
            buffer_zone=cfg.buffer_zone,
            volatility_days=cfg.volatility_days,
            momentum_days=cfg.momentum_days,
            ma_days=cfg.ma_days,
            breadth_threshold=cfg.breadth_threshold,
            show_market_mode=cfg.show_market_mode,
            market=market,
            benchmark=cfg.benchmark,
        )
    return ApexConfig(
        query_date=cfg.query_date,
        current_month_capital_twd=cfg.current_month_capital_twd,
        next_month_injection_twd=cfg.next_month_injection_twd,
        user_tickers=cfg.user_tickers,
        tw_tickers=cfg.tw_tickers,
        strategy_id=p.id,
        universe_size=p.universe_size,
        universe_mode=p.universe_mode,
        universe_momentum_days=p.universe_momentum_days,
        universe_last_updated=cfg.universe_last_updated,
        transaction_cost=p.transaction_cost,
        max_weight_cap=p.max_weight_cap,
        top_n_limit=p.top_n_limit,
        buffer_zone=p.buffer_zone,
        volatility_days=p.volatility_days,
        momentum_days=p.momentum_days,
        ma_days=p.ma_days,
        breadth_threshold=p.breadth_threshold,
        show_market_mode=p.show_market_mode,
        market=market,
        benchmark=cfg.benchmark or ("0050.TW" if market == "tw" else "SPY"),
    )


def report_header(strategy_id: str) -> str:
    p = get_preset(strategy_id)
    return report_header_cfg(
        ApexConfig(
            strategy_id=p.id,
            momentum_days=p.momentum_days,
            top_n_limit=p.top_n_limit,
            universe_size=p.universe_size,
        )
    )


def report_header_cfg(cfg: ApexConfig) -> str:
    p = get_preset(cfg.strategy_id)
    ver = product_version(cfg.strategy_id)
    brand = p.product
    return (
        f"{brand} {ver} | {p.label} "
        f"(宇宙{cfg.universe_size} / {cfg.momentum_days}d / Top{cfg.top_n_limit})"
    )
