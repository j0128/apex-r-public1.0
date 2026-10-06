import numpy as np
import pandas as pd
import pytest

pytest.importorskip("matplotlib")
from matplotlib.backends.backend_agg import FigureCanvasAgg  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

import charts  # noqa: E402
import theme  # noqa: E402


def fig(w=6, h=3):
    f = Figure(figsize=(w, h), dpi=80)
    FigureCanvasAgg(f)
    return f


def series(n=200):
    idx = pd.bdate_range("2026-01-01", periods=n)
    c = pd.Series(100 + np.cumsum(np.random.default_rng(3).normal(0.2, 1, n)), index=idx)
    return c, c.shift(1).bfill(), c.rolling(50).mean(), idx


@pytest.mark.parametrize("style", theme.STYLES)
@pytest.mark.parametrize("mode", theme.MODES)
def test_weights_chart_renders_all_palettes(style, mode):
    f = fig(4, 3)
    charts.WeightsChart(f).render(theme.get_palette(style, mode), {f"T{i}": 0.09 for i in range(10)})
    f.canvas.draw()
    texts = [t.get_text() for t in f.findobj(match=lambda a: hasattr(a, "get_text"))]
    assert "90%" in texts and "現金" in texts


def test_weights_chart_empty():
    f = fig(4, 3)
    charts.WeightsChart(f).render(theme.get_palette("Notion", "light"), {})
    f.canvas.draw()


def test_stock_chart_open_close_toggle_and_ma():
    c, o, ma, idx = series()
    p = theme.get_palette("Bloomberg", "dark")
    f = fig()
    ch = charts.StockChart(f)
    ch.render(p, "NVDA", c, o, ma, field="close", buy_date=idx[-15])
    assert np.allclose(ch._y, c.values)
    n_lines_with_ma = len(ch.ax.lines)
    ch.render(p, "NVDA", c, o, ma, field="open", buy_date=idx[-15])
    assert np.allclose(ch._y, o.values)
    ch.render(p, "NVDA", c, o, ma, field="close", show_ma=False, buy_date=idx[-15])
    assert len(ch.ax.lines) == n_lines_with_ma - 1
    f.canvas.draw()


def test_stock_chart_without_buy_date_or_data():
    c, o, ma, idx = series()
    p = theme.get_palette("Notion", "dark")
    ch = charts.StockChart(fig())
    ch.render(p, "AAPL", c, o, ma, buy_date=None)  # non-locked ticker
    ch.render(p, None, None, None, None)  # nothing selected
    assert ch._x is None


def test_hover_snaps_to_nearest_day_and_hides():
    import matplotlib.dates as mdates

    c, o, ma, idx = series()
    ch = charts.StockChart(fig())
    ch.render(theme.get_palette("Bloomberg", "light"), "X", c, o, ma)

    class Ev:
        pass

    e = Ev()
    e.inaxes, e.xdata = ch.ax, float(mdates.date2num(idx[50])) + 0.2
    assert ch.on_move(e) is True
    assert idx[50].strftime("%Y-%m-%d") in ch._tip.get_text()
    e.inaxes = None
    assert ch.on_move(e) is True  # hides
    assert ch.on_move(e) is False  # already hidden


def _curves():
    idx = pd.bdate_range("2021-01-01", periods=300)
    rng = np.random.default_rng(5)
    return {
        k: pd.Series(100 * np.cumprod(1 + rng.normal(0.0005, 0.01, 300)), index=idx)
        for k in ("apex_r_theory", "apex_r_net", "SPY")
    }


@pytest.mark.parametrize("style", theme.STYLES)
@pytest.mark.parametrize("mode", theme.MODES)
def test_curves_chart_renders_and_styles(style, mode):
    p = theme.get_palette(style, mode)
    f = fig(8, 4)
    ch = charts.CurvesChart(f)
    ch.render(p, _curves(), log=True)
    f.canvas.draw()
    assert len(ch.ax.lines) >= 3  # 3 series (+ baseline + hover vline)
    assert charts.curve_style(p, "apex_r_theory")["linestyle"] != charts.curve_style(p, "apex_r_net")["linestyle"]
    assert charts.curve_style(p, "apex_r_net")["color"] == charts.curve_style(p, "apex_r_theory")["color"]


def test_curves_chart_empty_message_and_hover():
    import matplotlib.dates as mdates

    p = theme.get_palette("Bloomberg", "dark")
    ch = charts.CurvesChart(fig(8, 4))
    ch.render(p, {}, message="尚未計算")
    assert ch.on_move(type("E", (), {"inaxes": None, "xdata": None})()) is False
    curves = _curves()
    ch.render(p, curves)
    day = curves["SPY"].index[120]

    class Ev:
        inaxes, xdata = ch.ax, float(mdates.date2num(day))

    assert ch.on_move(Ev()) is True
    text = ch._tip.get_text()
    assert f"{day:%Y-%m-%d}" in text and "Apex-R 理論值" in text and "SPY" in text
