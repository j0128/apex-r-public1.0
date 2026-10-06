"""
Build the Apex-R investment universe.

US candidates: current S&P 500 constituents (live fetch).
  - dollar_volume: Top N by prior 2-calendar-year dollar volume
  - momentum:      Top N by 2-year price return

Live monitors (Apex 4.0+) only allow a full universe rebuild about every
two years, matching the backtest universe-cycle cadence. Use force=True to
override (not recommended mid-lock month).

TW names: appended manually from config (not screened from S&P 500).

Falls back to a small master pool only if the S&P 500 list cannot be fetched.
"""

from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Literal, Optional, Sequence, Tuple
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

log = logging.getLogger("apex_r")

UniverseMode = Literal["dollar_volume", "momentum"]

MOMENTUM_2Y_DAYS = 504
DEFAULT_UNIVERSE_SIZE = 65
# Live refresh gate: align with backtest ~2-year universe cycles
UNIVERSE_REFRESH_YEARS = 2
UNIVERSE_REFRESH_DAYS = int(round(365.25 * UNIVERSE_REFRESH_YEARS))
MIN_HISTORY_DAYS = 200
MIN_AVG_DOLLAR_VOLUME = 5_000_000.0
DOWNLOAD_CHUNK = 80
WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SP500_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
)

# Master pool — same spirit as backtest_compare.py MASTER_TICKERS_RAW
MASTER_TICKERS_RAW = """
GLD, URA, NVDA, AMD, TSM, AVGO, ASML, INTC, CDNS, SNPS, QCOM, TXN,
AAPL, MSFT, GOOGL, AMZN, META, TSLA, NFLX, CRM, NOW, ADBE, PANW, CRWD, PLTR, ORCL,
INTU, V, MA, AXP, SPGI, MCO, JPM, BAC, GS, BLK, COST, WMT, PG, PEP, KO, MCD, LLY,
NVO, ISRG, UNH, JNJ, ABBV, LIN, CAT, DE, UNP, LMT, RTX, TDG, XOM, CVX, FCX, SLB,
MU, AMAT, LRCX, KLAC, ARM, SMCI, NXPI, MRVL, MCHP, IBM, CSCO, SHOP, UBER, ABNB,
WFC, C, MS, PYPL, HOOD, PFE, MRK, CVS, GILD, BIIB, AMGN, REGN, VRTX, HD, LOW, TGT,
SBUX, NKE, CMG, COP, HAL, BA, GE, HON, UPS, FDX, NUE, ALB, DIS, CMCSA, T, VZ,
BABA, JD, PDD, BIDU
""".replace("\n", " ")

CRYPTO_EXCLUDE = {"IBIT", "COIN", "MSTR", "MARA", "RIOT"}
ETF_EXCLUDE = {"GLD", "URA", "SPY", "QQQ", "IWM", "DIA", "BIL"}

# Taiwan ETFs / index proxies — use as benchmark, not in stock universe
TW_ETF_EXCLUDE = {
    "0050.TW", "0051.TW", "0052.TW", "0053.TW", "0055.TW", "0056.TW",
    "0061.TW", "006201.TW", "006203.TW", "006208.TW", "00631L.TW", "00632R.TW",
    "00633L.TW", "00634R.TW", "00635U.TW", "00636.TW", "00642U.TW", "00646.TW",
    "00655L.TW", "00657.TW", "00662.TW", "00675L.TW", "00692.TW", "00701.TW",
    "00713.TW", "00731.TW", "00757.TW", "00850.TW", "00878.TW", "00881.TW",
    "00885.TW", "00891.TW", "00892.TW", "00893.TW", "00894.TW", "00895.TW",
    "00896.TW", "00900.TW", "00919.TW", "00922.TW", "00923.TW", "00929.TW",
    "00932.TW", "00939.TW", "00940.TW", "00944.TW", "00946.TW", "00947.TW",
}

