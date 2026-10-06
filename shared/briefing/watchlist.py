"""從 Apex-R 的 MonitorResult 建立分層關注清單。

- Tier 1 持倉：現有 8 檔（locked_portfolio）
- Tier 2 下月選股：next_month_rows（標記「準備切換」的新標的）
- Tier 3 雷達候選：other_rows 前 N 名（均線之上、動能排名高）
- Tier 4 產業同業：宇宙池內、與 Tier 2/3 同產業、未持有的標的
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from apex_core import MonitorResult

from . import sector_peers

TIER_HOLDING = "holding"
TIER_NEXT = "next"
TIER_RADAR = "radar"
TIER_PEER = "peer"

TIER_LABEL = {
    TIER_HOLDING: "持倉",
    TIER_NEXT: "下月關注",
    TIER_RADAR: "雷達候選",
    TIER_PEER: "產業同業",
}


@dataclass
class WatchItem:
    ticker: str
    tier: str
    status: str = ""            # 狀態描述（續抱 / 準備切換 …）
    dist_ma: float = 0.0        # 距 200MA %
    roc_long: float = 0.0       # 長期動能 %
    roc_short: float = 0.0      # 短期加速 %
    is_new: bool = False        # 下月新進標的
    has_alert: bool = False     # Apex-R 技術警示（跌破均線 / 煞車）
    sector: str = ""            # 產業（Tier4 用）
    connects: List[str] = field(default_factory=list)  # 連動的你的標的（Tier4 用）


@dataclass
class Watchlist:
    holdings: List[WatchItem]
    next_picks: List[WatchItem]
    radar: List[WatchItem]
    peers: List[WatchItem]

    def all_tickers(self) -> List[str]:
        seen: List[str] = []
        for group in (self.holdings, self.next_picks, self.radar, self.peers):
            for it in group:
                if it.ticker not in seen:
                    seen.append(it.ticker)
        return seen


def _alert_from(alert_text: str) -> bool:
    return "⚠️" in (alert_text or "")


def build_watchlist(
    result: MonitorResult,
    universe: List[str],
    radar_n: int = 5,
    peers_per_sector: int = 2,
    max_peers: int = 6,
) -> Watchlist:
    holdings = [
        WatchItem(
            ticker=h.ticker,
            tier=TIER_HOLDING,
            status=h.action,
            dist_ma=h.dist_ma,
            roc_long=h.roc_long,
            roc_short=h.roc_short,
            has_alert=_alert_from(h.alert) or h.dist_ma < 0,
        )
        for h in result.holdings
    ]

    next_picks = [
        WatchItem(
            ticker=r.ticker,
            tier=TIER_NEXT,
            status=r.status,
            dist_ma=r.dist_ma,
            roc_long=r.roc_long,
            roc_short=r.roc_short,
            is_new=r.ticker not in result.locked_portfolio,
            has_alert=_alert_from(r.alert),
        )
        for r in result.next_month_rows
    ]

    radar = [
        WatchItem(
            ticker=r.ticker,
            tier=TIER_RADAR,
            status=r.status,
            dist_ma=r.dist_ma,
            roc_long=r.roc_long,
            roc_short=r.roc_short,
            has_alert=_alert_from(r.alert),
        )
        for r in result.other_rows[:radar_n]
    ]

    # Tier 4：以下月選股 + 雷達為目標，找宇宙池內同產業同業
    focus = [it.ticker for it in next_picks] + [it.ticker for it in radar]
    already = set(
        [it.ticker for it in holdings]
        + [it.ticker for it in next_picks]
        + [it.ticker for it in radar]
    )
    peer_map = sector_peers.peers_in_universe(focus, universe, exclude=list(already))

    # 依產業限量，避免同一產業洗版
    per_sector_count: dict[str, int] = {}
    peers: List[WatchItem] = []
    for ticker, sector in peer_map.items():
        if len(peers) >= max_peers:
            break
        if per_sector_count.get(sector, 0) >= peers_per_sector:
            continue
        per_sector_count[sector] = per_sector_count.get(sector, 0) + 1
        connects = [t for t in focus if sector_peers.sector_of(t) == sector][:4]
        peers.append(
            WatchItem(
                ticker=ticker,
                tier=TIER_PEER,
                status="產業同業",
                sector=sector,
                connects=connects,
            )
        )

    return Watchlist(holdings=holdings, next_picks=next_picks, radar=radar, peers=peers)
