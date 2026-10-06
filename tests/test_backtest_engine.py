import numpy as np
import pandas as pd
import pytest

import backtest_engine as be

TICKERS = [f"S{i:02d}" for i in range(40)]


def make_data(start="2015-01-01", end="2023-12-29", seed=7):
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    cols = TICKERS + ["SPY", "QQQ"]
    drift = rng.uniform(0.0001, 0.0009, len(cols))
    rets = rng.normal(drift, 0.013, (len(idx), len(cols)))
    close = pd.DataFrame(100 * np.cumprod(1 + rets, axis=0), index=idx, columns=cols)
    opn = close.shift(1).bfill() * (1 + rng.normal(0, 0.002, close.shape))
    vol = pd.DataFrame(rng.uniform(1e6, 5e6, close.shape), index=idx, columns=cols)
    return close, opn, vol


@pytest.fixture(scope="module")
def data():
    return make_data()


def test_cost_model_rates():
    cm = be.CostModel()
    assert cm.rates("NVDA") == (0.002, 0.002)
    buy, sell = cm.rates("2330.TW")
    assert buy == pytest.approx(0.001425) and sell == pytest.approx(0.004425)
    assert be.ZERO_COST.rates("2330.TW") == (0.0, 0.0)


def test_simulate_static_plan_matches_hand_calc():
    idx = pd.bdate_range("2022-01-03", periods=60)
    close = pd.DataFrame({"A": np.linspace(100, 130, 60), "B": np.full(60, 50.0)}, index=idx)
    opn = close.copy()
    exe = idx[5]
    res = be.simulate({exe: {"A": 0.5}}, close, opn, be.ZERO_COST, initial=100.0)
    expected = 100 * (0.5 * close["A"].iloc[-1] / opn["A"].loc[exe] + 0.5)
    assert res.equity.iloc[-1] == pytest.approx(expected)
    assert res.equity.index[0] == exe
    # costs reduce the result by roughly buy_rate * invested
    net = be.simulate({exe: {"A": 0.5}}, close, opn, be.CostModel(), initial=100.0)
    assert net.equity.iloc[-1] < res.equity.iloc[-1]
    assert net.cost_paid_pct == pytest.approx(50 * 0.002, rel=1e-6)


def test_universe_has_no_lookahead():
    idx = pd.bdate_range("2016-01-04", "2021-12-31")
    close = pd.DataFrame(100.0, index=idx, columns=["OLD", "NEW"])
    vol = pd.DataFrame({"OLD": 1e6, "NEW": 1.0}, index=idx)
    # NEW trades huge volume only inside cycle year 2019 itself → must not enter 2019's universe.
    vol.loc[vol.index.year == 2019, "NEW"] = 1e9
    cycles = be.build_cycles(vol, close, ["OLD", "NEW"], 1, 2017, 2021)
    assert cycles[2019] == ["OLD"]
    assert cycles[2021] == ["NEW"]  # visible once 2019 is in the past


def test_plans_use_live_rules(data):
    close, opn, vol = data
    end = close.index[-1]
    plan = be.plan_weights(be.SPECS[0], close, opn, vol, TICKERS, end - pd.DateOffset(years=4), end)
    non_empty = [w for w in plan.values() if w]
    assert len(non_empty) > 20
    for w in non_empty:
        assert sum(w.values()) <= 0.97 + 1e-9
        assert max(w.values()) <= 0.10 + 1e-9
        assert len(w) <= 20  # R0 top10 + R3 top10 union
        assert be.BENCHMARK not in w
    plan_m = be.plan_weights(be.SPECS[1], close, opn, vol, TICKERS, end - pd.DateOffset(years=4), end)
    assert all(len(w) <= 12 for w in plan_m.values())


def test_compute_all_theory_beats_net_and_shapes(data):
    close, opn, vol = data
    msgs = []
    df, meta = be.compute_all(close, opn, vol, TICKERS, years=5, progress=msgs.append)
    assert set(df.columns) == set(be.SERIES_LABELS)
    for key in ("apex_r", "apex_m"):
        t, n = df[f"{key}_theory"].dropna(), df[f"{key}_net"].dropna()
        assert len(t) > 500 and t.index[0] == n.index[0]
        assert n.iloc[-1] < t.iloc[-1]  # friction always costs something
        assert meta["stats"][key]["avg_monthly_turnover_pct"] > 0
    assert any("回測" in m for m in msgs)
    assert any("存活者偏差" in n for n in meta["notes"])


def test_slice_rebased_common_start(data):
    close, opn, vol = data
    df, _ = be.compute_all(close, opn, vol, TICKERS, years=5)
    curves = {k: df[k].dropna() for k in df.columns}
    out = be.slice_rebased(curves, 1)
    firsts = {s.index[0] for s in out.values()}
    assert len(firsts) == 1 and all(abs(s.iloc[0] - 100) < 1e-9 for s in out.values())
    assert (out["SPY"].index[-1] - out["SPY"].index[0]).days <= 370
    full = be.slice_rebased(curves, None)
    assert next(iter(full.values())).index[0] >= max(s.index[0] for s in curves.values())


def test_perf_stats_known_series():
    idx = pd.bdate_range("2020-01-01", periods=253)
    eq = pd.Series(100 * 1.001 ** np.arange(253), index=idx)
    s = be.perf_stats(eq)
    assert s["total"] == pytest.approx((1.001 ** 252 - 1) * 100, rel=1e-6)
    assert s["mdd"] == 0 or np.isnan(s["calmar"])
    assert be.perf_stats(eq.iloc[:2])["cagr"] != be.perf_stats(eq.iloc[:2])["cagr"]  # NaN


def test_save_load_roundtrip(tmp_path, data):
    close, opn, vol = data
    df, meta = be.compute_all(close, opn, vol, TICKERS, years=3)
    be.save_results(tmp_path, df, meta)
    got = be.load_results(tmp_path)
    assert got is not None
    df2, meta2 = got
    assert meta2["years"] == 3 and list(df2.columns) == list(df.columns)
    assert df2["SPY"].dropna().iloc[-1] == pytest.approx(df["SPY"].dropna().iloc[-1])
    assert be.load_results(tmp_path / "missing") is None


def test_cancel_stops_backtest(data):
    close, opn, vol = data
    with pytest.raises(InterruptedError):
        be.compute_all(close, opn, vol, TICKERS, years=3, cancel=lambda: True)


def test_extract_adjusts_open_by_adj_ratio():
    idx = pd.bdate_range("2024-01-01", periods=3)
    cols = pd.MultiIndex.from_product([["Close", "Adj Close", "Open", "Volume"], ["A"]])
    raw = pd.DataFrame([[100, 50, 100, 10], [100, 50, 100, 10], [100, 50, 100, 10]], index=idx, columns=cols)
    adj, opn, vol = be._extract(raw)
    assert adj["A"].iloc[0] == 50 and opn["A"].iloc[0] == 50 and vol["A"].iloc[0] == 10
