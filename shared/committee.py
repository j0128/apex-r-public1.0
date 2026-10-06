"""AI 投資委員會 — 固定格式日報紀要（Apex-M × Apex-R）。

每日產出同一骨架：席次 → 狀態 → 本月對照 → 下月預演 → 焦點 → 自動決議草案。
主席預設執行基準：Apex-M（R0）；Apex-R 為衛星異議席。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Set

import pytz

from apex_core import ApexConfig, MonitorResult
from strategy_presets import product_name, report_header_cfg

TW = pytz.timezone("Asia/Taipei")
SEP = "═" * 38
LINE = "─" * 38


def _set(xs: Iterable[str]) -> Set[str]:
    return {str(x).strip().upper() for x in xs if str(x).strip()}


def _fmt_list(tickers: Sequence[str], weights: Optional[Dict[str, float]] = None) -> str:
    if not tickers:
        return "（無）"
    if not weights:
        return "、".join(tickers)
    parts = []
    for t in tickers:
        w = weights.get(t)
        if w is None:
            parts.append(t)
        else:
            parts.append(f"{t}({w * 100:.1f}%)")
    return "、".join(parts)


def _sorted_by_weight(tickers: Set[str], weights: Dict[str, float]) -> List[str]:
    return sorted(tickers, key=lambda t: weights.get(t, 0.0), reverse=True)


def build_committee_minutes(
    *,
    m_result: MonitorResult,
    m_cfg: ApexConfig,
    r_result: MonitorResult,
    r_cfg: ApexConfig,
    briefing_excerpt: str = "",
    query_date: str = "",
) -> str:
    """固定格式委員會紀要正文（純文字，適配 Gmail）。"""
    now = datetime.now(TW)
    qdate = query_date or str(m_cfg.query_date)

    m_hold = _set(m_result.locked_portfolio)
    r_hold = _set(r_result.locked_portfolio)
    m_next = _set(m_result.next_month_picks)
    r_next = _set(r_result.next_month_picks)

    hold_both = m_hold & r_hold
    hold_m_only = m_hold - r_hold
    hold_r_only = r_hold - m_hold

    next_both = m_next & r_next
    next_m_only = m_next - r_next
    next_r_only = r_next - m_next

    # 相對「本月持倉」的淡出（下月不在）
    exit_m = m_hold - m_next
    exit_r = r_hold - r_next
    exit_both = exit_m & exit_r
    exit_m_only = exit_m - exit_r
    exit_r_only = exit_r - exit_m

    # 新進
    enter_m = m_next - m_hold
    enter_r = r_next - r_hold
    enter_both = enter_m & enter_r
    enter_m_only = enter_m - enter_r
    enter_r_only = enter_r - enter_m

    m_w = {k.upper(): v for k, v in m_result.locked_weights.items()}
    r_w = {k.upper(): v for k, v in r_result.locked_weights.items()}
    m_nw = {k.upper(): v for k, v in m_result.next_month_weights.items()}
    r_nw = {k.upper(): v for k, v in r_result.next_month_weights.items()}

    theme_flag = ""
    if m_result.theme_ai_hw_warning or r_result.theme_ai_hw_warning:
        theme_flag = "⚠️ 至少一方觸發主題集中警示 — 主席應檢視，勿自動加碼同主題"

    # 自動決議草案（固定規則，非自由發揮）
    exec_core = _sorted_by_weight(next_both, m_nw)
    watch_list = _sorted_by_weight(next_m_only | next_r_only, {**m_nw, **r_nw})

    lines: List[str] = []
    lines.append(SEP)
    lines.append("AI 投資委員會 · 日報紀要")
    lines.append(f"會議日（台灣）：{now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"查詢日（美股）：{qdate}")
    lines.append("性質：每日例會（固定格式）｜月度換股決策仍以月初鎖定為準")
    lines.append(SEP)
    lines.append("")
    lines.append("【席次】")
    lines.append(f"· 基準委員 Apex-M：{report_header_cfg(m_cfg)}")
    lines.append(f"· 衛星委員 Apex-R：{report_header_cfg(r_cfg)}")
    lines.append("· 主席預設執行：Apex-M（R0 純動能）")
    lines.append("· 秘書處：共用市場簡報管線（新聞／產業／總經）")
    lines.append("")
    lines.append(LINE)
    lines.append("【一、市場狀態】")
    lines.append(f"· Apex-M 戰略：{m_result.market_mode}")
    lines.append(f"· Apex-R 戰略：{r_result.market_mode}")
    if r_result.rdyn_blend_label:
        lines.append(
            f"· Apex-R RDyn：{r_result.rdyn_blend_label} "
            f"(regime={r_result.rdyn_regime}, R3={r_result.rdyn_w_r3 * 100:.0f}%)"
        )
    else:
        lines.append("· Apex-R：本日無 RDyn 混合標籤（或非 RDyn-W）")
    lines.append(
        f"· 有效曝險：M {m_result.effective_exposure * 100:.1f}%｜"
        f"R {r_result.effective_exposure * 100:.1f}%"
    )
    lines.append(
        f"· AI/半導主題：M {m_result.theme_ai_hw_weight * 100:.0f}%｜"
        f"R {r_result.theme_ai_hw_weight * 100:.0f}%"
    )
    if m_result.theme_ai_hw_warning:
        lines.append(f"· M 警示：{m_result.theme_ai_hw_warning}")
    if r_result.theme_ai_hw_warning:
        lines.append(f"· R 警示：{r_result.theme_ai_hw_warning}")
    if theme_flag:
        lines.append(f"· {theme_flag}")
    lines.append(
        f"· 換股鎖定自：M {m_result.rebalance_execution_date.strftime('%Y-%m-%d')}｜"
        f"R {r_result.rebalance_execution_date.strftime('%Y-%m-%d')}"
    )
    lines.append("")
    lines.append(LINE)
    lines.append("【二、本月持倉對照】（月內續抱，非今日買賣指令）")
    lines.append(
        f"· 共識持有（{len(hold_both)}）："
        f"{_fmt_list(_sorted_by_weight(hold_both, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 Apex-M（{len(hold_m_only)}）："
        f"{_fmt_list(_sorted_by_weight(hold_m_only, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 Apex-R（{len(hold_r_only)}）："
        f"{_fmt_list(_sorted_by_weight(hold_r_only, r_w), r_w)}"
    )
    lines.append("")
    lines.append(LINE)
    lines.append("【三、下月換股預演】")
    lines.append(
        f"· 共識續抱／納入（{len(next_both)}）："
        f"{_fmt_list(_sorted_by_weight(next_both, m_nw), m_nw)}"
    )
    lines.append(
        f"· 共識新進（{len(enter_both)}）："
        f"{_fmt_list(_sorted_by_weight(enter_both, m_nw), m_nw)}"
    )
    lines.append(
        f"· 僅 M 主張新進（{len(enter_m_only)}）："
        f"{_fmt_list(_sorted_by_weight(enter_m_only, m_nw), m_nw)}"
    )
    lines.append(
        f"· 僅 R 主張新進（{len(enter_r_only)}）："
        f"{_fmt_list(_sorted_by_weight(enter_r_only, r_nw), r_nw)}"
    )
    lines.append(
        f"· 共識淡出（{len(exit_both)}）："
        f"{_fmt_list(_sorted_by_weight(exit_both, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 M 淡出（{len(exit_m_only)}）："
        f"{_fmt_list(_sorted_by_weight(exit_m_only, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 R 淡出（{len(exit_r_only)}）："
        f"{_fmt_list(_sorted_by_weight(exit_r_only, r_w), r_w)}"
    )
    lines.append(
        f"· 下月名單分歧（僅一方要）（{len(watch_list)}）："
        f"{_fmt_list(watch_list)}"
    )
    lines.append("")
    lines.append(LINE)
    lines.append("【四、今日秘書處焦點】（取自基準委員簡報節錄）")
    if briefing_excerpt.strip():
        lines.append(briefing_excerpt.strip())
    else:
        lines.append("（本日無簡報節錄）")
    lines.append("")
    lines.append(LINE)
    lines.append("【五、委員會決議草案】（自動規則，主席可覆核）")
    lines.append("1. 執行基準：採 Apex-M 下月名單與權重意圖。")
    lines.append(
        f"2. 共識核心（兩邊都要）：優先配置 → {_fmt_list(exec_core)}"
    )
    lines.append(
        f"3. 分歧標的（僅一方）：列觀察／不自動加碼 → {_fmt_list(watch_list)}"
    )
    lines.append("4. 月內：無換股；僅均線警示追蹤，不因單日新聞交易。")
    lines.append("5. 若 AI/半導任一方 ≥35% 警示：禁止再往同主題加碼，直至警示解除。")
    lines.append("6. Apex-R 異議用途：壓力測試與集中度對照，不覆蓋 Apex-M 主決議。")
    lines.append("")
    lines.append(LINE)
    lines.append("【六、附件索引】")
    lines.append("· 配置試算表 CSV（權重已填；總資金／金額由人填）")
    lines.append("· alloc_committee_*_next.csv = 基準執行（Apex-M 下月權重）")
    lines.append("· Apex-M／Apex-R 完整引擎報告與市場簡報")
    lines.append("· 本紀要（committee_minutes）")
    lines.append("")
    lines.append("※ 本紀要由系統每日固定格式產生，僅供參考，非投資建議。")
    lines.append(SEP)
    return "\n".join(lines)


def excerpt_briefing(briefing: str, *, max_chars: int = 3500) -> str:
    """節錄簡報：保留深度分析 + 下月新聞開頭，控制郵件長度。"""
    text = (briefing or "").strip()
    if not text:
        return ""
    # Prefer from 大幅波動 through 下月關注, else truncate
    keep_markers = ("⚡ 大幅波動", "【下月關注", "【持倉 — 漲跌】", "【總經】")
    if "⚡ 大幅波動" in text:
        start = text.find("⚡ 大幅波動")
        chunk = text[start:]
    else:
        chunk = text
    if len(chunk) > max_chars:
        chunk = chunk[: max_chars - 20].rstrip() + "\n…（節錄，全文見附件簡報）"
    # Drop unused to satisfy linter if markers unused
    _ = keep_markers
    return chunk
