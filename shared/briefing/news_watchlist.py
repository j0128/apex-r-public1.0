"""逐檔新聞抓取（yfinance）與 150–200 字模板摘要。

yfinance 1.4.x 的 ``Ticker.news`` 結構為 ``[{"id":..., "content": {...}}]``，
其中 ``content`` 含 title / summary / pubDate / provider / canonicalUrl。
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional

from .market_snapshot import PriceChange, pct_str
from .watchlist import TIER_HOLDING, TIER_NEXT, TIER_PEER, TIER_RADAR, WatchItem
log = logging.getLogger("apex_r")


@dataclass
class NewsItem:
    ticker: str
    title: str
    summary: str
    publisher: str
    url: str
    published: Optional[datetime]


def _parse_dt(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def _parse_news_entry(ticker: str, entry: dict) -> Optional[NewsItem]:
    content = entry.get("content") if isinstance(entry, dict) else None
    if not isinstance(content, dict):
        # 舊版扁平結構 fallback
        content = entry if isinstance(entry, dict) else {}
    title = (content.get("title") or "").strip()
    if not title:
        return None
    summary = (content.get("summary") or content.get("description") or "").strip()
    provider = ""
    prov = content.get("provider")
    if isinstance(prov, dict):
        provider = (prov.get("displayName") or "").strip()
    url = ""
    for key in ("canonicalUrl", "clickThroughUrl"):
        val = content.get(key)
        if isinstance(val, dict) and val.get("url"):
            url = val["url"]
            break
    published = _parse_dt(content.get("pubDate") or content.get("displayTime"))
    return NewsItem(
        ticker=ticker,
        title=title,
        summary=summary,
        publisher=provider,
        url=url,
        published=published,
    )


def fetch_news(ticker: str, limit: int = 4) -> List[NewsItem]:
    """抓取單一標的新聞；任何錯誤都回傳空清單，不中斷簡報。"""
    import yfinance as yf

    try:
        raw = yf.Ticker(ticker).news or []
    except Exception as exc:
        log.info("news fetch failed for %s: %s", ticker, exc)
        return []

    items: List[NewsItem] = []
    for entry in raw:
        parsed = _parse_news_entry(ticker, entry)
        if parsed:
            items.append(parsed)
        if len(items) >= limit:
            break
    return items


def fetch_news_batch(tickers: List[str], limit: int = 4, max_workers: int = 8) -> Dict[str, List[NewsItem]]:
    """平行抓取多檔新聞。"""
    out: Dict[str, List[NewsItem]] = {}
    if not tickers:
        return out
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_news, t, limit): t for t in tickers}
        for fut in as_completed(futures):
            t = futures[fut]
            try:
                out[t] = fut.result()
            except Exception as exc:
                log.info("news batch failed for %s: %s", t, exc)
                out[t] = []
    return out


def _display_name(ticker: str) -> str:
    return ticker


def _tier_context(item: WatchItem) -> str:
    """一句話說明此標的與你的關聯。"""
    if item.tier == TIER_HOLDING:
        return "此為你目前持倉，本月續抱至換股日。"
    if item.tier == TIER_NEXT:
        if item.is_new:
            return "此為下月換股的新進標的，屬換股前重點觀察對象。"
        return "此為下月續抱標的，動能維持在前段班。"
    if item.tier == TIER_RADAR:
        return "此為雷達候選，尚未進組合，動能若延續可能於下月入選。"
    if item.tier == TIER_PEER:
        conn = "、".join(item.connects) if item.connects else "你的持股"
        return f"你未持有，但與 {conn} 同屬「{item.sector}」，可能產生情緒連動。"
    return ""


def summarize(item: WatchItem, news: List[NewsItem], change: Optional[PriceChange]) -> str:
    """組出 150–200 字左右的段落摘要。無新聞時回傳簡短技術面描述。"""
    name = _display_name(item.ticker)
    move = pct_str(change.pct if change else None)

    tech_bits = []
    if item.dist_ma:
        tech_bits.append(f"距200MA {item.dist_ma:+.0f}%")
    if item.roc_long:
        tech_bits.append(f"長期動能 {item.roc_long:+.0f}%")
    tech = "，".join(tech_bits)

    context = _tier_context(item)

    if not news:
        base = f"{name}（{move}）今日無明顯個股新聞。"
        if tech:
            base += f"技術面 {tech}。"
        base += context
        return base

    head = news[0]
    body = head.summary or head.title
    # 控制長度，避免單則過長
    if len(body) > 240:
        body = body[:238] + "…"

    extra = ""
    if len(news) > 1:
        extra = f"另有 {news[1].publisher or '媒體'} 報導「{news[1].title[:40]}」。"

    parts = [f"{name}（{move}）", body]
    if tech:
        parts.append(f"技術面 {tech}。")
    if extra:
        parts.append(extra)
    parts.append(context)
    return " ".join(p for p in parts if p)