# Curated liquid TWSE/TPEx master pool for Apex-TW experiments (~90 names)
TW_MASTER_TICKERS_RAW = """
2330.TW, 2317.TW, 2454.TW, 2303.TW, 2382.TW, 2308.TW, 3711.TW, 2891.TW, 2881.TW,
2882.TW, 2886.TW, 2892.TW, 2884.TW, 2885.TW, 2880.TW, 2887.TW, 2890.TW, 2883.TW,
5871.TW, 5876.TW, 2912.TW, 2412.TW, 3045.TW, 4904.TW, 6505.TW, 1301.TW, 1303.TW,
1326.TW, 2002.TW, 1101.TW, 1216.TW, 2207.TW, 2105.TW, 9910.TW, 3034.TW, 2379.TW,
2327.TW, 6669.TW, 3661.TW, 3037.TW, 3231.TW, 2357.TW, 2395.TW, 2345.TW, 3008.TW,
4938.TW, 2474.TW, 2301.TW, 2356.TW, 2409.TW, 2618.TW, 2610.TW, 2603.TW, 2609.TW,
6770.TW, 6488.TW, 8299.TWO, 3443.TW, 5269.TW, 8046.TW, 3105.TWO, 4966.TW, 6415.TW,
8454.TW, 8464.TW, 9914.TW, 1476.TW, 1504.TW, 1605.TW, 1717.TW, 1722.TW, 1904.TW,
2015.TW, 2049.TW, 2059.TW, 2201.TW, 2227.TW, 2231.TW, 2313.TW, 2324.TW, 2344.TW,
2347.TW, 2353.TW, 2360.TW, 2376.TW, 2377.TW, 2383.TW, 2408.TW, 2449.TW, 2498.TW,
2801.TW, 2834.TW, 2888.TW, 3006.TW, 3017.TW, 3023.TW, 3035.TW, 3036.TW, 3044.TW,
3189.TW, 3406.TW, 3481.TW, 3532.TW, 3653.TW, 3702.TW, 6176.TW, 6239.TW, 6271.TW,
6285.TW, 6409.TW, 6456.TW, 6531.TW, 6592.TW, 6706.TW, 6781.TW, 8016.TW, 8069.TWO,
8112.TW, 8210.TW, 9945.TW, 2633.TW, 2542.TW, 1402.TW, 9904.TW, 1229.TW, 1795.TW,
2340.TW, 2441.TW, 2458.TW, 2615.TW, 2809.TW, 2915.TW, 3030.TW, 3596.TW, 4919.TW,
4958.TW, 5347.TWO, 5483.TWO, 6182.TWO, 6274.TW, 6443.TW, 6669.TW, 6756.TW, 6861.TW
""".replace("\n", " ")

# TW avg daily TWD volume floor (~50M TWD ≈ US $1.5M) for momentum mode
MIN_AVG_DOLLAR_VOLUME_TW = 50_000_000.0
DEFAULT_TW_UNIVERSE_SIZE = 60



