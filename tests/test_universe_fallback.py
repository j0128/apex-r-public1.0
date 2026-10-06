import logging

import universe_builder as ub


def test_candidate_pool_falls_back_and_warns(monkeypatch, caplog):
    def boom():
        raise RuntimeError("offline")

    monkeypatch.setattr(ub, "fetch_sp500_tickers", boom)
    monkeypatch.setattr(ub, "master_pool", lambda: ["AAA", "BBB"])
    with caplog.at_level(logging.WARNING, logger="apex_r"):
        pool, source = ub.get_candidate_pool("dollar_volume")
    assert (pool, source) == (["AAA", "BBB"], "master_fallback")
    assert "offline" in caplog.text
