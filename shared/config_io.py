"""Load / save config.yaml for Apex-R / Apex-TW."""

from __future__ import annotations

from pathlib import Path

import yaml

from apex_core import ApexConfig
from markets import normalize_market_id
from strategy_presets import normalize_strategy_id
from universe_builder import is_tw_ticker, parse_ticker_csv


def _normalize_tickers(raw) -> str:
    if isinstance(raw, list):
        return ", ".join(str(t) for t in raw)
    return str(raw or "").replace("\n", " ").strip()


def _split_legacy_tickers(tickers: str) -> tuple[str, str]:
    """Move .TW symbols from user_tickers into tw_tickers for older configs."""
    all_t = parse_ticker_csv(tickers)
    us = [t for t in all_t if not is_tw_ticker(t)]
    tw = [t for t in all_t if is_tw_ticker(t)]
    return ", ".join(us), ", ".join(tw)


def load_config(path: Path) -> ApexConfig:
    with path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    market = normalize_market_id(raw.get("market", "us"))
    tickers = _normalize_tickers(raw.get("user_tickers", ""))
    tw = _normalize_tickers(raw.get("tw_tickers", ""))

    # US configs: peel .TW sidecar out of user_tickers
    # TW configs: user_tickers is the full TW universe — do not split
    if market == "us" and not tw and tickers:
        tickers, tw = _split_legacy_tickers(tickers)

    return ApexConfig(
        query_date=str(raw.get("query_date", "2026-06-19")),
        current_month_capital_twd=float(raw.get("current_month_capital_twd", 1_000_000)),
        next_month_injection_twd=float(raw.get("next_month_injection_twd", 0)),
        user_tickers=tickers,
        tw_tickers=tw,
        strategy_id=normalize_strategy_id(raw.get("strategy_id")),
        universe_size=int(raw.get("universe_size", 60)),
        universe_mode=str(raw.get("universe_mode", "dollar_volume")),
        universe_momentum_days=int(raw.get("universe_momentum_days", 504)),
        universe_last_updated=str(raw.get("universe_last_updated", "") or ""),
        transaction_cost=float(raw.get("transaction_cost", 0.002)),
        max_weight_cap=float(raw.get("max_weight_cap", 0.10)),
        top_n_limit=int(raw.get("top_n_limit", 10)),
        buffer_zone=float(raw.get("buffer_zone", 0.97)),
        volatility_days=int(raw.get("volatility_days", 20)),
        momentum_days=int(raw.get("momentum_days", 120)),
        ma_days=int(raw.get("ma_days", 200)),
        breadth_threshold=float(raw.get("breadth_threshold", 0.50)),
        show_market_mode=bool(raw.get("show_market_mode", True)),
        market=market,
        benchmark=str(raw.get("benchmark", "") or "").strip().upper(),
    )


def save_config(path: Path, cfg: ApexConfig) -> None:
    us_lines = _format_ticker_block(cfg.user_tickers)
    tw_lines = _format_ticker_block(cfg.tw_tickers)
    market = normalize_market_id(cfg.market)
    bench = (cfg.benchmark or "").strip().upper()
    if not bench:
        bench = "0050.TW" if market == "tw" else "SPY"

    tw_section = ""
    if market == "us" and tw_lines:
        tw_section = f"""
# Taiwan stocks — add manually; not auto-screened (US market sidecar only)
tw_tickers: >
  {tw_lines}
"""

    universe_meta = ""
    if cfg.universe_last_updated:
        universe_meta = f'universe_last_updated: "{cfg.universe_last_updated}"\n'

    from strategy_presets import is_apex_m_strategy, product_name

    brand = product_name(cfg.strategy_id)
    if market == "tw":
        header = f"# Apex-TW experimental monitor — {brand}"
        universe_comment = (
            "# TW universe — master pool ranked by TWD dollar volume; "
            "benchmark ETF excluded from picks"
        )
        ticker_key = "user_tickers"
    elif is_apex_m_strategy(cfg.strategy_id):
        header = f"# {brand} (R0 純動能) local monitor configuration"
        universe_comment = (
            "# US universe — S&P 500 流動池 Top N；實盤約兩年才允許整池刷新（與回測 cycle 對齊）"
        )
        ticker_key = "user_tickers"
    else:
        header = f"# {brand} local monitor configuration"
        universe_comment = (
            "# US universe — S&P 500 流動池 Top N；實盤約兩年才允許整池刷新（與回測 cycle 對齊）"
        )
        ticker_key = "user_tickers"

    text = f"""{header}

market: {market}
benchmark: {bench}
strategy_id: {cfg.strategy_id}  # apex_m=Apex-M/R0 | apex_rdyn_w=Apex-R RDyn-W | apex_tw_m | apex_tw_rdyn

query_date: "{cfg.query_date}"
current_month_capital_twd: {int(cfg.current_month_capital_twd)}
next_month_injection_twd: {int(cfg.next_month_injection_twd)}

{universe_comment}
universe_mode: {cfg.universe_mode}
universe_size: {cfg.universe_size}
universe_momentum_days: {cfg.universe_momentum_days}
{universe_meta}{ticker_key}: >
  {us_lines}
{tw_section}
# Strategy parameters (auto-filled when switching preset in GUI)
transaction_cost: {cfg.transaction_cost}
max_weight_cap: {cfg.max_weight_cap}
top_n_limit: {cfg.top_n_limit}
buffer_zone: {cfg.buffer_zone}
volatility_days: {cfg.volatility_days}
momentum_days: {cfg.momentum_days}
ma_days: {cfg.ma_days}
breadth_threshold: {cfg.breadth_threshold}
show_market_mode: {str(cfg.show_market_mode).lower()}
"""
    path.write_text(text, encoding="utf-8")


def _format_ticker_block(tickers: str, chunk: int = 10) -> str:
    parts = [t.strip() for t in tickers.replace("\n", " ").split(",") if t.strip()]
    if not parts:
        return ""
    lines = [", ".join(parts[i : i + chunk]) for i in range(0, len(parts), chunk)]
    return ",\n  ".join(lines)


def default_config_path(base: Path) -> Path:
    return base / "config.yaml"
