"""Lightweight monthly backtest used by the desktop 績效曲線 tab.

Uses the *live* selection/weighting functions (apex_core.build_rdyn_weights,
select_top_n, finalize_weights) so the curves follow the same rules as the
monitor. Each strategy is simulated twice from one weight plan:
  theory : no trading cost
  net    : turnover-based cost (US each side, TW sell tax + commission)

Universe: S&P 500 candidates ranked by dollar volume over the two calendar
years BEFORE each two-year cycle (no look-ahead). Candidate list is today's
S&P 500, so survivorship bias remains (noted in the UI).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from apex_core import (
    ApexConfig,
    build_rdyn_weights,
    finalize_weights,
    select_top_n,
)

log = logging.getLogger("apex_r")

BENCHMARK = "SPY"
EXTRA_BENCH = "QQQ"
MA_DAYS = 200
VOL_DAYS = 20
ROC_SHORT_DAYS = 20
BUFFER = 0.97
CAP = 0.10
CYCLE_YEARS = 2


@dataclass(frozen=True)
class CostModel:
    us_buy: float = 0.002
    us_sell: float = 0.002
    tw_buy: float = 0.001425  # commission
    tw_sell: float = 0.001425 + 0.003  # commission + securities transaction tax

    def rates(self, ticker: str) -> Tuple[float, float]:
        if ticker.upper().endswith((".TW", ".TWO")):
            return self.tw_buy, self.tw_sell
        return self.us_buy, self.us_sell


ZERO_COST = CostModel(0.0, 0.0, 0.0, 0.0)


@dataclass(frozen=True)
class StrategySpec:
    key: str
    label: str
    strategy_id: str  # apex_rdyn_w | apex_m
    top_n: int
    universe_size: int
    momentum_days: int = 120


SPECS: List[StrategySpec] = [
    StrategySpec("apex_r", "Apex-R (RDyn-W)", "apex_rdyn_w", top_n=10, universe_size=60),
    StrategySpec("apex_m", "Apex-M (R0)", "apex_m", top_n=12, universe_size=65),
]

SERIES_LABELS = {
    "apex_r_theory": "Apex-R 理論值",
    "apex_r_net": "Apex-R 扣成本",
    "apex_m_theory": "Apex-M 理論值",
    "apex_m_net": "Apex-M 扣成本",
    "SPY": "SPY",
    "QQQ": "QQQ",
}


# ---------------------------------------------------------------- universe
def cycle_key(dt: pd.Timestamp) -> int:
    y = dt.year
    return y if y % 2 == 1 else y - 1


def build_cycles(
    volume: pd.DataFrame, close: pd.DataFrame, candidates: List[str], size: int,
    first_year: int, last_year: int,
) -> Dict[int, List[str]]:
    """Cycle y (odd) covers years y and y+1; ranked on dollar volume of y-2 and y-1."""
    cycles: Dict[int, List[str]] = {}
    for y in range(first_year if first_year % 2 else first_year + 1, last_year + 1, CYCLE_YEARS):
        mask = volume.index.year.isin([y - 2, y - 1])
        if not mask.any():
            continue
        dv = (volume.loc[mask] * close.loc[mask]).sum(axis=0).dropna()
        ranked = [t for t in sorted((t for t in candidates if t in dv.index and dv[t] > 0),
                                    key=lambda t: dv[t], reverse=True)][:size]
        if ranked:
            cycles[y] = ranked
    return cycles


def universe_for(cycles: Dict[int, List[str]], dt: pd.Timestamp) -> List[str]:
    ck = cycle_key(dt)
    if ck in cycles:
        return cycles[ck]
    return []  # no earlier data than the first cycle → stay in cash


# ---------------------------------------------------------------- weights plan
def plan_weights(
    spec: StrategySpec, close: pd.DataFrame, opn: pd.DataFrame, volume: pd.DataFrame,
    candidates: List[str], start: pd.Timestamp, end: pd.Timestamp,
    cancel: Optional[Callable[[], bool]] = None,
) -> Dict[pd.Timestamp, Dict[str, float]]:
    """{execution_date: weights} for each month start in [start, end]."""
    c = close.ffill()
    ma = c.rolling(MA_DAYS).mean()
    vol = c.pct_change(fill_method=None).rolling(VOL_DAYS).std()
    mom = c.pct_change(spec.momentum_days, fill_method=None)
    rs = c.pct_change(ROC_SHORT_DAYS, fill_method=None)
    cycles = build_cycles(volume, close, candidates, spec.universe_size,
                          c.index[0].year + CYCLE_YEARS, end.year)
    cfg = ApexConfig(strategy_id=spec.strategy_id, top_n_limit=spec.top_n,
                     momentum_days=spec.momentum_days, buffer_zone=BUFFER, max_weight_cap=CAP)
    idx = c.index
    plan: Dict[pd.Timestamp, Dict[str, float]] = {}
    for i in range(1, len(idx)):
        if idx[i].month == idx[i - 1].month or idx[i] < start or idx[i] > end:
            continue
        if cancel and cancel():
            raise InterruptedError("cancelled")
        dec, exe = idx[i - 1], idx[i]
        uni = [t for t in universe_for(cycles, dec) if t in c.columns and t != BENCHMARK]
        if not uni:
            plan[exe] = {}
            continue
        if spec.strategy_id == "apex_rdyn_w":
            w, _mode, _w3 = build_rdyn_weights(
                cfg, uni + [BENCHMARK], c.loc[dec], ma.loc[dec], mom.loc[dec], vol.loc[dec],
                rs.loc[dec], benchmark=BENCHMARK,
            )
        else:
            picks = select_top_n(uni, c.loc[dec], ma.loc[dec], mom.loc[dec], vol.loc[dec], spec.top_n)
            w = finalize_weights(picks, vol.loc[dec], BUFFER, CAP) if picks else {}
        plan[exe] = w
    return plan


# ---------------------------------------------------------------- simulation
@dataclass
class SimResult:
    equity: pd.Series
    avg_monthly_turnover: float  # fraction of portfolio traded per rebalance (one-way)
    cost_paid_pct: float  # total cost as % of initial capital


def simulate(
    plan: Dict[pd.Timestamp, Dict[str, float]], close: pd.DataFrame, opn: pd.DataFrame,
    costs: CostModel, initial: float = 100.0,
) -> SimResult:
    execs = sorted(d for d, w in plan.items() if w)
    if not execs:
        return SimResult(pd.Series(dtype=float), 0.0, 0.0)
    c = close.ffill()
    o = opn.reindex(c.index).ffill()
    idx = c.index[c.index >= execs[0]]
    cols = list(c.columns)
    col_ix = {t: i for i, t in enumerate(cols)}
    cn, on = c.to_numpy(float), o.to_numpy(float)
    pos = {d: i for i, d in enumerate(c.index)}
    buy_r = np.array([costs.rates(t)[0] for t in cols])
    sell_r = np.array([costs.rates(t)[1] for t in cols])

    shares = np.zeros(len(cols))
    cash = float(initial)
    eq, turnovers, cost_paid = [], [], 0.0
    for d in idx:
        r = pos[d]
        if d in plan and plan[d]:
            price = np.where(np.isfinite(on[r]) & (on[r] > 0), on[r], cn[r])
            valid = np.isfinite(price) & (price > 0)
            total = cash + float(np.nansum(shares * np.where(valid, price, 0.0)))
            target = np.zeros(len(cols))
            for t, w in plan[d].items():
                j = col_ix.get(t)
                if j is not None and valid[j]:
                    target[j] = total * w
            cur = shares * np.where(valid, price, 0.0)
            delta = target - cur
            sells = np.where(delta < 0, -delta, 0.0)
            buys = np.where(delta > 0, delta, 0.0)
            sell_cost = float((sells * sell_r).sum())
            cash += float(sells.sum()) - sell_cost
            need = float((buys * (1 + buy_r)).sum())
            scale = min(1.0, cash / need) if need > 0 else 1.0
            buys *= scale
            buy_cost = float((buys * buy_r).sum())
            cash -= float(buys.sum()) + buy_cost
            safe = np.where(valid, price, 1.0)
            shares = shares - sells / safe + buys / safe
            cost_paid += sell_cost + buy_cost
            turnovers.append(float(sells.sum() + buys.sum()) / 2 / total if total > 0 else 0.0)
        eq.append(cash + float(np.nansum(shares * np.where(np.isfinite(cn[r]), cn[r], 0.0))))
    return SimResult(pd.Series(eq, index=idx), float(np.mean(turnovers)) if turnovers else 0.0,
                     cost_paid / initial * 100)


# ---------------------------------------------------------------- stats / periods
def perf_stats(eq: pd.Series) -> Dict[str, float]:
    eq = eq.dropna()
    nan = float("nan")
    if len(eq) < 3:
        return dict(total=nan, cagr=nan, vol=nan, sharpe=nan, mdd=nan, calmar=nan, final=nan)
    yrs = (eq.index[-1] - eq.index[0]).days / 365.25
    total = eq.iloc[-1] / eq.iloc[0] - 1
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else nan
    dr = eq.pct_change().dropna()
    vol = dr.std() * np.sqrt(252)
    sharpe = dr.mean() * 252 / vol if vol > 0 else nan
    mdd = (eq / eq.cummax() - 1).min()
    calmar = cagr / abs(mdd) if mdd < 0 else nan
    return dict(total=total * 100, cagr=cagr * 100, vol=vol * 100, sharpe=sharpe, mdd=mdd * 100,
                calmar=calmar, final=float(eq.iloc[-1]))


def period_start(end: pd.Timestamp, years: Optional[float]) -> Optional[pd.Timestamp]:
    return None if years is None else end - pd.DateOffset(years=years)


def slice_rebased(curves: Dict[str, pd.Series], years: Optional[float]) -> Dict[str, pd.Series]:
    """Cut every series to the period and rebase to 100 at a common first date."""
    live = {k: s.dropna() for k, s in curves.items() if s is not None and not s.dropna().empty}
    if not live:
        return {}
    end = max(s.index[-1] for s in live.values())
    lo = period_start(end, years)
    first = max(s.index[0] for s in live.values())
    if lo is not None:
        first = max(first, lo)
    out = {}
    for k, s in live.items():
        s = s.loc[s.index >= first]
        if len(s) >= 2:
            out[k] = s / s.iloc[0] * 100.0
    return out


# ---------------------------------------------------------------- data download
def _extract(raw: pd.DataFrame) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(adj_close, adj_open, volume) from a yfinance frame downloaded with auto_adjust=False."""
    if not isinstance(raw.columns, pd.MultiIndex):
        raise ValueError("unexpected yfinance frame")
    cr = raw["Close"]
    adj = raw["Adj Close"] if "Adj Close" in raw.columns.get_level_values(0) else cr
    ratio = adj / cr.replace(0, np.nan)
    return adj, raw["Open"] * ratio, raw["Volume"]