@dataclass
class UniverseBuildResult:
    us_tickers: List[str]
    tw_tickers: List[str]
    combined: List[str]
    as_of: str
    mode: str
    candidate_count: int
    ranked_table: pd.DataFrame = field(repr=False)
    source: str = "master"

    def summary_lines(self) -> List[str]:
        mode_label = "兩年成交額" if self.mode == "dollar_volume" else "兩年動量"
        is_tw_only = bool(self.tw_tickers) and not self.us_tickers
        if is_tw_only:
            lines = [
                f"台股宇宙更新完成 | 基準日 {self.as_of} | 候選池 {self.candidate_count} 檔 ({self.source})",
                f"台股 {mode_label} Top {len(self.tw_tickers)}",
                "",
            ]
            if self.mode == "dollar_volume":
                lines.append("台股 Top 15 (兩年成交額 TWD):")
                for _, row in self.ranked_table.head(15).iterrows():
                    lines.append(f"  {row['ticker']:10s}  NT${row['dollar_volume_2y']/1e9:,.1f}B")
            else:
                lines.append("台股 Top 15 (兩年報酬率):")
                for _, row in self.ranked_table.head(15).iterrows():
                    lines.append(
                        f"  {row['ticker']:10s}  {row['momentum_2y']:+.1%}  avg$vol {row['avg_dollar_vol']:,.0f}"
                    )
            if len(self.tw_tickers) > 15:
                lines.append(f"  ... 共 {len(self.tw_tickers)} 檔")
            return lines

        lines = [
            f"宇宙更新完成 | 基準日 {self.as_of} | 候選池 {self.candidate_count} 檔 ({self.source})",
            f"美股 {mode_label} Top {len(self.us_tickers)} + 台股 {len(self.tw_tickers)} 檔",
            "",
        ]
        if self.mode == "dollar_volume":
            lines.append("美股 Top 15 (兩年成交額):")
            for _, row in self.ranked_table.head(15).iterrows():
                lines.append(f"  {row['ticker']:6s}  ${row['dollar_volume_2y']/1e9:,.1f}B")
        else:
            lines.append("美股 Top 15 (兩年報酬率):")
            for _, row in self.ranked_table.head(15).iterrows():
                lines.append(
                    f"  {row['ticker']:6s}  {row['momentum_2y']:+.1%}  avg$vol {row['avg_dollar_vol']:,.0f}"
                )
        if len(self.us_tickers) > 15:
            lines.append(f"  ... 共 {len(self.us_tickers)} 檔")
        if self.tw_tickers:
            lines.append("")
            lines.append("台股 (手動): " + ", ".join(self.tw_tickers))
        return lines


def is_tw_ticker(ticker: str) -> bool:
    t = ticker.strip().upper()
    return t.endswith(".TW") or t.endswith(".TWO")


def yfinance_symbol(symbol: str) -> str:
    return symbol.strip().upper().replace(".", "-")


def parse_ticker_csv(raw: str) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for part in raw.replace("\n", " ").split(","):
        t = part.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def split_us_tw(tickers: Sequence[str]) -> Tuple[List[str], List[str]]:
    us, tw = [], []
    for t in tickers:
        if is_tw_ticker(t):
            tw.append(t)
        else:
            us.append(t)
    return us, tw


def master_pool() -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for t in parse_ticker_csv(MASTER_TICKERS_RAW):
        if t in CRYPTO_EXCLUDE or t in ETF_EXCLUDE or is_tw_ticker(t) or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def tw_master_pool(
    *,
    exclude_etf: bool = True,
    exclude_benchmark: str = "0050.TW",
) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    bench = (exclude_benchmark or "").strip().upper()
    for t in parse_ticker_csv(TW_MASTER_TICKERS_RAW):
        if not is_tw_ticker(t) or t in seen:
            continue
        if exclude_etf and t in TW_ETF_EXCLUDE:
            continue
        if bench and t == bench:
            continue
        seen.add(t)
        out.append(t)
    return out


def fetch_sp500_tickers() -> List[str]:
    try:
        req = Request(SP500_CSV_URL, headers={"User-Agent": "Apex-R/1.0"})
        with urlopen(req, timeout=30) as resp:
            df = pd.read_csv(resp)
        col = "Symbol" if "Symbol" in df.columns else df.columns[0]
        symbols = df[col].astype(str).tolist()
    except Exception as exc:
        log.warning("S&P 500 CSV source failed (%s); trying Wikipedia", exc)
        req = Request(WIKI_SP500_URL, headers={"User-Agent": "Apex-R/1.0"})
        with urlopen(req, timeout=30) as resp:
            html = resp.read()
        tables = pd.read_html(html)
        symbols = tables[0]["Symbol"].astype(str).tolist()

    out: List[str] = []
    seen: set[str] = set()
    for sym in symbols:
        t = yfinance_symbol(sym)
        if t and t not in seen and t not in ETF_EXCLUDE and t not in CRYPTO_EXCLUDE:
            seen.add(t)
            out.append(t)
    if len(out) < 400:
        raise RuntimeError(f"S&P 500 parse yielded only {len(out)} symbols")
    return out


