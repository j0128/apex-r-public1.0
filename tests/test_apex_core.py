import numpy as np
import pandas as pd
import pytest

import apex_core as ac
from apex_core import ApexConfig


def s(d):
    return pd.Series(d, dtype=float)


# ---- finalize_weights ----------------------------------------------------

def test_finalize_weights_sums_to_target_and_respects_cap():
    tickers = list("ABCDEFGHIJ")
    vol = s({t: 0.2 + 0.05 * i for i, t in enumerate(tickers)})
    w = ac.finalize_weights(tickers, vol, 0.97, 0.10)
    assert sum(w.values()) == pytest.approx(0.97, abs=1e-6)
    assert max(w.values()) <= 0.10 + 1e-9


def test_finalize_weights_inverse_vol_ordering():
    w = ac.finalize_weights(["A", "B"], s({"A": 0.1, "B": 0.4}), 0.9, 1.0)
    assert w["A"] > w["B"]


def test_finalize_weights_empty_and_zero_target():
    assert ac.finalize_weights([], s({}), 0.97, 0.1) == {}
    assert ac.finalize_weights(["A"], s({"A": 0.2}), 0.0, 0.1) == {}


def test_finalize_weights_missing_vol_falls_back_to_equal():
    w = ac.finalize_weights(["A", "B"], s({}), 0.6, 1.0)
    assert w["A"] == pytest.approx(w["B"])


# ---- momentum / selection -----------------------------------------------

def test_momentum_score_is_risk_adjusted():
    mom, vol = s({"A": 1.0}), s({"A": 0.5})
    assert ac.momentum_score("A", mom, vol) == pytest.approx(2.0)
    assert ac.momentum_score("Z", mom, vol) == -999.0


def test_select_top_n_filters_below_200ma_and_ranks_by_roc_over_vol():
    universe = ["A", "B", "C", "D"]
    prices = s({"A": 110, "B": 90, "C": 120, "D": 100})
    ma = s({"A": 100, "B": 100, "C": 100, "D": 100})
    mom = s({"A": 0.5, "B": 9.0, "C": 0.5, "D": 0.4})
    vol = s({"A": 0.5, "B": 0.1, "C": 0.25, "D": 0.2})
    # B is below its MA -> excluded despite top raw momentum.
    # scores: A=1.0, C=2.0, D=2.0 -> C/D tie, A last
    picks = ac.select_top_n(universe, prices, ma, mom, vol, 2)
    assert "B" not in picks
    assert len(picks) == 2 and "A" not in picks


def test_select_top_n_entry_20d_pos_only():
    universe = ["A", "B"]
    prices, ma = s({"A": 110, "B": 110}), s({"A": 100, "B": 100})
    mom, vol = s({"A": 1, "B": 2}), s({"A": 1, "B": 1})
    roc_short = s({"A": 0.05, "B": -0.05})
    picks = ac.select_top_n(universe, prices, ma, mom, vol, 5,
                            entry_20d_pos_only=True, roc_short=roc_short)
    assert picks == ["A"]


# ---- regime --------------------------------------------------------------

@pytest.mark.parametrize(
    "spy_p,spy_ma,breadth,expected",
    [
        (110, 100, 0.6, "offensive_full"),
        (110, 100, 0.4, "offensive_half"),
        (90, 100, 0.9, "bunker"),
        (np.nan, 100, 0.9, "offensive_half"),
    ],
)
def test_detect_regime_mode(spy_p, spy_ma, breadth, expected):
    assert ac.detect_regime_mode(spy_p, spy_ma, breadth, 0.5) == expected


def test_regime_w_r3_mapping():
    assert ac.REGIME_W_R3 == {"offensive_full": 0.25, "offensive_half": 0.50, "bunker": 0.75}


def test_blend_weights_sum_preserved():
    w0, w3 = {"A": 0.5, "B": 0.47}, {"B": 0.5, "C": 0.47}
    for w_r3 in ac.REGIME_W_R3.values():
        b = ac.blend_strategy_weights(w0, w3, w_r3)
        assert sum(b.values()) == pytest.approx(0.97)


def test_format_rdyn_blend_label():
    assert ac.format_rdyn_blend_label(0.25) == "R0 75% / R3 25%"


def test_compute_breadth():
    prices, ma = s({"A": 2, "B": 1, "C": 3}), s({"A": 1, "B": 2, "C": 1})
    assert ac.compute_breadth(["A", "B", "C"], prices, ma) == pytest.approx(2 / 3)
    assert ac.compute_breadth(["X"], prices, ma) == 0.0


# ---- build_rdyn_weights --------------------------------------------------

def _market(n=14):
    tickers = [f"T{i}" for i in range(n)]
    prices = s({**{t: 110 for t in tickers}, "SPY": 110})
    ma = s({**{t: 100 for t in tickers}, "SPY": 100})
    mom = s({**{t: 0.5 + 0.05 * i for i, t in enumerate(tickers)}, "SPY": 0.2})
    vol = s({**{t: 0.3 for t in tickers}, "SPY": 0.15})
    rs = s({**{t: 0.02 for t in tickers}, "SPY": 0.01})
    return tickers, prices, ma, mom, vol, rs


def test_build_rdyn_weights_full_regime():
    tickers, prices, ma, mom, vol, rs = _market()
    cfg = ApexConfig()
    w, mode, w_r3 = ac.build_rdyn_weights(cfg, tickers + ["SPY"], prices, ma, mom, vol, rs, benchmark="SPY")
    assert mode == "offensive_full" and w_r3 == 0.25
    assert "SPY" not in w
    assert len(w) <= cfg.top_n_limit
    assert sum(w.values()) == pytest.approx(cfg.buffer_zone, abs=1e-6)
    assert max(w.values()) <= cfg.max_weight_cap + 1e-9


def test_build_rdyn_weights_bunker_stays_invested():
    tickers, prices, ma, mom, vol, rs = _market()
    prices["SPY"] = 90  # below 200MA
    cfg = ApexConfig()
    w, mode, w_r3 = ac.build_rdyn_weights(cfg, tickers + ["SPY"], prices, ma, mom, vol, rs, benchmark="SPY")
    assert mode == "bunker" and w_r3 == 0.75
    assert sum(w.values()) == pytest.approx(cfg.buffer_zone, abs=1e-6)


def test_build_rdyn_weights_nothing_eligible():
    tickers, prices, ma, mom, vol, rs = _market(3)
    prices[tickers] = 50  # all below MA
    w, _, _ = ac.build_rdyn_weights(ApexConfig(), tickers + ["SPY"], prices, ma, mom, vol, rs, benchmark="SPY")
    assert w == {}


# ---- misc ----------------------------------------------------------------

def test_find_month_rebalance_dates():
    idx = pd.to_datetime(["2026-05-28", "2026-05-29", "2026-06-01", "2026-06-02"])
    df = pd.DataFrame({"A": range(4)}, index=idx)
    prev, first = ac.find_month_rebalance_dates(df)
    assert prev == pd.Timestamp("2026-05-29") and first == pd.Timestamp("2026-06-01")


def test_is_rdyn_w_cfg():
    assert ac.is_rdyn_w_cfg(ApexConfig(strategy_id="apex_rdyn_w"))
    assert not ac.is_rdyn_w_cfg(ApexConfig(strategy_id="apex_m"))