def download_history(
    symbols: List[str], start: str, end: str, chunk: int = 60,
    progress: Optional[Callable[[str], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    from apex_core import _download_chunk_with_retry

    closes, opens, vols = [], [], []
    for i in range(0, len(symbols), chunk):
        if cancel and cancel():
            raise InterruptedError("cancelled")
        part = symbols[i:i + chunk]
        if progress:
            progress(f"下載行情 {min(i + chunk, len(symbols))}/{len(symbols)}")
        raw = _download_chunk_with_retry(part, start, end)
        if raw.empty:
            log.warning("backtest download: empty chunk %s..", part[:3])
            continue
        a, o, v = _extract(raw)
        closes.append(a); opens.append(o); vols.append(v)
    if not closes:
        raise RuntimeError("下載不到任何行情，請確認網路連線（Yahoo Finance）後再試。")

    def cat(frames):
        df = pd.concat(frames, axis=1)
        return df.loc[:, ~df.columns.duplicated()].sort_index()

    c, o, v = cat(closes), cat(opens), cat(vols)
    return c.dropna(how="all"), o.reindex(c.index), v.reindex(c.index)


# ---------------------------------------------------------------- orchestration
def compute_all(
    close: pd.DataFrame, opn: pd.DataFrame, volume: pd.DataFrame, candidates: List[str],
    *, years: int = 15, costs: CostModel = CostModel(),
    progress: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
) -> Tuple[pd.DataFrame, dict]:
    say = progress or (lambda _m: None)
    end = close.index[-1]
    start = end - pd.DateOffset(years=years)
    curves: Dict[str, pd.Series] = {}
    stats_meta: Dict[str, dict] = {}
    for spec in SPECS:
        say(f"回測 {spec.label} …")
        plan = plan_weights(spec, close, opn, volume, candidates, start, end, cancel)
        theory = simulate(plan, close, opn, ZERO_COST)
        net = simulate(plan, close, opn, costs)
        curves[f"{spec.key}_theory"] = theory.equity
        curves[f"{spec.key}_net"] = net.equity
        stats_meta[spec.key] = dict(avg_monthly_turnover_pct=round(net.avg_monthly_turnover * 100, 1),
                                    total_cost_pct_of_capital=round(net.cost_paid_pct, 1))
    for sym in (BENCHMARK, EXTRA_BENCH):
        if sym in close.columns:
            s = close[sym].dropna()
            curves[sym] = s.loc[s.index >= start]
    df = pd.DataFrame(curves).sort_index()
    meta = dict(
        generated_at=pd.Timestamp.now().isoformat(timespec="seconds"),
        data_end=str(end.date()), years=years, candidates=len(candidates),
        costs=dict(us_each_side=costs.us_buy, tw_buy=costs.tw_buy, tw_sell=costs.tw_sell),
        specs={s.key: dict(label=s.label, top_n=s.top_n, universe_size=s.universe_size) for s in SPECS},
        stats=stats_meta,
        notes=["回測，非實盤；美元計價，起點=100",
               "宇宙：今日 S&P 500 成分股，依前兩年成交額排序（含存活者偏差，約高估 0.1~0.5pp 年化）",
               "扣成本：依每月實際換手量計算（美股每邊 0.2%；台股賣出稅 0.3% + 手續費 0.1425%）"],
    )
    return df, meta


def save_results(folder: Path, df: pd.DataFrame, meta: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    df.to_csv(folder / "curves.csv", index_label="date")
    (folder / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")


def load_results(folder: Path) -> Optional[Tuple[pd.DataFrame, dict]]:
    try:
        df = pd.read_csv(folder / "curves.csv", index_col="date", parse_dates=True)
        meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
        return df, meta
    except (OSError, ValueError, KeyError):
        return None