def get_candidate_pool(mode: UniverseMode) -> Tuple[List[str], str]:
    """US screening pool. Both modes use S&P 500; master is offline fallback only."""
    del mode  # same pool for dollar_volume and momentum
    try:
        return fetch_sp500_tickers(), "sp500"
    except Exception as exc:
        log.warning("S&P 500 fetch failed (%s); using offline master pool", exc)
        return master_pool(), "master_fallback"


def _yf_session():
    try:
        from curl_cffi import requests as cfi_requests

        return cfi_requests.Session(impersonate="chrome")
    except Exception as exc:
        log.info("curl_cffi session unavailable: %s", exc)
        return None


def _download_chunk(symbols: List[str], start: str, end: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    if not symbols:
        return pd.DataFrame(), pd.DataFrame()
    kwargs = dict(
        start=start,
        end=end,
        progress=False,
        auto_adjust=False,
        threads=True,
    )
    session = _yf_session()
    if session is not None:
        kwargs["session"] = session
    raw = yf.download(symbols, **kwargs)
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"].ffill()
        vol = raw["Volume"].ffill()
    else:
        sym = symbols[0]
        close = raw[["Close"]].copy()
        close.columns = [sym]
        vol = raw[["Volume"]].copy()
        vol.columns = [sym]

    return close.dropna(how="all"), vol.reindex(close.index).ffill()


def download_prices(
    symbols: List[str],
    start: str,
    end: str,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    frames_close: List[pd.DataFrame] = []
    frames_vol: List[pd.DataFrame] = []
    for i in range(0, len(symbols), DOWNLOAD_CHUNK):
        chunk = symbols[i : i + DOWNLOAD_CHUNK]
        close, vol = _download_chunk(chunk, start, end)
        if not close.empty:
            frames_close.append(close)
            frames_vol.append(vol)

    if not frames_close:
        raise RuntimeError("無法下載候選股票行情。")

    close = pd.concat(frames_close, axis=1)
    close = close.loc[:, ~close.columns.duplicated()]
    volume = pd.concat(frames_vol, axis=1)
    volume = volume.reindex(close.index).ffill()
    volume = volume.loc[:, close.columns]
    return close, volume


def two_year_dollar_volume(
    vol: pd.DataFrame,
    close: pd.DataFrame,
    as_of: pd.Timestamp,
) -> pd.Series:
    """Sum dollar volume over prior two calendar years (matches backtest_compare)."""
    end_year = as_of.year - 1
    years = [end_year - 1, end_year]
    mask = vol.index.year.isin(years)
    if mask.any():
        return (vol.loc[mask] * close.loc[mask]).sum(axis=0).dropna()
    window = min(MOMENTUM_2Y_DAYS, len(vol))
    return (vol.iloc[-window:] * close.iloc[-window:]).sum(axis=0).dropna()


def rank_by_dollar_volume(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    as_of: pd.Timestamp,
) -> pd.DataFrame:
    dv = two_year_dollar_volume(volume, close, as_of)
    rows = []
    for t in close.columns:
        total_dv = dv.get(t, np.nan)
        if pd.isna(total_dv) or total_dv <= 0:
            continue
        hist = close[t].dropna()
        if len(hist) < MIN_HISTORY_DAYS:
            continue
        rows.append({"ticker": t, "dollar_volume_2y": float(total_dv)})

    if not rows:
        raise RuntimeError("篩選後無有效候選股票。")

    return pd.DataFrame(rows).sort_values("dollar_volume_2y", ascending=False).reset_index(drop=True)


def rank_by_momentum(
    close: pd.DataFrame,
    volume: pd.DataFrame,
    momentum_days: int = MOMENTUM_2Y_DAYS,
    min_avg_dollar_vol: float = MIN_AVG_DOLLAR_VOLUME,
) -> pd.DataFrame:
    if len(close) < momentum_days + 5:
        raise RuntimeError(f"歷史資料不足 {momentum_days} 交易日。")

    mom = close.pct_change(momentum_days).iloc[-1]
    dollar_vol = (close * volume).mean()
    rows = []
    for t in close.columns:
        m = mom.get(t, np.nan)
        avg_dv = dollar_vol.get(t, np.nan)
        hist = close[t].dropna()
        if pd.isna(m) or len(hist) < MIN_HISTORY_DAYS:
            continue
        if pd.isna(avg_dv) or avg_dv < min_avg_dollar_vol:
            continue
        rows.append({"ticker": t, "momentum_2y": float(m), "avg_dollar_vol": float(avg_dv)})

    if not rows:
        raise RuntimeError("篩選後無有效候選股票。")

    return pd.DataFrame(rows).sort_values("momentum_2y", ascending=False).reset_index(drop=True)


def apply_corporate_event_adjustments(
    ranked: pd.DataFrame,
    mode: UniverseMode,
    event_scores: Optional[Dict[str, float]] = None,
) -> pd.DataFrame:
    """Placeholder for 股東會 / 法說會 ranking adjustments."""
    if not event_scores:
        return ranked
    out = ranked.copy()
    score_col = "dollar_volume_2y" if mode == "dollar_volume" else "momentum_2y"
    out["event_boost"] = out["ticker"].map(event_scores).fillna(0.0)
    if mode == "dollar_volume":
        out["adjusted_score"] = out[score_col] * (1.0 + out["event_boost"])
    else:
        out["adjusted_score"] = out[score_col] + out["event_boost"]
    return out.sort_values("adjusted_score", ascending=False).reset_index(drop=True)


def _parse_as_of(as_of: str | datetime | pd.Timestamp | None) -> pd.Timestamp:
    if as_of is None or (isinstance(as_of, str) and not str(as_of).strip()):
        return pd.Timestamp(datetime.utcnow().date())
    return pd.Timestamp(as_of).normalize()


def next_universe_refresh_date(last_updated: str | None) -> Optional[pd.Timestamp]:
    """Earliest date a non-forced live refresh is allowed."""
    if not last_updated or not str(last_updated).strip():
        return None
    return _parse_as_of(last_updated) + pd.Timedelta(days=UNIVERSE_REFRESH_DAYS)


def universe_refresh_status(
    last_updated: str | None,
    as_of: str | datetime | pd.Timestamp | None = None,
) -> Dict[str, object]:
    """Status dict for UI / reports about the 2-year universe lock."""
    as_of_ts = _parse_as_of(as_of)
    if not last_updated or not str(last_updated).strip():
        return {
            "has_stamp": False,
            "last_updated": "",
            "next_refresh": None,
            "days_remaining": 0,
            "allowed": True,
            "message": "宇宙尚未蓋章；允許首次更新，完成後將鎖定約兩年。",
        }
    last_ts = _parse_as_of(last_updated)
    nxt = last_ts + pd.Timedelta(days=UNIVERSE_REFRESH_DAYS)
    days_left = int((nxt - as_of_ts).days)
    allowed = days_left <= 0
    if allowed:
        msg = (
            f"宇宙上次更新 {last_ts.date()}；已滿約 {UNIVERSE_REFRESH_YEARS} 年，允許刷新。"
        )
    else:
        msg = (
            f"宇宙上次更新 {last_ts.date()}；下次可更新日 {nxt.date()} "
            f"（尚餘約 {days_left} 天／週期 {UNIVERSE_REFRESH_YEARS} 年）。"
        )
    return {
        "has_stamp": True,
        "last_updated": str(last_ts.date()),
        "next_refresh": str(nxt.date()),
        "days_remaining": max(days_left, 0),
        "allowed": allowed,
        "message": msg,
    }


def can_refresh_universe(
    last_updated: str | None,
    as_of: str | datetime | pd.Timestamp | None = None,
    *,
    force: bool = False,
) -> Tuple[bool, str]:
    """Return (allowed, reason). force=True bypasses the 2-year gate."""
    status = universe_refresh_status(last_updated, as_of)
    if force:
        return True, "已啟用強制更新（略過兩年週期閘門）。"
    if status["allowed"]:
        return True, str(status["message"])
    return False, str(status["message"])


def ensure_universe_cycle_stamp(
    last_updated: str | None,
    as_of: str | datetime | pd.Timestamp | None = None,
) -> str:
    """
    If no stamp exists, lock the current universe clock to as_of.
    Does not rebuild tickers — only writes the cycle timestamp.
    """
    if last_updated and str(last_updated).strip():
        return str(_parse_as_of(last_updated).date())
    return str(_parse_as_of(as_of).date())


def format_universe_cycle_note(
    last_updated: str | None,
    as_of: str | datetime | pd.Timestamp | None = None,
    *,
    market: str = "us",
) -> str:
    status = universe_refresh_status(last_updated, as_of)
    market_label = "台股" if str(market).strip().lower() in ("tw", "taiwan", "twse", "台股") else "美股"
    tip = "建議：滿兩年後、換倉決策日之前、盡量靠近年初／奇數年 cycle 再整池刷新。"
    if not status["has_stamp"]:
        return (
            f"※ {market_label}宇宙：尚未蓋兩年週期章（首次更新後將鎖定約兩年）\n"
            f"※ {tip}"
        )
    nxt = status["next_refresh"]
    return (
        f"※ {market_label}宇宙鎖定: 上次更新 {status['last_updated']} | "
        f"下次可更新 >= {nxt}（週期 {UNIVERSE_REFRESH_YEARS} 年）\n"
        f"※ {tip}"
    )


def build_universe(
    as_of: str,
    top_n: int = DEFAULT_UNIVERSE_SIZE,
    tw_tickers: Optional[Sequence[str]] = None,
    mode: UniverseMode = "dollar_volume",
    momentum_days: int = MOMENTUM_2Y_DAYS,
    event_scores: Optional[Dict[str, float]] = None,
    candidate_pool: Optional[Sequence[str]] = None,
    *,
    market: str = "us",
    benchmark: str = "",
) -> UniverseBuildResult:
    market_key = (market or "us").strip().lower()
    if market_key in ("tw", "taiwan", "twse", "台股"):
        return build_tw_universe(
            as_of=as_of,
            top_n=top_n,
            mode=mode,
            momentum_days=momentum_days,
            event_scores=event_scores,
            candidate_pool=candidate_pool,
            benchmark=benchmark or "0050.TW",
        )

    as_of_ts = pd.to_datetime(as_of)
    lookback_calendar = int(MOMENTUM_2Y_DAYS * 1.6) + 60
    start = (as_of_ts - timedelta(days=lookback_calendar)).strftime("%Y-%m-%d")
    end = (as_of_ts + timedelta(days=1)).strftime("%Y-%m-%d")

    if candidate_pool is None:
        candidates, source = get_candidate_pool(mode)
    else:
        candidates = [t for t in candidate_pool if not is_tw_ticker(t)]
        source = "custom"

    close, volume = download_prices(candidates, start, end)
    close = close.loc[:as_of_ts]
    volume = volume.loc[:as_of_ts]
    if close.empty:
        raise RuntimeError("下載後無有效收盤價。")

    if mode == "dollar_volume":
        ranked = rank_by_dollar_volume(close, volume, as_of_ts)
    else:
        ranked = rank_by_momentum(close, volume, momentum_days=momentum_days)

    ranked = apply_corporate_event_adjustments(ranked, mode, event_scores)

    us_selected = ranked["ticker"].head(top_n).tolist()
    tw_list = [t.strip().upper() for t in (tw_tickers or []) if t.strip()]
    combined = list(dict.fromkeys(us_selected + tw_list))

    return UniverseBuildResult(
        us_tickers=us_selected,
        tw_tickers=tw_list,
        combined=combined,
        as_of=str(close.index[-1].date()),
        mode=mode,
        candidate_count=len(candidates),
        ranked_table=ranked,
        source=source,
    )


def build_tw_universe(
    as_of: str,
    top_n: int = DEFAULT_TW_UNIVERSE_SIZE,
    mode: UniverseMode = "dollar_volume",
    momentum_days: int = MOMENTUM_2Y_DAYS,
    event_scores: Optional[Dict[str, float]] = None,
    candidate_pool: Optional[Sequence[str]] = None,
    *,
    benchmark: str = "0050.TW",
) -> UniverseBuildResult:
    """Rank Taiwan master pool by TWD dollar volume / momentum. Benchmark ETF excluded."""
    as_of_ts = pd.to_datetime(as_of)
    lookback_calendar = int(MOMENTUM_2Y_DAYS * 1.6) + 60
    start = (as_of_ts - timedelta(days=lookback_calendar)).strftime("%Y-%m-%d")
    end = (as_of_ts + timedelta(days=1)).strftime("%Y-%m-%d")

    bench = (benchmark or "0050.TW").strip().upper()
    if candidate_pool is None:
        candidates = tw_master_pool(exclude_etf=True, exclude_benchmark=bench)
        source = "tw_master"
    else:
        candidates = [
            t.strip().upper()
            for t in candidate_pool
            if is_tw_ticker(t)
            and t.strip().upper() != bench
            and t.strip().upper() not in TW_ETF_EXCLUDE
        ]
        source = "tw_custom"

    if not candidates:
        raise RuntimeError("台股候選池為空。")

    close, volume = download_prices(candidates, start, end)
    close = close.loc[:as_of_ts]
    volume = volume.loc[:as_of_ts]
    if close.empty:
        raise RuntimeError("台股下載後無有效收盤價。")

    if mode == "dollar_volume":
        ranked = rank_by_dollar_volume(close, volume, as_of_ts)
    else:
        ranked = rank_by_momentum(
            close,
            volume,
            momentum_days=momentum_days,
            min_avg_dollar_vol=MIN_AVG_DOLLAR_VOLUME_TW,
        )

    ranked = apply_corporate_event_adjustments(ranked, mode, event_scores)
    tw_selected = ranked["ticker"].head(top_n).tolist()

    return UniverseBuildResult(
        us_tickers=[],
        tw_tickers=tw_selected,
        combined=list(tw_selected),
        as_of=str(close.index[-1].date()),
        mode=mode,
        candidate_count=len(candidates),
        ranked_table=ranked,
        source=source,
    )


def build_momentum_universe(
    as_of: str,
    top_n: int = DEFAULT_UNIVERSE_SIZE,
    tw_tickers: Optional[Sequence[str]] = None,
    momentum_days: int = MOMENTUM_2Y_DAYS,
    event_scores: Optional[Dict[str, float]] = None,
    candidate_pool: Optional[Sequence[str]] = None,
) -> UniverseBuildResult:
    return build_universe(
        as_of=as_of,
        top_n=top_n,
        tw_tickers=tw_tickers,
        mode="momentum",
        momentum_days=momentum_days,
        event_scores=event_scores,
        candidate_pool=candidate_pool,
    )


def backtest_us_pool() -> Tuple[List[str], str]:
    """US tickers for backtests (S&P 500 with master fallback)."""
    return get_candidate_pool("dollar_volume")


def backtest_download_symbols(
    tw_tickers: Optional[Sequence[str]] = None,
    extra: Optional[Sequence[str]] = None,
) -> Tuple[List[str], str]:
    """Prefetch list: S&P 500 + SPY + optional TW / extras."""
    us, source = backtest_us_pool()
    syms = list(dict.fromkeys(list(us) + ["SPY"] + list(tw_tickers or []) + list(extra or [])))
    return syms, source


def build_dollar_volume_universe(
    as_of: str,
    top_n: int = DEFAULT_UNIVERSE_SIZE,
    tw_tickers: Optional[Sequence[str]] = None,
    event_scores: Optional[Dict[str, float]] = None,
    candidate_pool: Optional[Sequence[str]] = None,
) -> UniverseBuildResult:
    return build_universe(
        as_of=as_of,
        top_n=top_n,
        tw_tickers=tw_tickers,
        mode="dollar_volume",
        event_scores=event_scores,
        candidate_pool=candidate_pool,
    )
