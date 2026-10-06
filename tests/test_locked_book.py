"""The month-start book never changes inside a month; it is recomputed next month."""

import numpy as np
import pandas as pd
import pytest

import apex_core as ac
from apex_core import ApexConfig
from locked_book import LockedBookStore

NAMES = [f"T{i}" for i in range(14)]


def make_prices(end: str, seed: int = 0, boost: dict | None = None) -> pd.DataFrame:
    idx = pd.bdate_range("2025-01-02", end)
    rng = np.random.default_rng(seed)
    cols = {}
    for i, t in enumerate(NAMES + ["SPY"]):
        drift = 0.0006 + 0.00005 * i
        r = rng.normal(drift, 0.01, len(idx))
        cols[t] = 100 * np.cumprod(1 + r)
    cols["USDTWD=X"] = np.full(len(idx), 31.5)
    df = pd.DataFrame(cols, index=idx)
    for t, (since, mult) in (boost or {}).items():
        df.loc[since:, t] *= mult
    return df


@pytest.fixture
def patch_data(monkeypatch):
    state = {"df": None, "calls": []}

    def fake_download(tickers, query_date, lookback_days=400, **kw):
        state["calls"].append(list(tickers))
        df = state["df"]
        df = df.loc[: pd.Timestamp(query_date)]
        cols = [c for c in df.columns if c in set(tickers) | {"SPY", "USDTWD=X"}]
        return df[cols], df[cols]

    monkeypatch.setattr(ac, "download_market_data", fake_download)
    return state


def cfg(date, names=None, **kw):
    return ApexConfig(query_date=date, user_tickers=",".join(names or NAMES), **kw)


def test_same_month_book_is_frozen_across_dates_and_data_revisions(patch_data, tmp_path):
    store = LockedBookStore(tmp_path)
    patch_data["df"] = make_prices("2026-10-31")
    first = ac.run_monitor(cfg("2026-10-05"), book_store=store)
    assert first.book_lock_status == "new"
    assert first.locked_weights

    # Later in the month: prices moved a lot, a name was added, params edited.
    boosted = make_prices("2026-10-31", boost={"T0": ("2026-10-12", 0.2), "T13": ("2026-10-12", 3.0)})
    patch_data["df"] = boosted
    later = ac.run_monitor(
        cfg("2026-10-28", names=NAMES[1:], top_n_limit=5, universe_size=40), book_store=store
    )
    assert later.book_lock_status == "reused"
    assert later.locked_weights == first.locked_weights
    assert later.locked_portfolio == first.locked_portfolio
    assert later.rebalance_decision_date == first.rebalance_decision_date


def test_locked_tickers_outside_current_universe_are_still_priced(patch_data, tmp_path):
    store = LockedBookStore(tmp_path)
    patch_data["df"] = make_prices("2026-10-31")
    first = ac.run_monitor(cfg("2026-10-05"), book_store=store)
    dropped = first.locked_portfolio[0]
    smaller = [n for n in NAMES if n != dropped]
    again = ac.run_monitor(cfg("2026-10-20", names=smaller), book_store=store)
    assert dropped in again.locked_weights
    assert {h.ticker for h in again.holdings} >= {dropped}


def test_next_month_recomputes_and_writes_new_lock(patch_data, tmp_path):
    store = LockedBookStore(tmp_path)
    patch_data["df"] = make_prices("2026-11-30", boost={"T0": ("2026-10-26", 4.0)})
    oct_res = ac.run_monitor(cfg("2026-10-20"), book_store=store)
    nov_res = ac.run_monitor(cfg("2026-11-10"), book_store=store)
    assert oct_res.book_lock_status == "new" and nov_res.book_lock_status == "new"
    assert nov_res.rebalance_execution_date.month == 11
    assert len(list(tmp_path.glob("book_*.json"))) == 2
    # October's lock is untouched by November's run.
    assert ac.run_monitor(cfg("2026-10-27"), book_store=store).locked_weights == oct_res.locked_weights


def test_relock_overwrites_only_when_explicit(patch_data, tmp_path):
    store = LockedBookStore(tmp_path)
    patch_data["df"] = make_prices("2026-10-31")
    ac.run_monitor(cfg("2026-10-05"), book_store=store)
    res = ac.run_monitor(cfg("2026-10-06", names=NAMES[:8], top_n_limit=4), book_store=store, relock=True)
    assert res.book_lock_status == "relocked"
    assert len(res.locked_weights) <= 4


def test_corrupt_lock_file_is_an_error_not_a_silent_repick(patch_data, tmp_path):
    store = LockedBookStore(tmp_path)
    patch_data["df"] = make_prices("2026-10-31")
    ac.run_monitor(cfg("2026-10-05"), book_store=store)
    (next(tmp_path.glob("book_*.json"))).write_text("{not json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="鎖定檔"):
        ac.run_monitor(cfg("2026-10-06"), book_store=store)


def test_no_store_keeps_legacy_behavior(patch_data):
    patch_data["df"] = make_prices("2026-10-31")
    res = ac.run_monitor(cfg("2026-10-05"))
    assert res.book_lock_status == ""


def test_report_mentions_lock(patch_data, tmp_path):
    patch_data["df"] = make_prices("2026-10-31")
    res = ac.run_monitor(cfg("2026-10-05"), book_store=LockedBookStore(tmp_path))
    text = ac.format_report(res, strategy_id="apex_rdyn_w", cfg=cfg("2026-10-05"))
    assert "已於" in text and "鎖定" in text
