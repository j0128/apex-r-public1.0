"""Apex-R 市場簡報模組。

以 Apex-R 的 MonitorResult 為核心，產生「以投資標的為中心」的市場簡報：
- 關注清單分層：持倉 / 下月選股 / 雷達候選 / 產業同業
- 逐檔新聞摘要（yfinance）
- 單日大波動（±10%）升級為深度分析

對外主要入口：``compose.build_briefing``。
"""

from __future__ import annotations

from .compose import build_briefing

__all__ = ["build_briefing"]
