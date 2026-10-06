"""Month-start locked book: tickers + weights frozen for the whole month.

Rule (owner decision): the portfolio and weights chosen at a month's rebalance
are written down once and never change on any query date inside that month.
They are recomputed only when the next month's rebalance arrives (new key).

The key is (strategy_id, market, YYYY-MM) of the rebalance *execution* month.
Parameters (universe size, Top N, ...) are stored for audit but are NOT part of
the key, so editing parameters or refreshing the universe mid-month cannot
silently change the book.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

log = logging.getLogger("apex_r")

SCHEMA_VERSION = 1


@dataclass
class LockedBook:
    strategy_id: str
    market: str
    month: str  # YYYY-MM of the rebalance execution date
    decision_date: str
    execution_date: str
    locked_at: str
    weights: Dict[str, float]
    params: Dict[str, object]


def month_key(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s or "x")


class LockedBookStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def _path(self, strategy_id: str, market: str, month: str) -> Path:
        return self.root / f"book_{_safe(strategy_id)}_{_safe(market)}_{month}.json"

    def load(self, strategy_id: str, market: str, month: str) -> Optional[LockedBook]:
        path = self._path(strategy_id, market, month)
        if not path.exists():
            return None
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            weights = {str(t): float(w) for t, w in raw["weights"].items()}
            if not weights:
                raise ValueError("empty weights")
            return LockedBook(
                strategy_id=raw["strategy_id"],
                market=raw["market"],
                month=raw["month"],
                decision_date=raw["decision_date"],
                execution_date=raw["execution_date"],
                locked_at=raw["locked_at"],
                weights=weights,
                params=dict(raw.get("params", {})),
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # Never silently re-pick: a damaged lock file must be noticed.
            raise RuntimeError(
                f"本月鎖定檔 {path} 無法讀取（{exc}）。請修復或刪除該檔後重新執行；"
                "刪除會以當月月初資料重新鎖定。"
            ) from exc

    def save(self, book: LockedBook) -> Path:
        path = self._path(book.strategy_id, book.market, book.month)
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "strategy_id": book.strategy_id,
            "market": book.market,
            "month": book.month,
            "decision_date": book.decision_date,
            "execution_date": book.execution_date,
            "locked_at": book.locked_at,
            "weights": book.weights,
            "params": book.params,
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
        return path

    def candidate_tickers(self, strategy_id: str, market: str, query_date: str) -> List[str]:
        """Tickers of any lock that could apply to this query (query month or the one before).

        Used to make sure locked names are downloaded even if the universe
        changed since the book was locked.
        """
        q = pd.Timestamp(query_date)
        months = {month_key(q), month_key(q - pd.DateOffset(months=1))}
        out: List[str] = []
        for m in sorted(months):
            try:
                book = self.load(strategy_id, market, m)
            except RuntimeError:
                continue  # surfaced later, when the month is actually resolved
            if book:
                out.extend(book.weights)
        return list(dict.fromkeys(out))


def new_book(
    *,
    strategy_id: str,
    market: str,
    decision_date,
    execution_date,
    weights: Dict[str, float],
    params: Dict[str, object],
) -> LockedBook:
    return LockedBook(
        strategy_id=strategy_id,
        market=market,
        month=month_key(execution_date),
        decision_date=str(pd.Timestamp(decision_date).date()),
        execution_date=str(pd.Timestamp(execution_date).date()),
        locked_at=datetime.now().isoformat(timespec="seconds"),
        weights={t: float(w) for t, w in weights.items()},
        params=params,
    )
