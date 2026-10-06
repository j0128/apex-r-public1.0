import pandas as pd

import apex_core as ac
import view_model as vm
from locked_book import LockedBookStore
from test_locked_book import cfg, make_prices, patch_data  # noqa: F401


def test_param_deviation_rdyn_w_uses_validated_standard():
    ok = dict(universe_size=60, momentum_days=120, top_n_limit=10, buffer_zone=0.97)
    assert vm.param_deviations("apex_rdyn_w", **ok) == []
    devs = vm.param_deviations("apex_rdyn_w", **{**ok, "universe_size": 65, "top_n_limit": 12})
    assert len(devs) == 2 and "宇宙數 65" in devs[0]


def test_param_deviation_other_preset_compares_with_itself():
    # Apex-M's own preset is U65 / Top12 — not a deviation for that strategy.
    assert vm.param_deviations(
        "apex_m", universe_size=65, momentum_days=120, top_n_limit=12, buffer_zone=0.97
    ) == []


def test_weight_bar_bounds():
    assert vm.weight_bar(0.10) == "█" * 10
    assert vm.weight_bar(0.0) == "·" * 10
    assert vm.weight_bar(0.5) == "█" * 10  # clamped


def test_sort_key_numeric_aware():
    vals = ["10.5%", "9.2%", "1,200", "abc"]
    assert sorted(vals, key=vm.sort_key) == ["9.2%", "10.5%", "1,200", "abc"]


def test_badges_and_rows(patch_data, tmp_path):  # noqa: F811
    patch_data["df"] = make_prices("2026-10-31")
    store = LockedBookStore(tmp_path)
    res = ac.run_monitor(cfg("2026-10-05"), book_store=store)
    text, level = vm.lock_badge(res)
    assert level == vm.OK and "已鎖定" in text or "剛鎖定" in text
    again = ac.run_monitor(cfg("2026-10-20"), book_store=store)
    assert "月內不變" in vm.lock_badge(again)[0]
    rows = vm.holding_rows(again)
    assert len(rows) == len(again.holdings)
    ticker, values, tag, ratio = rows[0]
    assert ticker in again.locked_weights and tag in {"accel", "brake", "below_ma"}
    assert len(values) == len(vm.VALUE_COLUMNS) and 0 < ratio <= 1.0001
    assert vm.theme_badge(again)[1] == vm.OK
    assert "有效曝險" in vm.exposure_line(again)
    assert all(r[2] == "new" or r[2] in {"accel", "brake", "below_ma"} for r in vm.next_rows(again))
    assert all(r[3] is None and len(r[1]) == len(vm.VALUE_COLUMNS) for r in vm.other_rows(again))


def test_rdyn_w_default_universe_is_60_and_editable():
    from apex_core import ApexConfig
    from strategy_presets import apply_preset, get_preset

    assert get_preset("apex_rdyn_w").universe_size == 60
    assert ApexConfig().universe_size == 60
    base = apply_preset(ApexConfig(), "apex_rdyn_w")
    assert base.universe_size == 60
    # Manual change: switching to custom keeps the user's value.
    from dataclasses import replace

    custom = apply_preset(replace(base, universe_size=75), "apex_custom")
    assert custom.universe_size == 75
    # Apex-M keeps its own U65 preset.
    assert get_preset("apex_m").universe_size == 65


def test_kpi_cards(patch_data, tmp_path):  # noqa: F811
    patch_data["df"] = make_prices("2026-10-31")
    res = ac.run_monitor(cfg("2026-10-05"), book_store=LockedBookStore(tmp_path))
    cards = vm.kpi_cards(res, 1000000.0)
    assert [c["label"] for c in cards][:2] == ["預估總資產 TWD", "本月損益"]
    pnl = res.final_assets_twd - 1000000.0
    assert cards[1]["tone"] == ("up" if pnl > 0 else "down" if pnl < 0 else "text")
    assert cards[1]["value"].endswith("%")
    assert "🟢" not in cards[3]["value"] and "(" not in cards[3]["value"]
    assert cards[5]["value"] == "2026-10"


def test_all_palettes_have_readable_contrast():
    import theme

    for style in theme.STYLES:
        for mode in theme.MODES:
            for red_up in (True, False):
                p = theme.get_palette(style, mode, red_up)
                for fg, bg, need in [
                    (p.text, p.bg, 7), (p.text, p.surface, 7), (p.muted, p.surface, 4.5),
                    (p.muted, p.side, 4.5), (p.accent_fg, p.accent, 4.5),
                    (p.up, p.surface, 4.5), (p.down, p.surface, 4.5),
                    (p.warn, p.surface, 3), (p.danger, p.surface, 3),
                ]:
                    assert theme.contrast(fg, bg) >= need, (style, mode, red_up, fg, bg)
                assert p.up != p.down


def test_red_up_convention_swaps_colors():
    import theme

    tw = theme.get_palette("Notion", "light", red_up=True)
    us = theme.get_palette("Notion", "light", red_up=False)
    assert tw.up == us.down and tw.down == us.up
