"""組裝市場簡報文字。

流程：build_watchlist → 抓當日漲跌 → 抓新聞 → 偵測 ±10% 大波動 →
依序輸出【⚡深度分析】【你的標的：下月/雷達】【產業連動】【持倉一行】【總經一行】。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Dict, List, Optional

import pytz

from apex_core import ApexConfig, MonitorResult

from . import market_snapshot, news_watchlist
from .deep_dive import DeepDiveEngine, TemplateDeepDive, detect_big_moves
from .market_snapshot import PriceChange, pct_str
from .watchlist import (
    TIER_HOLDING,
    TIER_NEXT,
    TIER_PEER,
    TIER_RADAR,
    WatchItem,
    Watchlist,
    build_watchlist,
)

TW_TZ = pytz.timezone("Asia/Taipei")
SEP = "━" * 30

ProgressFn = Callable[[str], None]
log = logging.getLogger("apex_r")


def _noop(_: str) -> None:
    pass


def _priority_lookup(wl: Watchlist) -> Dict[str, WatchItem]:
    """ticker → 最相關的 WatchItem（優先：持倉 > 下月 > 雷達 > 同業）。"""
    lookup: Dict[str, WatchItem] = {}
    for group in (wl.peers, wl.radar, wl.next_picks, wl.holdings):
        for it in group:
            lookup[it.ticker] = it  # 後者覆蓋前者 → 高優先在後
    return lookup


def _news_target_tickers(wl: Watchlist) -> List[str]:
    """需要抓新聞的標的：下月 + 雷達 + 同業 + 有警示的持倉。"""
    targets: List[str] = []
    for it in wl.next_picks + wl.radar + wl.peers:
        if it.ticker not in targets:
            targets.append(it.ticker)
    for it in wl.holdings:
        if it.has_alert and it.ticker not in targets:
            targets.append(it.ticker)
    return targets


def build_briefing(
    result: MonitorResult,
    cfg: ApexConfig,
    *,
    deep_dive_threshold_pct: float = 10.0,
    max_deep_dive: int = 2,
    radar_n: int = 5,
    engine: Optional[DeepDiveEngine] = None,
    include_macro: bool = True,
    progress: Optional[ProgressFn] = None,
) -> str:
    say = progress or _noop
    engine = engine or TemplateDeepDive()

    universe = cfg.ticker_list()

    say("分析關注清單…")
    wl = build_watchlist(result, universe, radar_n=radar_n)
    lookup = _priority_lookup(wl)
    all_tickers = wl.all_tickers()

    say("下載當日漲跌…")
    changes = market_snapshot.fetch_daily_changes(all_tickers)

    say("抓取個股新聞…")
    news_targets = _news_target_tickers(wl)
    news_map = news_watchlist.fetch_news_batch(news_targets)

    # 偵測大波動；若命中標的尚未抓新聞，補抓
    big_moves = detect_big_moves(changes, all_tickers, deep_dive_threshold_pct)
    big_moves = big_moves[:max_deep_dive]
    for t in big_moves:
        if t not in news_map:
            news_map[t] = news_watchlist.fetch_news(t)

    say("組裝簡報…")
    return _render(
        result,
        cfg,
        wl,
        lookup,
        changes,
        news_map,
        big_moves,
        engine,
        include_macro,
        deep_dive_threshold_pct,
    )


def _fmt_change(ticker: str, changes: Dict[str, PriceChange]) -> str:
    ch = changes.get(ticker.upper())
    return pct_str(ch.pct if ch else None)


def _render(
    result: MonitorResult,
    cfg: ApexConfig,
    wl: Watchlist,
    lookup: Dict[str, WatchItem],
    changes: Dict[str, PriceChange],
    news_map: Dict[str, List[news_watchlist.NewsItem]],
    big_moves: List[str],
    engine: DeepDiveEngine,
    include_macro: bool,
    deep_dive_threshold_pct: float,
) -> str:
    now = datetime.now(TW_TZ)
    try:
        from strategy_presets import product_name, report_header_cfg

        version_line = report_header_cfg(cfg)
        brand = product_name(cfg.strategy_id)
    except Exception as exc:
        log.warning("briefing header unavailable: %s", exc)
        version_line = "Apex"
        brand = "Apex"

    lines: List[str] = []
    lines.append(f"📊 {brand} 市場簡報 | {now.strftime('%Y-%m-%d %H:%M')} (台灣時間)")
    lines.append(version_line)
    lines.append(
        f"戰略狀態: {result.market_mode} | "
        f"換股鎖定自 {result.rebalance_execution_date.strftime('%Y-%m-%d')}"
    )

    # 【⚡ 大幅波動深度分析】
    if big_moves:
        lines.append("")
        lines.append(SEP)
        lines.append(f"⚡ 大幅波動深度分析（單日 ±{deep_dive_threshold_pct:.0f}%）")
        for t in big_moves:
            item = lookup.get(t) or WatchItem(ticker=t, tier=TIER_RADAR)
            lines.append("")
            lines.append(engine.analyze(item, news_map.get(t, []), changes.get(t.upper())))

    dd_set = set(big_moves)

    # 【新消息 — 你的標的（下月關注）】
    next_items = [it for it in wl.next_picks if it.ticker not in dd_set]
    if next_items:
        lines.append("")
        lines.append(SEP)
        lines.append("【下月關注 — 新聞】")
        # 新標的優先
        next_items.sort(key=lambda it: (not it.is_new))
        for it in next_items:
            lines.append("")
            tag = "👀 " if it.is_new else ""
            lines.append(
                tag + news_watchlist.summarize(it, news_map.get(it.ticker, []), changes.get(it.ticker.upper()))
            )

    # 【雷達候選】
    radar_items = [it for it in wl.radar if it.ticker not in dd_set]
    if radar_items:
        lines.append("")
        lines.append(SEP)
        lines.append("【雷達候選 — 動態】")
        for it in radar_items:
            lines.append("")
            lines.append(
                news_watchlist.summarize(it, news_map.get(it.ticker, []), changes.get(it.ticker.upper()))
            )

    # 【產業連動 — 同業動態】（只顯示有新聞者）
    peer_items = [
        it for it in wl.peers
        if it.ticker not in dd_set and news_map.get(it.ticker)
    ]
    if peer_items:
        lines.append("")
        lines.append(SEP)
        lines.append("【產業連動 — 同業動態】")
        for it in peer_items:
            lines.append("")
            lines.append(
                news_watchlist.summarize(it, news_map.get(it.ticker, []), changes.get(it.ticker.upper()))
            )

    # 【持倉一行】
    if wl.holdings:
        lines.append("")
        lines.append(SEP)
        lines.append("【持倉 — 漲跌】")
        cells = []
        for it in wl.holdings:
            flag = " ⚠️" if it.has_alert else ""
            cells.append(f"{it.ticker} {_fmt_change(it.ticker, changes)}{flag}")
        lines.append(" | ".join(cells))

    # 【總經一行】
    if include_macro:
        macro = market_snapshot.format_macro_line()
        if macro:
            lines.append("")
            lines.append(SEP)
            lines.append(f"【總經】{macro}")

    lines.append("")
    lines.append(f"※ 本簡報由 {brand} 自動彙整，僅供參考，非投資建議。")
    return "\n".join(lines)
