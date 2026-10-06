"""Allocation spreadsheets: weights filled, amounts left for humans.

CSV opens in Excel / Google Sheets. Fill total capital, then amounts via formula.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from apex_core import ApexConfig, MonitorResult
from strategy_presets import product_name, report_header_cfg


def _readme_lines(tag: str, header: str) -> List[str]:
    return [
        f"# {header}",
        f"# tag={tag}",
        "# 用法（Excel／Google 試算表）：",
        "# 1. 在「總投資金額_TWD」列的 amount_twd 欄填入你的總資金（整數即可）。",
        "# 2. 各標的列的 amount_twd 已預填公式：=總資金 * weight_pct / 100",
        "#    （Excel 開啟後若顯示文字，選該欄 → 資料/文字轉欄位 或重新輸入公式。）",
        "# 3. 權重已由系統給定；勿改 weight_pct 除非你要覆核覆蓋。",
        "#",
    ]


def _write_csv(path: Path, fieldnames: Sequence[str], rows: List[dict], preamble: List[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        for line in preamble:
            f.write(line + "\n")
        writer = csv.DictWriter(f, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def write_engine_allocation_csvs(
    result: MonitorResult,
    cfg: ApexConfig,
    out_dir: Path,
    *,
    tag: str,
    stamp: str,
) -> List[Path]:
    """Write holdings + next-month CSVs for one engine (apex_m / apex_r)."""
    out_dir = Path(out_dir)
    brand = product_name(cfg.strategy_id)
    header = report_header_cfg(cfg)
    paths: List[Path] = []

    # --- holdings ---
    hold_fields = [
        "row_type",
        "ticker",
        "weight_pct",
        "roc_long_pct",
        "roc_20_pct",
        "dist_ma_pct",
        "action",
        "amount_twd",
    ]
    hold_rows: List[dict] = [
        {
            "row_type": "TOTAL_CAPITAL",
            "ticker": "",
            "weight_pct": "",
            "roc_long_pct": "",
            "roc_20_pct": "",
            "dist_ma_pct": "",
            "action": "在此列 amount_twd 填總投資金額",
            "amount_twd": "",  # human fills; Excel ref as $H$2 if header is row 1 after comments
        }
    ]
    # Data rows start after preamble + header + TOTAL row.
    # For formula simplicity: use weight_pct column and instruct user to set capital in H2
    # after opening (comments don't count as Excel rows the same way). Better approach:
    # put TOTAL as first data row with a clear label; formulas use absolute ref to that cell.
    #
    # Excel row mapping when opened:
    # - Comment lines starting with # may be imported as rows in some tools.
    # Safer: separate readme file + clean CSV without # lines for formulas.
    hold_data_start = 3  # row 1 header, row 2 TOTAL, row 3 first ticker (1-based Excel)
    for i, h in enumerate(result.holdings):
        wt = result.locked_weights.get(h.ticker, 0.0) * 100
        excel_row = hold_data_start + i
        hold_rows.append(
            {
                "row_type": "HOLDING",
                "ticker": h.ticker,
                "weight_pct": f"{wt:.2f}",
                "roc_long_pct": f"{h.roc_long:.1f}",
                "roc_20_pct": f"{h.roc_short:.1f}",
                "dist_ma_pct": f"{h.dist_ma:.1f}",
                "action": f"{h.alert} {h.action}",
                # H2 = TOTAL amount; C = weight_pct column
                "amount_twd": f"=$H$2*C{excel_row}/100",
            }
        )

    hold_path = out_dir / f"alloc_{tag}_{stamp}_holdings.csv"
    # Clean CSV (no # preamble) so Excel row numbers match formulas; readme separate
    _write_csv(hold_path, hold_fields, hold_rows, preamble=[])
    paths.append(hold_path)

    # --- next month ---
    next_fields = [
        "row_type",
        "ticker",
        "weight_pct",
        "status",
        "roc_long_pct",
        "roc_20_pct",
        "dist_ma_pct",
        "amount_twd",
    ]
    next_rows: List[dict] = [
        {
            "row_type": "TOTAL_CAPITAL",
            "ticker": "",
            "weight_pct": "",
            "status": "在此列 amount_twd 填總投資金額（含預計加碼）",
            "roc_long_pct": "",
            "roc_20_pct": "",
            "dist_ma_pct": "",
            "amount_twd": "",
        }
    ]
    next_data_start = 3
    for i, r in enumerate(result.next_month_rows):
        excel_row = next_data_start + i
        next_rows.append(
            {
                "row_type": "NEXT",
                "ticker": r.ticker,
                "weight_pct": f"{r.est_weight * 100:.2f}",
                "status": f"{r.status} {r.alert}",
                "roc_long_pct": f"{r.roc_long:.1f}",
                "roc_20_pct": f"{r.roc_short:.1f}",
                "dist_ma_pct": f"{r.dist_ma:.1f}",
                "amount_twd": f"=$H$2*C{excel_row}/100",
            }
        )

    next_path = out_dir / f"alloc_{tag}_{stamp}_next.csv"
    _write_csv(next_path, next_fields, next_rows, preamble=[])
    paths.append(next_path)

    readme = out_dir / f"alloc_{tag}_{stamp}_readme.txt"
    readme.write_text(
        "\n".join(
            _readme_lines(tag, f"{brand} 配置試算表")
            + [
                f"策略：{header}",
                f"查詢日：{cfg.query_date}",
                "",
                f"檔案：{hold_path.name}（本月鎖定）",
                f"檔案：{next_path.name}（下月預演）",
                "",
                "Excel 操作：",
                "1. 開啟 CSV（UTF-8）。",
                "2. 第 2 列 row_type=TOTAL_CAPITAL，在 amount_twd 欄（H 欄）填入總資金。",
                "3. 下方各列 amount_twd 為公式 =$H$2*權重%/100，填完總額即自動算出。",
                "4. 若公式顯示為文字：選取金額欄 → 開始編輯任一公式格按 Enter，或「文字轉欄位」。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    paths.append(readme)
    return paths


def write_committee_next_csv(
    m_result: MonitorResult,
    r_result: MonitorResult,
    out_dir: Path,
    *,
    stamp: str,
) -> List[Path]:
    """Committee next-month sheet using Apex-M weights; flag presence in Apex-R."""
    out_dir = Path(out_dir)
    r_next = {t.upper() for t in r_result.next_month_picks}
    fields = [
        "row_type",
        "ticker",
        "weight_pct_apex_m",
        "in_apex_r",
        "status",
        "roc_long_pct",
        "roc_20_pct",
        "dist_ma_pct",
        "amount_twd",
    ]
    rows: List[dict] = [
        {
            "row_type": "TOTAL_CAPITAL",
            "ticker": "",
            "weight_pct_apex_m": "",
            "in_apex_r": "",
            "status": "基準執行=Apex-M；在此列 amount_twd 填總投資金額",
            "roc_long_pct": "",
            "roc_20_pct": "",
            "dist_ma_pct": "",
            "amount_twd": "",
        }
    ]
    data_start = 3
    for i, r in enumerate(m_result.next_month_rows):
        excel_row = data_start + i
        rows.append(
            {
                "row_type": "NEXT",
                "ticker": r.ticker,
                "weight_pct_apex_m": f"{r.est_weight * 100:.2f}",
                "in_apex_r": "Y" if r.ticker.upper() in r_next else "N",
                "status": f"{r.status} {r.alert}",
                "roc_long_pct": f"{r.roc_long:.1f}",
                "roc_20_pct": f"{r.roc_short:.1f}",
                "dist_ma_pct": f"{r.dist_ma:.1f}",
                # C = weight_pct_apex_m
                "amount_twd": f"=$I$2*C{excel_row}/100",
            }
        )

    path = out_dir / f"alloc_committee_{stamp}_next.csv"
    _write_csv(path, fields, rows, preamble=[])
    readme = out_dir / f"alloc_committee_{stamp}_readme.txt"
    readme.write_text(
        "\n".join(
            [
                "# AI 投資委員會 — 下月配置試算（基準=Apex-M）",
                "# 1. 第 2 列 amount_twd（I 欄）填總投資金額。",
                "# 2. 各列公式 =$I$2 * weight_pct_apex_m / 100。",
                "# 3. in_apex_r=Y 表示衛星委員下月名單也有此標的（共識）。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return [path, readme]


def write_committee_tw_next_csv(
    m_result: MonitorResult,
    r_result: MonitorResult,
    out_dir: Path,
    *,
    stamp: str,
    anchor_ticker: str = "0050.TW",
) -> List[Path]:
    """台股委員會：0050 錨列 + Apex-TW R0 權重；in_rdyn 標共識。"""
    out_dir = Path(out_dir)
    r_next = {t.upper() for t in r_result.next_month_picks}
    fields = [
        "row_type",
        "ticker",
        "sleeve",
        "weight_pct_r0",
        "in_rdyn",
        "status",
        "roc_long_pct",
        "roc_20_pct",
        "dist_ma_pct",
        "amount_twd",
    ]
    rows: List[dict] = [
        {
            "row_type": "TOTAL_CAPITAL",
            "ticker": "",
            "sleeve": "",
            "weight_pct_r0": "",
            "in_rdyn": "",
            "status": "基準執行=動能袖 Apex-TW R0；J 欄填總投資金額",
            "roc_long_pct": "",
            "roc_20_pct": "",
            "dist_ma_pct": "",
            "amount_twd": "",
        },
        {
            "row_type": "ANCHOR",
            "ticker": anchor_ticker,
            "sleeve": "core",
            "weight_pct_r0": "",  # human fills sleeve % of total
            "in_rdyn": "Y",
            "status": "錨定袖：請在 weight_pct_r0 填 0050 佔總資金％（例 40）",
            "roc_long_pct": "",
            "roc_20_pct": "",
            "dist_ma_pct": "",
            "amount_twd": "=$J$2*D3/100",
        },
    ]
    data_start = 4  # row1 header, row2 TOTAL, row3 ANCHOR, row4 first mom
    for i, r in enumerate(m_result.next_month_rows):
        excel_row = data_start + i
        rows.append(
            {
                "row_type": "NEXT",
                "ticker": r.ticker,
                "sleeve": "momentum",
                "weight_pct_r0": f"{r.est_weight * 100:.2f}",
                "in_rdyn": "Y" if r.ticker.upper() in r_next else "N",
                "status": f"{r.status} {r.alert}",
                "roc_long_pct": f"{r.roc_long:.1f}",
                "roc_20_pct": f"{r.roc_short:.1f}",
                "dist_ma_pct": f"{r.dist_ma:.1f}",
                "amount_twd": f"=$J$2*D{excel_row}/100",
            }
        )

    path = out_dir / f"alloc_committee_tw_{stamp}_next.csv"
    _write_csv(path, fields, rows, preamble=[])
    readme = out_dir / f"alloc_committee_tw_{stamp}_readme.txt"
    readme.write_text(
        "\n".join(
            [
                "# AI 台股投資委員會 — 下月配置試算",
                "# 基準動能袖 = Apex-TW R0；核心袖 = 0050.TW",
                "# 1. 第 2 列 amount_twd（J 欄）填總投資金額。",
                "# 2. 第 3 列 ANCHOR：在 weight_pct_r0（D 欄）填 0050 袖比重％。",
                "# 3. 動能列公式 =$J$2 * weight_pct_r0 / 100（相對「動能袖」權重；",
                "#    若要相對總資金，請先把動能權重 × (1−錨定袖％) 再填）。",
                "# 4. in_rdyn=Y 表示 RDyn 下月名單也有此標的（共識）。",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return [path, readme]
