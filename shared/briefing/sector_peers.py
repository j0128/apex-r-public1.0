"""產業分組與同業展開。

從 ``data/sector_groups.yaml`` 載入產業 → 標的清單，並提供：
- ``sector_of(ticker)``：查標的所屬產業
- ``peers_in_universe(...)``：找出宇宙池內、與目標標的同產業、且未被排除的同業
"""

from __future__ import annotations

import logging
import sys
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger("apex_r")


def _candidate_data_dirs() -> List[Path]:
    dirs = [Path(__file__).resolve().parent / "data"]
    # PyInstaller 打包後資料被解壓到 sys._MEIPASS/briefing/data
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "briefing" / "data")
    return dirs

# 內建預設，確保 yaml 缺失（如打包環境）時仍可運作。
_DEFAULT_GROUPS: Dict[str, List[str]] = {
    "AI半導體": ["NVDA", "AMD", "INTC", "MU", "MRVL", "AVGO", "QCOM", "TXN", "ARM", "TSM"],
    "半導體設備": ["AMAT", "LRCX", "ASML"],
    "AI伺服器硬體": ["DELL", "SMCI", "IBM"],
    "軟體SaaS": ["MSFT", "ORCL", "CRM", "ADBE", "NOW", "INTU", "PLTR", "SHOP"],
    "資安": ["PANW", "CRWD"],
    "網路媒體": ["GOOGL", "GOOG", "META", "NFLX", "AMZN", "BABA", "PDD", "UBER", "BKNG", "APP", "HOOD", "DIS"],
    "製藥醫療": ["LLY", "MRK", "JNJ", "ABBV", "PFE", "UNH"],
    "金融": ["JPM", "BAC", "GS", "C", "WFC", "V", "MA", "BRK-B"],
    "消費": ["COST", "WMT", "HD", "NKE", "MCD", "SBUX", "PEP", "KO", "PG"],
    "工業能源": ["GE", "GEV", "CAT", "BA", "XOM", "CVX", "LIN"],
    "台股電子": ["0050.TW", "2330.TW", "2317.TW", "2454.TW"],
}


@lru_cache(maxsize=1)
def load_sector_groups() -> Dict[str, List[str]]:
    """載入產業分組（yaml 優先，失敗則用內建預設）。標的一律轉大寫。"""
    groups = _DEFAULT_GROUPS
    for data_dir in _candidate_data_dirs():
        path = data_dir / "sector_groups.yaml"
        try:
            import yaml

            with path.open(encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            if isinstance(loaded, dict) and loaded:
                groups = {str(k): list(v or []) for k, v in loaded.items()}
                break
        except Exception as exc:
            log.warning("sector groups load failed (%s): %s", path, exc)
            continue
    return {sec: [str(t).upper() for t in tickers] for sec, tickers in groups.items()}


@lru_cache(maxsize=1)
def _ticker_to_sector() -> Dict[str, str]:
    """標的 → 主要產業（以第一個出現者為準）。"""
    mapping: Dict[str, str] = {}
    for sector, tickers in load_sector_groups().items():
        for t in tickers:
            mapping.setdefault(t, sector)
    return mapping


def sector_of(ticker: str) -> Optional[str]:
    return _ticker_to_sector().get((ticker or "").upper())


def peers_in_universe(
    target_tickers: List[str],
    universe: List[str],
    exclude: Optional[List[str]] = None,
) -> Dict[str, str]:
    """找出宇宙池內與 target_tickers 同產業的其他標的。

    回傳 ``{ticker: 產業}``（以 dict 保序、去重）。會排除 exclude 中的標的
    以及 target 本身。
    """
    exclude_set = {t.upper() for t in (exclude or [])}
    target_set = {t.upper() for t in target_tickers}
    universe_upper = [t.upper() for t in universe]

    # 目標涵蓋的產業
    sectors = {sector_of(t) for t in target_set}
    sectors.discard(None)

    result: Dict[str, str] = {}
    for t in universe_upper:
        if t in target_set or t in exclude_set:
            continue
        sec = sector_of(t)
        if sec and sec in sectors:
            result.setdefault(t, sec)
    return result
