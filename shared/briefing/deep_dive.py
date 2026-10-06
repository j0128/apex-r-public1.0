"""單日大波動（±10%）深度分析。

- ``detect_big_moves``：從當日漲跌找出超過門檻的標的
- ``TemplateDeepDive``：免費的模板版分析（約 400 字），結構為
  發生什麼 / 市場反應 / 技術面 / 對你的意涵 / 後續觀察
- ``DeepDiveEngine``：介面協定，日後可換成 LLM 版

模板版利用 yfinance 新聞的 summary 欄位作為「原因」，搭配 Apex-R 技術數據。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Protocol

from .market_snapshot import PriceChange, pct_str
from .news_watchlist import NewsItem
from .watchlist import TIER_LABEL, TIER_PEER, WatchItem


def detect_big_moves(
    changes: Dict[str, PriceChange],
    tickers: List[str],
    threshold_pct: float = 10.0,
) -> List[str]:
    """回傳漲跌絕對值 >= 門檻的標的，依波動幅度由大到小排序。"""
    hits = []
    for t in tickers:
        ch = changes.get(t.upper())
        if ch and abs(ch.pct) >= threshold_pct:
            hits.append((t.upper(), abs(ch.pct)))
    hits.sort(key=lambda x: x[1], reverse=True)
    return [t for t, _ in hits]


class DeepDiveEngine(Protocol):
    def analyze(
        self,
        item: WatchItem,
        news: List[NewsItem],
        change: Optional[PriceChange],
    ) -> str:
        ...


class TemplateDeepDive:
    """規則/模板版深度分析（免費，無需 API key）。"""

    def analyze(
        self,
        item: WatchItem,
        news: List[NewsItem],
        change: Optional[PriceChange],
    ) -> str:
        pct = change.pct if change else 0.0
        direction = "大漲" if pct >= 0 else "重挫"
        move = pct_str(pct)
        tier_label = TIER_LABEL.get(item.tier, "")
        if item.tier == TIER_PEER and item.sector:
            tag = f"{item.sector} · 未持有"
        else:
            tag = tier_label

        # 〔發生什麼〕
        if news:
            head = news[0]
            reason = head.summary or head.title
            if len(reason) > 260:
                reason = reason[:258] + "…"
            src = head.publisher or "媒體"
            what = f"{item.ticker} 單日{direction} {move}。{src}報導：{reason}"
        else:
            what = (
                f"{item.ticker} 單日{direction} {move}，"
                f"但目前尚無明確個股新聞對應，可能為板塊連動或資金面因素。"
            )

        # 〔技術面〕
        tech_bits = []
        if item.dist_ma:
            side = "之上" if item.dist_ma >= 0 else "之下"
            tech_bits.append(f"距 200MA {item.dist_ma:+.0f}%（位於均線{side}）")
        if item.roc_long:
            tech_bits.append(f"長期動能 {item.roc_long:+.0f}%")
        if item.roc_short:
            tech_bits.append(f"短期加速 {item.roc_short:+.0f}%")
        tech = "，".join(tech_bits) if tech_bits else "技術數據不足"

        # 〔對你的意涵〕
        if item.tier == TIER_PEER:
            conn = "、".join(item.connects) if item.connects else "你的持股"
            meaning = (
                f"你未直接持有，但與 {conn} 同屬「{item.sector}」，"
                f"此波動可能牽動同業情緒；本月策略維持續抱，不因單日波動調整。"
            )
        elif item.tier == "holding":
            meaning = "此為你的持倉；策略為月內續抱制，除非跌破均線觸發警示，否則續抱至換股日。"
        elif item.tier == "next":
            meaning = "此為下月換股相關標的，波動會直接影響下月配置決策，值得優先追蹤。"
        else:
            meaning = "此為雷達候選；波動放大代表關注度上升，留意是否具備下月入選動能。"

        # 〔後續觀察〕
        if pct >= 0:
            watch = "後續觀察：漲勢能否延續、量能是否跟上、以及是否帶動同產業其他標的。"
        else:
            watch = "後續觀察：是否守住 200MA、有無進一步利空發酵、以及同業是否跟跌。"

        return (
            f"⚡ {item.ticker}（{tag}）\n"
            f"〔發生什麼〕{what}\n"
            f"〔技術面〕{tech}。\n"
            f"〔對你的意涵〕{meaning}\n"
            f"{watch}"
        )
