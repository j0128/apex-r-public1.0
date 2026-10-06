"""
Apex-R core engine: shared logic for Colab and local monitor.

Changes vs Apex 4.5:
  - Risk-adjusted momentum: ROC_120 / vol_20
  - Cap-then-normalize weights to BUFFER_ZONE (97%)
  - No intraday stop-loss
  - RDyn-W (apex_rdyn_w): regime-driven R0/R3 weight blend
  - Classic mode: market regime display-only (no allocation impact)
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import pytz

warnings.filterwarnings("ignore")

log = logging.getLogger("apex_r")

TW_TZ = pytz.timezone("Asia/Taipei")

ROC_SHORT_DAYS = 20

# Legacy alias — prefer markets.get_market(cfg.market).theme_ai_hw
from markets import THEME_AI_HW_US as THEME_AI_HW  # noqa: E402

THEME_WARN_SOFT = 0.35
THEME_WARN_HARD = 0.50

# RDyn-W: R3 weight by regime (matches backtest_r0_r3_dynamic.py)
REGIME_W_R3: Dict[str, float] = {
    "offensive_full": 0.25,   # R0 75% / R3 25%
    "offensive_half": 0.50,   # R0 50% / R3 50%
    "bunker": 0.75,           # R0 25% / R3 75% (stay in stocks, no bunker assets)
}


@dataclass
class ApexConfig:
    query_date: str = "2026-06-19"
    current_month_capital_twd: float = 1_000_000.0
    next_month_injection_twd: float = 0.0
    user_tickers: str = ""
    strategy_id: str = "apex_rdyn_w"
    transaction_cost: float = 0.002
    max_weight_cap: float = 0.10
    top_n_limit: int = 10
    buffer_zone: float = 0.97
    volatility_days: int = 20
    momentum_days: int = 120
    ma_days: int = 200
    breadth_threshold: float = 0.50
    show_market_mode: bool = True  # display only, no allocation impact
    tw_tickers: str = ""  # manual Taiwan names; appended to US universe (market=us only)
    universe_size: int = 60
    universe_mode: str = "dollar_volume"  # dollar_volume | momentum
    universe_momentum_days: int = 504
    universe_last_updated: str = ""
    market: str = "us"  # us | tw
    benchmark: str = ""  # empty → market default (SPY / 0050.TW)

    def ticker_list(self) -> List[str]:
        us = [t.strip().upper() for t in self.user_tickers.split(",") if t.strip()]
        tw = [t.strip().upper() for t in self.tw_tickers.split(",") if t.strip()]
        # TW market: user_tickers is the full TW universe; ignore sidecar mix-in
        if (self.market or "us").strip().lower() in ("tw", "taiwan", "twse", "台股"):
            return list(dict.fromkeys(us if us else tw))
        return list(dict.fromkeys(us + tw))

    def market_ctx(self):
        from markets import get_market

        return get_market(self.market, benchmark=self.benchmark or None)


@dataclass
class HoldingRow:
    ticker: str
    roc_long: float
    roc_short: float
    dist_ma: float
    est_value_twd: float
    action: str
    alert: str


@dataclass
class RadarRow:
    ticker: str
    roc_long: float
    roc_short: float
    dist_ma: float
    est_weight: float
    est_amount_twd: float
    status: str
    alert: str


@dataclass
class MonitorResult:
    run_time_tw: datetime
    query_date: pd.Timestamp
    fx_rate: float
    final_assets_twd: float
    market_mode: str
    rebalance_decision_date: pd.Timestamp
    rebalance_execution_date: pd.Timestamp
    locked_portfolio: List[str]
    locked_weights: Dict[str, float]
    holdings: List[HoldingRow]
    next_month_picks: List[str]
    next_month_weights: Dict[str, float]
    next_month_rows: List[RadarRow]
    other_rows: List[RadarRow]
    effective_exposure: float
    cash_drag_pct: float
    buffer_zone: float = 0.97
    next_month_injection_twd: float = 0.0
    rdyn_regime: str = ""
    rdyn_w_r3: float = 0.0
    rdyn_blend_label: str = ""
    # Factor-theme exposure (name diversification ≠ risk diversification)
    theme_ai_hw_weight: float = 0.0
    theme_ai_hw_warning: str = ""
    # Month-start lock: "" (no store) | "new" | "reused" | "relocked"
    book_lock_status: str = ""
    book_locked_at: str = ""
    book_lock_note: str = ""
    # Recent price history for charts (display only; never feeds the strategy)
    hist_close: Optional[pd.DataFrame] = None
    hist_open: Optional[pd.DataFrame] = None
    hist_ma: Optional[pd.DataFrame] = None


def finalize_weights(
    tickers: List[str],
    vol_row: pd.Series,
    target_sum: float,
    cap: float,
) -> Dict[str, float]:
    if not tickers or target_sum <= 0:
        return {}

    inv: Dict[str, float] = {}
    for t in tickers:
        v = vol_row.get(t, np.nan)
        if pd.notna(v) and v > 0:
            inv[t] = 1.0 / v
    if not inv:
        inv = {t: 1.0 for t in tickers}

    total = sum(inv.values())
    weights = {t: inv[t] / total * target_sum for t in inv}

    for _ in range(100):
        excess = 0.0
        room: Dict[str, float] = {}
        capped = False
        for t in list(weights):
            if weights[t] > cap + 1e-12:
                excess += weights[t] - cap
                weights[t] = cap
                capped = True
            else:
                room[t] = cap - weights[t]
        if excess <= 1e-12:
            break
        if not room:
            break
        room_total = sum(room.values())
        if room_total <= 1e-12:
            break
        for t, r in room.items():
            weights[t] += excess * (r / room_total)
        if not capped:
            break

    s = sum(weights.values())
    if 0 < s < target_sum - 1e-9:
        scale = target_sum / s
        weights = {t: min(w * scale, cap) for t, w in weights.items()}

    return weights


def momentum_score(ticker: str, mom: pd.Series, vol: pd.Series) -> float:
    m = mom.get(ticker, np.nan)
    if pd.isna(m):
        return -999.0
    v = vol.get(ticker, np.nan)
    if pd.notna(v) and v > 1e-8:
        return m / v
    return m


def compute_breadth(tickers: List[str], prices: pd.Series, ma: pd.Series) -> float:
    valid = [t for t in tickers if pd.notna(prices.get(t)) and pd.notna(ma.get(t))]
    if not valid:
        return 0.0
    return sum(1 for t in valid if prices[t] >= ma[t]) / len(valid)


def market_mode_label(spy_p: float, spy_ma: float, breadth: float, threshold: float) -> str:
    if pd.isna(spy_p) or pd.isna(spy_ma):
        return "⚪ 資料不足"
    if spy_p >= spy_ma and breadth >= threshold:
        return "🟢 晴空萬里 (100% 滿倉進攻)"
    if spy_p >= spy_ma:
        return "🟡 虛胖拉積盤 (僅 50% 曝險)"
    return "🔴 全天候避難所啟動"


def detect_regime_mode(spy_p: float, spy_ma: float, breadth: float, threshold: float) -> str:
    """Regime code for RDyn-W weight mapping."""
    if pd.isna(spy_p) or pd.isna(spy_ma):
        return "offensive_half"
    if spy_p >= spy_ma and breadth >= threshold:
        return "offensive_full"
    if spy_p >= spy_ma:
        return "offensive_half"
    return "bunker"


def format_rdyn_blend_label(w_r3: float) -> str:
    w0 = int(round((1.0 - w_r3) * 100))
    w3 = int(round(w_r3 * 100))
    return f"R0 {w0}% / R3 {w3}%"


def find_month_rebalance_dates(df_close: pd.DataFrame) -> Tuple[pd.Timestamp, pd.Timestamp]:
    for i in range(len(df_close) - 1, 0, -1):
        if df_close.index[i].month != df_close.index[i - 1].month:
            return df_close.index[i - 1], df_close.index[i]
    if len(df_close) > 1:
        return df_close.index[0], df_close.index[1]
    return df_close.index[0], df_close.index[0]


def select_top_n(
    universe: List[str],
    prices: pd.Series,
    ma: pd.Series,
    mom: pd.Series,
    vol: pd.Series,
    top_n: int,
    entry_20d_pos_only: bool = False,
    roc_short: Optional[pd.Series] = None,
) -> List[str]:
    eligible: List[str] = []
    for t in universe:
        p, m = prices.get(t, np.nan), ma.get(t, np.nan)
        if pd.isna(p) or pd.isna(m) or p < m:
            continue
        if entry_20d_pos_only:
            rs = roc_short.get(t, np.nan) if roc_short is not None else np.nan
            if pd.isna(rs) or rs < 0:
                continue
        eligible.append(t)
    ranked = sorted(eligible, key=lambda t: momentum_score(t, mom, vol), reverse=True)
    return ranked[:top_n]


def blend_strategy_weights(
    w0: Dict[str, float],
    w3: Dict[str, float],
    w_r3: float,
) -> Dict[str, float]:
    blended: Dict[str, float] = {}
    for t in set(w0) | set(w3):
        blended[t] = (1.0 - w_r3) * w0.get(t, 0.0) + w_r3 * w3.get(t, 0.0)
    return blended


def build_rdyn_weights(
    cfg: ApexConfig,
    universe: List[str],
    prices: pd.Series,
    ma: pd.Series,
    mom: pd.Series,
    vol: pd.Series,
    roc_short: pd.Series,
    *,
    benchmark: Optional[str] = None,
) -> Tuple[Dict[str, float], str, float]:
    """Regime-driven R0/R3 portfolio weights (RDyn-W)."""
    bench = (benchmark or cfg.market_ctx().benchmark).strip().upper()
    offensive = [t for t in universe if t != bench]
    breadth = compute_breadth(offensive, prices, ma)
    spy_p = prices.get(bench, np.nan)
    spy_ma = ma.get(bench, np.nan)
    mode = detect_regime_mode(spy_p, spy_ma, breadth, cfg.breadth_threshold)
    w_r3 = REGIME_W_R3[mode]

    r0_picks = select_top_n(
        offensive, prices, ma, mom, vol, cfg.top_n_limit,
        entry_20d_pos_only=False, roc_short=roc_short,
    )
    r3_picks = select_top_n(
        offensive, prices, ma, mom, vol, cfg.top_n_limit,
        entry_20d_pos_only=True, roc_short=roc_short,
    )
    w0 = finalize_weights(r0_picks, vol, cfg.buffer_zone, cfg.max_weight_cap) if r0_picks else {}
    w3 = finalize_weights(r3_picks, vol, cfg.buffer_zone, cfg.max_weight_cap) if r3_picks else {}

    if not w0 and not w3:
        return {}, mode, w_r3
    if not w0:
        return w3, mode, w_r3
    if not w3:
        return w0, mode, w_r3
    return blend_strategy_weights(w0, w3, w_r3), mode, w_r3


def is_rdyn_w_cfg(cfg: ApexConfig) -> bool:
    try:
        from strategy_presets import is_rdyn_w_strategy

        return is_rdyn_w_strategy(cfg.strategy_id)
    except ImportError:
        return (cfg.strategy_id or "").strip().lower() in ("apex_rdyn_w", "rdyn_w", "rdyn-w")


DOWNLOAD_CHUNK = 40
HISTORY_DAYS = 200  # trading days kept for charts
HISTORY_LOOKBACK_DAYS = 640  # calendar days: 200 shown + 200 for the 200MA + buffer
FX_FALLBACK = 31.50
_RATE_LIMIT_MARKERS = ("Too Many Requests", "Rate limited", "YFRateLimitError")
_YF_SESSION = None


def _yf_session():
    """Reuse a browser-like session — plain yfinance hits Yahoo rate limits hard."""
    global _YF_SESSION
    if _YF_SESSION is not None:
        return _YF_SESSION
    try:
        from curl_cffi import requests as cfi_requests

        _YF_SESSION = cfi_requests.Session(impersonate="chrome")
    except Exception as exc:
        log.info("curl_cffi session unavailable, using default yfinance session: %s", exc)
        _YF_SESSION = False  # mark unavailable
    return _YF_SESSION if _YF_SESSION is not False else None


def _price_cache_path(symbols: List[str], query_date: str, lookback_days: int) -> Path:
    import hashlib
    import tempfile

    key = f"{query_date}|{lookback_days}|{','.join(sorted(symbols))}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    root = Path(tempfile.gettempdir()) / "apex_r_price_cache"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{digest}.pkl"


def _is_rate_limited(exc: BaseException | str | None) -> bool:
    text = str(exc or "")
    return any(m.lower() in text.lower() for m in _RATE_LIMIT_MARKERS)


def _raw_to_adj_open(raw: pd.DataFrame, symbols: List[str]) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if raw is None or raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        if "Adj Close" in raw.columns.get_level_values(0):
            close_raw = raw["Close"].ffill().dropna(how="all")
            adj = raw["Adj Close"].ffill().dropna(how="all")
            ratio = adj / close_raw.replace(0, np.nan)
            # 有些標的（如 0050.TW）某日開盤價會回傳 0，視為缺值以免污染市值計算
            open_raw = raw["Open"].replace(0, np.nan)
            opn = (open_raw * ratio).ffill().dropna(how="all")
        else:
            adj = raw["Close"].ffill().dropna(how="all")
            opn = raw["Open"].replace(0, np.nan).ffill().dropna(how="all")
    else:
        sym = symbols[0] if symbols else "Close"
        adj = raw[["Close"]].copy()
        adj.columns = [sym]
        opn = raw[["Open"]].replace(0, np.nan).ffill()
        opn.columns = [sym]

    return adj, opn


def _yf_download_raw(symbols: List[str], start: str, end: str) -> Tuple[pd.DataFrame, Optional[str]]:
    """Return (raw_df, error_message). Empty df on failure."""
    import yfinance as yf

    if not symbols:
        return pd.DataFrame(), None
    kwargs = dict(
        start=start,
        end=end,
        progress=False,
        auto_adjust=False,
        threads=True,
        group_by="column",
    )
    session = _yf_session()
    if session is not None:
        kwargs["session"] = session
    try:
        raw = yf.download(symbols, **kwargs)
    except Exception as exc:
        return pd.DataFrame(), str(exc)

    if raw is None or raw.empty:
        return pd.DataFrame(), "empty_response"
    return raw, None


def _download_chunk_with_retry(
    symbols: List[str],
    start: str,
    end: str,
    *,
    retries: int = 2,
) -> pd.DataFrame:
    import time

    for attempt in range(retries):
        raw, err = _yf_download_raw(symbols, start, end)
        if not raw.empty:
            return raw
        sleep_s = 5 * (attempt + 1) if _is_rate_limited(err) or err == "empty_response" else 1.5
        time.sleep(sleep_s)
    return pd.DataFrame()


def download_market_data(
    tickers: List[str],
    query_date: str,
    lookback_days: int = 400,
    *,
    use_cache: bool = True,
    benchmark: str = "SPY",
    fx_symbol: Optional[str] = "USDTWD=X",
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    import time

    extras = [benchmark.strip().upper()] if benchmark else []
    if fx_symbol:
        extras.append(fx_symbol.strip().upper())
    all_syms = list(
        dict.fromkeys([*(t.strip().upper() for t in tickers if t.strip()), *extras])
    )
    q_end = pd.to_datetime(query_date)
    # yfinance end is exclusive; +1 day keeps query_date bars when available
    fetch_end = (q_end + timedelta(days=1)).strftime("%Y-%m-%d")
    fetch_start = (q_end - timedelta(days=lookback_days)).strftime("%Y-%m-%d")

    cache_path = _price_cache_path(all_syms, str(q_end.date()), lookback_days)
    if use_cache and cache_path.exists():
        try:
            cached = pd.read_pickle(cache_path)
            adj_c, opn_c = cached.get("adj"), cached.get("opn")
            if isinstance(adj_c, pd.DataFrame) and not adj_c.empty:
                return adj_c, opn_c
        except Exception as exc:
            log.warning("price cache read failed (%s): %s", cache_path.name, exc)

    # Fast path: one batched download with browser session
    raw, err = _yf_download_raw(all_syms, fetch_start, fetch_end)
    if raw.empty:
        frames: List[pd.DataFrame] = []
        for i in range(0, len(all_syms), DOWNLOAD_CHUNK):
            chunk = all_syms[i : i + DOWNLOAD_CHUNK]
            part = _download_chunk_with_retry(chunk, fetch_start, fetch_end)
            if not part.empty:
                frames.append(part)
            if i + DOWNLOAD_CHUNK < len(all_syms):
                time.sleep(0.4)
        if frames:
            raw = pd.concat(frames, axis=1)
            raw = raw.loc[:, ~raw.columns.duplicated()]

    if raw.empty:
        raise RuntimeError(
            f"未能取得市場報價（Yahoo 限流或空回應）。基準日 {q_end.date()}，"
            f"標的 {len(all_syms)} 檔。請稍候再試；成功後會快取以加速重跑。"
            + (f" 細節: {err}" if err else "")
        )

    adj, opn = _raw_to_adj_open(raw, all_syms)
    if not adj.empty:
        adj = adj.loc[:q_end].dropna(how="all")
    if not opn.empty:
        opn = opn.reindex(adj.index).ffill().dropna(how="all")

    if adj.empty:
        raise RuntimeError(
            f"未能取得有效的市場報價（無收盤價）。基準日 {q_end.date()}。"
        )

    valid_cols = [c for c in adj.columns if adj[c].notna().any()]
    if len(valid_cols) < 5:
        raise RuntimeError(
            f"未能取得有效的市場報價（有效標的過少：{len(valid_cols)}）。"
            "請稍後再試。"
        )
    adj = adj[valid_cols]
    opn = opn.reindex(columns=[c for c in valid_cols if c in opn.columns])

    if use_cache:
        try:
            pd.to_pickle({"adj": adj, "opn": opn}, cache_path)
        except Exception as exc:
            log.warning("price cache write failed (%s): %s", cache_path.name, exc)

    return adj, opn


def fx_from_close(
    df_close: pd.DataFrame,
    fx_symbol: Optional[str] = "USDTWD=X",
) -> Optional[float]:
    if not fx_symbol:
        return None
    if df_close is None or df_close.empty or fx_symbol not in df_close.columns:
        return None
    series = df_close[fx_symbol].dropna()
    if series.empty:
        return None
    try:
        return float(series.iloc[-1])
    except (TypeError, ValueError):
        return None


def fetch_fx_rate(fx_symbol: str = "USDTWD=X", fallback: float = FX_FALLBACK) -> float:
    import time
    import yfinance as yf

    if not fx_symbol:
        return fallback
    kwargs = dict(period="5d", progress=False, threads=False)
    session = _yf_session()
    if session is not None:
        kwargs["session"] = session
    for attempt in range(3):
        try:
            fx = yf.download(fx_symbol, **kwargs)
            if fx is None or fx.empty:
                time.sleep(2 * (attempt + 1))
                continue
            if isinstance(fx.columns, pd.MultiIndex):
                return float(fx["Close"][fx_symbol].dropna().iloc[-1])
            return float(fx["Close"].dropna().iloc[-1])
        except Exception as exc:
            log.warning("FX fetch attempt %d failed for %s: %s", attempt + 1, fx_symbol, exc)
            time.sleep(2 * (attempt + 1))
    log.warning("FX rate unavailable for %s, using fallback %s", fx_symbol, fallback)
    return fallback


def run_monitor(
    cfg: ApexConfig,
    *,
    book_store=None,
    relock: bool = False,
) -> MonitorResult:
    """Run the monitor.

    book_store: optional ``locked_book.LockedBookStore``. When given, the
    month-start book (tickers + weights) is written once per month and reused
    unchanged for every query inside that month. ``relock=True`` deliberately
    overwrites the current month's lock (explicit user action only).
    """
    tickers = cfg.ticker_list()
    if not tickers:
        raise ValueError("USER_TICKERS 不可為空。")

    mkt = cfg.market_ctx()
    bench = mkt.benchmark
    theme_set = mkt.theme_ai_hw

    now_tw = datetime.now(TW_TZ)
    is_morning = now_tw.hour < 12

    lock_extra: List[str] = []
    if book_store is not None and not relock:
        lock_extra = book_store.candidate_tickers(cfg.strategy_id, cfg.market, cfg.query_date)
    dl_tickers = list(dict.fromkeys([*tickers, *lock_extra]))

    df_close, df_open = download_market_data(
        dl_tickers,
        cfg.query_date,
        lookback_days=HISTORY_LOOKBACK_DAYS,
        benchmark=bench,
        fx_symbol=mkt.fx_symbol,
    )
    if df_close.empty:
        raise RuntimeError("未能取得有效的市場報價。")

    if mkt.fx_symbol is None:
        fx = 1.0
    else:
        fx = fx_from_close(df_close, mkt.fx_symbol)
        if fx is None:
            fx = fetch_fx_rate(mkt.fx_symbol, mkt.fx_fallback)

    # Strategy math only needs universe + benchmark; keep FX extraction above
    needed = [t for t in dl_tickers if t in df_close.columns]
    n_universe_ok = sum(1 for t in tickers if t in needed)
    if bench in df_close.columns and bench not in needed:
        needed.append(bench)
    if n_universe_ok < max(5, min(10, len(tickers) // 2)):
        raise RuntimeError(
            f"未能取得有效的市場報價（宇宙標的僅下載到 {n_universe_ok}/{len(tickers)}）。"
            "請稍後再試。"
        )
    df_close = df_close[needed]
    df_open = df_open.reindex(columns=[c for c in needed if c in df_open.columns]).reindex(df_close.index)

    last_idx = df_close.index[-1]
    df_ma = df_close.rolling(cfg.ma_days).mean()
    df_vol = df_close.pct_change().rolling(cfg.volatility_days).std()
    df_mom = df_close.pct_change(cfg.momentum_days)
    df_roc_short = df_close.pct_change(ROC_SHORT_DAYS)

    rebalance_decision_date, rebalance_execution_date = find_month_rebalance_dates(df_close)

    # --- month-start locked book ---
    roc_at_reb = df_mom.loc[rebalance_decision_date]
    vol_at_reb = df_vol.loc[rebalance_decision_date]
    ma_at_reb = df_ma.loc[rebalance_decision_date]
    px_at_reb = df_close.loc[rebalance_decision_date]
    roc_short_at_reb = df_roc_short.loc[rebalance_decision_date]

    offensive_universe = [t for t in tickers if t != bench]
    use_rdyn = is_rdyn_w_cfg(cfg)
    rdyn_regime = ""
    rdyn_w_r3 = 0.0
    rdyn_blend_label = ""

    book_month = None
    snapshot = None
    lock_status = ""
    lock_note = ""
    if book_store is not None:
        from locked_book import month_key

        book_month = month_key(rebalance_execution_date)
        if not relock:
            snapshot = book_store.load(cfg.strategy_id, cfg.market, book_month)

    if snapshot is not None:
        # Frozen for the month: no recomputation, whatever today's data says.
        missing = [t for t in snapshot.weights if t not in df_close.columns]
        if missing:
            lock_note = f"鎖定標的無最新報價，已排除：{', '.join(missing)}"
            log.warning("locked book %s: no price data for %s", book_month, missing)
        locked_weights = {t: w for t, w in snapshot.weights.items() if t in df_close.columns}
        locked_portfolio = sorted(locked_weights, key=lambda t: locked_weights[t], reverse=True)
        lock_status = "reused"
        lock_locked_at = snapshot.locked_at
    else:
        if use_rdyn:
            locked_weights, rdyn_regime, rdyn_w_r3 = build_rdyn_weights(
                cfg,
                tickers,
                px_at_reb,
                ma_at_reb,
                roc_at_reb,
                vol_at_reb,
                roc_short_at_reb,
                benchmark=bench,
            )
            locked_portfolio = sorted(locked_weights.keys(), key=lambda t: locked_weights[t], reverse=True)
            rdyn_blend_label = format_rdyn_blend_label(rdyn_w_r3)
        else:
            locked_portfolio = select_top_n(
                offensive_universe,
                px_at_reb,
                ma_at_reb,
                roc_at_reb,
                vol_at_reb,
                cfg.top_n_limit,
            )
            locked_weights = finalize_weights(
                locked_portfolio,
                vol_at_reb,
                cfg.buffer_zone,
                cfg.max_weight_cap,
            )
        lock_locked_at = ""
        if book_store is not None:
            from locked_book import new_book

            book = new_book(
                strategy_id=cfg.strategy_id,
                market=cfg.market,
                decision_date=rebalance_decision_date,
                execution_date=rebalance_execution_date,
                weights=locked_weights,
                params={
                    "universe_size": cfg.universe_size,
                    "momentum_days": cfg.momentum_days,
                    "top_n_limit": cfg.top_n_limit,
                    "buffer_zone": cfg.buffer_zone,
                    "max_weight_cap": cfg.max_weight_cap,
                    "ma_days": cfg.ma_days,
                    "volatility_days": cfg.volatility_days,
                    "regime": rdyn_regime,
                    "w_r3": rdyn_w_r3,
                },
            )
            book_store.save(book)
            lock_status = "relocked" if relock else "new"
            lock_locked_at = book.locked_at

    start_capital = float(cfg.current_month_capital_twd)
    cash_weight = max(cfg.buffer_zone - sum(locked_weights.values()), 0.0)
    current_cash = start_capital * cash_weight
    portfolio_value = current_cash

    for t in locked_portfolio:
        buy_px = df_open.loc[rebalance_execution_date, t]
        cur_px = df_close.loc[last_idx, t]
        if pd.notna(buy_px) and pd.notna(cur_px) and buy_px > 0:
            invested = start_capital * locked_weights[t]
            portfolio_value += invested * (cur_px / buy_px) * (1 - cfg.transaction_cost)

    final_assets = portfolio_value
    target_total = final_assets + cfg.next_month_injection_twd

    # --- today signals ---
    roc_l = df_mom.loc[last_idx]
    roc_s = df_roc_short.loc[last_idx]
    spy_p = df_close.loc[last_idx, bench] if bench in df_close.columns else np.nan
    spy_ma = df_ma.loc[last_idx, bench] if bench in df_ma.columns else np.nan
    breadth = compute_breadth(offensive_universe, df_close.loc[last_idx], df_ma.loc[last_idx])
    mode = market_mode_label(spy_p, spy_ma, breadth, cfg.breadth_threshold) if cfg.show_market_mode else ""

    # --- block 1: holdings ---
    holdings: List[HoldingRow] = []
    for t in locked_portfolio:
        p = df_close.loc[last_idx, t]
        ma = df_ma.loc[last_idx, t]
        if pd.isna(p) or pd.isna(ma):
            continue

        rl = float(roc_l.get(t, 0) * 100)
        rs = float(roc_s.get(t, 0) * 100)
        dist = float((p / ma - 1) * 100) if ma > 0 else 0.0
        alert = "[🚀加速]" if rs > 0 else "[⚠️煞車]"

        buy_px = df_open.loc[rebalance_execution_date, t]
        est_val = start_capital * locked_weights.get(t, 0) * (p / buy_px) if pd.notna(buy_px) and buy_px > 0 else 0.0

        if dist < 0:
            action = "⚠️ 跌破均線，密切盯盤（月內續抱至換股日）"
        else:
            action = "✅ 安全持股（續抱至月底換股）"

        holdings.append(HoldingRow(t, rl, rs, dist, est_val, action, alert))

    # --- block 2: next month preview ---
    if use_rdyn:
        next_weights, next_regime, next_w_r3 = build_rdyn_weights(
            cfg,
            tickers,
            df_close.loc[last_idx],
            df_ma.loc[last_idx],
            roc_l,
            df_vol.loc[last_idx],
            roc_s,
            benchmark=bench,
        )
        next_picks = sorted(next_weights.keys(), key=lambda t: next_weights[t], reverse=True)
        rdyn_regime = next_regime
        rdyn_w_r3 = next_w_r3
        rdyn_blend_label = format_rdyn_blend_label(next_w_r3)
    else:
        next_picks = select_top_n(
            offensive_universe,
            df_close.loc[last_idx],
            df_ma.loc[last_idx],
            roc_l,
            df_vol.loc[last_idx],
            cfg.top_n_limit,
        )
        next_weights = finalize_weights(
            next_picks,
            df_vol.loc[last_idx],
            cfg.buffer_zone,
            cfg.max_weight_cap,
        )

    next_rows: List[RadarRow] = []
    for t in next_picks:
        rl = float(roc_l.get(t, 0) * 100)
        rs = float(roc_s.get(t, 0) * 100)
        dist = float((df_close.loc[last_idx, t] / df_ma.loc[last_idx, t] - 1) * 100)
        w = next_weights.get(t, 0.0)
        status = "🔥 核心領跑中 (續抱)" if t in locked_portfolio else "👀 準備切換 (新標的)"
        alert = "[🚀加速]" if rs > 0 else "[⚠️煞車]"
        next_rows.append(RadarRow(t, rl, rs, dist, w, target_total * w, status, alert))

    # --- block 3: other ---
    others = [t for t in offensive_universe if t not in locked_portfolio and t not in next_picks]
    others_ranked = sorted(
        others,
        key=lambda x: momentum_score(x, roc_l, df_vol.loc[last_idx]),
        reverse=True,
    )

    other_rows: List[RadarRow] = []
    for t in others_ranked:
        p = df_close.loc[last_idx, t]
        ma = df_ma.loc[last_idx, t]
        if pd.isna(p) or pd.isna(ma):
            continue
        rl = float(roc_l.get(t, 0) * 100)
        rs = float(roc_s.get(t, 0) * 100)
        dist = float((p / ma - 1) * 100)
        if dist >= 0:
            status = "⏳ 動能醞釀中 (均線之上，但排名落後)"
        else:
            status = "📉 跌破均線 (空頭趨勢 / 系統自動封鎖)"
        alert = "[🚀加速]" if rs > 0 else "[⚠️煞車]"
        other_rows.append(RadarRow(t, rl, rs, dist, 0.0, 0.0, status, alert))

    effective_exposure = sum(locked_weights.values())
    cash_drag = max(cfg.buffer_zone - effective_exposure, 0.0) + (1.0 - cfg.buffer_zone)

    theme_w = sum(w for t, w in locked_weights.items() if t in theme_set)
    if theme_w >= THEME_WARN_HARD:
        theme_warn = (
            f"⚠️ AI/半導主題曝險 {theme_w * 100:.0f}%（歷史約僅 2% 月份達此水準）"
            "——名目多檔仍可能是同一因子，勿再加碼同主題"
        )
    elif theme_w >= THEME_WARN_SOFT:
        theme_warn = (
            f"⚠️ AI/半導主題曝險 {theme_w * 100:.0f}% 偏高"
            "——分散是票數，風險可能仍集中"
        )
    else:
        theme_warn = f"AI/半導主題曝險 {theme_w * 100:.0f}%（正常區間）"

    return MonitorResult(
        run_time_tw=now_tw,
        query_date=last_idx,
        fx_rate=fx,
        final_assets_twd=final_assets,
        market_mode=mode,
        rebalance_decision_date=rebalance_decision_date,
        rebalance_execution_date=rebalance_execution_date,
        locked_portfolio=locked_portfolio,
        locked_weights=locked_weights,
        holdings=holdings,
        next_month_picks=next_picks,
        next_month_weights=next_weights,
        next_month_rows=next_rows,
        other_rows=other_rows,
        effective_exposure=effective_exposure,
        cash_drag_pct=cash_drag * 100,
        buffer_zone=cfg.buffer_zone,
        next_month_injection_twd=cfg.next_month_injection_twd,
        rdyn_regime=rdyn_regime,
        rdyn_w_r3=rdyn_w_r3,
        rdyn_blend_label=rdyn_blend_label,
        theme_ai_hw_weight=theme_w,
        theme_ai_hw_warning=theme_warn,
        book_lock_status=lock_status,
        book_locked_at=lock_locked_at,
        book_lock_note=lock_note,
        hist_close=df_close.tail(HISTORY_DAYS).copy(),
        hist_open=df_open.reindex(df_close.tail(HISTORY_DAYS).index).copy(),
        hist_ma=df_ma.tail(HISTORY_DAYS).copy(),
    )


def format_report(
    result: MonitorResult,
    is_morning: Optional[bool] = None,
    strategy_id: str = "apex_r",
    cfg: Optional[ApexConfig] = None,
    *,
    show_amounts: bool = False,
) -> str:
    if is_morning is None:
        is_morning = result.run_time_tw.hour < 12

    mom_days = cfg.momentum_days if cfg else 120
    try:
        from strategy_presets import report_header_cfg

        version_line = report_header_cfg(cfg) if cfg else report_header_cfg(ApexConfig(strategy_id=strategy_id))
    except Exception as exc:
        log.warning("report header unavailable: %s", exc)
        version_line = "Apex-R"

    mom_col = f"{mom_days}日動能"

    session = (
        (cfg.market_ctx().session_morning_label if cfg else "🌅 【早盤動態檢視】")
        if is_morning
        else (cfg.market_ctx().session_night_label if cfg else "🌃 【夜盤常規檢視】")
    )
    lines: List[str] = []
    w = 190
    sep = "━" * w
    dash = "-" * w

    target_total = result.final_assets_twd + result.next_month_injection_twd
    mkt = cfg.market_ctx() if cfg else None
    fx_display = result.fx_rate
    native_fx = mkt is not None and mkt.fx_symbol is None

    lines.append(sep)
    lines.append(
        f"{session} 執行時間: {result.run_time_tw.strftime('%Y-%m-%d %H:%M:%S')} (台灣時區) | {version_line}"
    )
    mkt_tag = f" | 市場: {mkt.label} | 基準: {mkt.benchmark}" if mkt else ""
    if native_fx:
        lines.append(
            f"🎯 查詢日: {result.query_date.strftime('%Y-%m-%d')}{mkt_tag} | "
            f"有效曝險: {result.effective_exposure * 100:.1f}% | 現金拖累: {result.cash_drag_pct:.1f}%"
        )
    else:
        lines.append(
            f"🎯 查詢日: {result.query_date.strftime('%Y-%m-%d')}{mkt_tag} | 匯率: {fx_display:.2f} | "
            f"有效曝險: {result.effective_exposure * 100:.1f}% | 現金拖累: {result.cash_drag_pct:.1f}%"
        )
    if show_amounts:
        if native_fx or fx_display <= 0:
            lines.append(
                f"💰 預估帳戶估值: NT${result.final_assets_twd:,.0f} | 🌊 戰略狀態: {result.market_mode}"
            )
        else:
            lines.append(
                f"💰 預估帳戶估值: NT${result.final_assets_twd:,.0f} "
                f"(約 ${result.final_assets_twd / fx_display:,.0f} USD) | 🌊 戰略狀態: {result.market_mode}"
            )
    else:
        lines.append(
            f"🌊 戰略狀態: {result.market_mode} | "
            f"※ 金額請填試算表（權重已給定，總資金由人填入）"
        )
    if result.rdyn_blend_label:
        regime_cn = {
            "offensive_full": "牛市",
            "offensive_half": "震盪",
            "bunker": "熊市",
        }.get(result.rdyn_regime, result.rdyn_regime)
        lines.append(
            f"   ※ RDyn-W 動態混合: {result.rdyn_blend_label} "
            f"(Regime: {regime_cn} | R3權重 {result.rdyn_w_r3 * 100:.0f}%)"
        )
    else:
        try:
            from strategy_presets import is_apex_m_strategy, product_name

            brand = product_name(cfg.strategy_id) if cfg is not None else "Apex-M"
            if cfg is not None and is_apex_m_strategy(cfg.strategy_id):
                lines.append(f"   ※ {brand}：R0 純動能，不做 regime 動態混合／減倉")
            else:
                lines.append(f"   ※ 戰略狀態僅供參考，{brand} 不做動態減倉")
        except Exception as exc:
            log.warning("regime note unavailable: %s", exc)
            lines.append("   ※ 戰略狀態僅供參考，不做動態減倉")
    if result.theme_ai_hw_warning:
        lines.append(f"   ※ 因子集中度: {result.theme_ai_hw_warning}")
    if cfg is not None:
        try:
            from universe_builder import format_universe_cycle_note

            lines.append(
                format_universe_cycle_note(
                    cfg.universe_last_updated,
                    result.query_date,
                    market=cfg.market,
                )
            )
        except Exception as exc:
            log.warning("universe cycle note unavailable: %s", exc)
    lines.append(sep)

    lines.append(
        f"🛡️ 【我的真實持倉監控】(鎖定自 {result.rebalance_execution_date.strftime('%Y-%m-%d')} 換股日)"
    )
    lines.append(dash)
    if getattr(result, "book_lock_status", ""):
        stamp = (result.book_locked_at or "").replace("T", " ")
        lines.append(
            f"   🔒 本月標的與權重已於 {stamp} 鎖定，月內任何日期查詢皆不變動；次月換股日才重新計算"
        )
        if result.book_lock_note:
            lines.append(f"   ⚠️ {result.book_lock_note}")
    if show_amounts:
        lines.append(
            f"{'資產代碼':<9} | {mom_col:>9} | {'20日加速':>8} | {'距200MA':>7} | "
            f"{'權重%':>6} | {'預估市值(TWD)':>13} | {'今日指令'}"
        )
        lines.append(dash)
        for h in result.holdings:
            wt = result.locked_weights.get(h.ticker, 0) * 100
            lines.append(
                f"{h.ticker:<9} | {h.roc_long:>8.1f}% | {h.roc_short:>7.1f}% | {h.dist_ma:>6.1f}% | "
                f"{wt:>5.1f}% | NT${h.est_value_twd:>11,.0f} | {h.alert} {h.action}"
            )
    else:
        lines.append(
            f"{'資產代碼':<9} | {mom_col:>9} | {'20日加速':>8} | {'距200MA':>7} | "
            f"{'權重%':>6} | {'今日指令'}"
        )
        lines.append(dash)
        for h in result.holdings:
            wt = result.locked_weights.get(h.ticker, 0) * 100
            lines.append(
                f"{h.ticker:<9} | {h.roc_long:>8.1f}% | {h.roc_short:>7.1f}% | {h.dist_ma:>6.1f}% | "
                f"{wt:>5.1f}% | {h.alert} {h.action}"
            )
    lines.append(sep)

    if show_amounts:
        lines.append(
            f"📡 【下月換股選秀與預演配資】"
            f"(現有資產 + 下月加碼 NT${result.next_month_injection_twd:,.0f}，"
            f"合計約 NT${target_total:,.0f} | normalize {result.buffer_zone * 100:.0f}%)"
        )
        lines.append(dash)
        lines.append(
            f"{'資產代碼':<9} | {mom_col:>11} | {'20日加速':>10} | {'距200MA':>7} | "
            f"{'預估權重%':>8} | {'預估配額(TWD)':>13} | {'狀態'}"
        )
        lines.append(dash)
        for r in result.next_month_rows:
            lines.append(
                f"{r.ticker:<9} | {r.roc_long:>10.1f}% | {r.roc_short:>9.1f}% | {r.dist_ma:>6.1f}% | "
                f"{r.est_weight * 100:>7.1f}% | NT${r.est_amount_twd:>11,.0f} | {r.status} {r.alert}"
            )
    else:
        lines.append(
            f"📡 【下月換股選秀與預演配資】"
            f"(權重 normalize {result.buffer_zone * 100:.0f}%｜金額見試算表 CSV)"
        )
        lines.append(dash)
        lines.append(
            f"{'資產代碼':<9} | {mom_col:>11} | {'20日加速':>10} | {'距200MA':>7} | "
            f"{'預估權重%':>8} | {'狀態'}"
        )
        lines.append(dash)
        for r in result.next_month_rows:
            lines.append(
                f"{r.ticker:<9} | {r.roc_long:>10.1f}% | {r.roc_short:>9.1f}% | {r.dist_ma:>6.1f}% | "
                f"{r.est_weight * 100:>7.1f}% | {r.status} {r.alert}"
            )
    lines.append(sep)

    lines.append("🌍 【全宇宙備用雷達】(未持有且未進榜)")
    lines.append(dash)
    lines.append(
        f"{'資產代碼':<9} | {mom_col:>11} | {'20日加速':>10} | {'距200MA':>7} | {'狀態'}"
    )
    lines.append(dash)
    for r in result.other_rows:
        lines.append(
            f"{r.ticker:<9} | {r.roc_long:>10.1f}% | {r.roc_short:>9.1f}% | {r.dist_ma:>6.1f}% | "
            f"{r.status} {r.alert}"
        )
    lines.append(sep)
    return "\n".join(lines)
