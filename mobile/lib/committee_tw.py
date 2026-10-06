"""AI 台股投資委員會 — 0050 錨 × Apex-TW R0 × Apex-TW RDyn-W。

每日產出：席次 → 狀態 → 本月對照 → 下月預演 → 標的消息 → 總經分析 → 決議草案。
主席預設執行基準：Apex-TW R0；0050 為錨定袖；RDyn 為衛星異議席。
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Iterable, List, Optional, Sequence, Set

import pytz

from apex_core import ApexConfig, MonitorResult
from strategy_presets import report_header_cfg

TW = pytz.timezone("Asia/Taipei")
SEP = "═" * 38
LINE = "─" * 38
ANCHOR = "0050.TW"


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


def build_committee_tw_minutes(
    *,
    m_result: MonitorResult,
    m_cfg: ApexConfig,
    r_result: MonitorResult,
    r_cfg: ApexConfig,
    news_section: str = "",
    macro_section: str = "",
    query_date: str = "",
    anchor_sleeve_hint: str = "由主席人工決定（例 30–50%）",
) -> str:
    """固定格式台股委員會紀要正文（純文字，適配 Gmail）。"""
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

    exit_m = m_hold - m_next
    exit_r = r_hold - r_next
    exit_both = exit_m & exit_r
    exit_m_only = exit_m - exit_r
    exit_r_only = exit_r - exit_m

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

    exec_core = _sorted_by_weight(next_both, m_nw)
    watch_list = _sorted_by_weight(next_m_only | next_r_only, {**m_nw, **r_nw})

    lines: List[str] = []
    lines.append(SEP)
    lines.append("AI 台股投資委員會 · 日報紀要")
    lines.append(f"會議日（台灣）：{now.strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"查詢日（台股）：{qdate}")
    lines.append("性質：每日例會（固定格式）｜月度換股決策仍以月初鎖定為準")
    lines.append(SEP)
    lines.append("")
    lines.append("【席次】")
    lines.append(f"· 錨定委員 0050：元大台灣50｜BUY&HOLD｜盤態／regime 基準")
    lines.append(f"· 基準委員 Apex-TW R0：{report_header_cfg(m_cfg)}")
    lines.append(f"· 衛星委員 Apex-TW RDyn-W：{report_header_cfg(r_cfg)}")
    lines.append("· 主席預設執行：動能袖＝Apex-TW R0；核心袖＝0050（比重人工）")
    lines.append("· 秘書處：個股消息＋總經分析（本紀要第四／五章）")
    lines.append("")
    lines.append(LINE)
    lines.append("【一、市場狀態】")
    lines.append(f"· 錨定袖：{ANCHOR}｜建議比重 {anchor_sleeve_hint}")
    lines.append(f"· Apex-TW R0 戰略：{m_result.market_mode}")
    lines.append(f"· Apex-TW RDyn 戰略：{r_result.market_mode}")
    if r_result.rdyn_blend_label:
        lines.append(
            f"· RDyn 混合：{r_result.rdyn_blend_label} "
            f"(regime={r_result.rdyn_regime}, R3={r_result.rdyn_w_r3 * 100:.0f}%)"
        )
    else:
        lines.append("· RDyn：本日無混合標籤")
    lines.append(
        f"· 有效曝險：錨 100%｜R0 {m_result.effective_exposure * 100:.1f}%｜"
        f"RDyn {r_result.effective_exposure * 100:.1f}%"
    )
    lines.append(
        f"· AI/半導主題：R0 {m_result.theme_ai_hw_weight * 100:.0f}%｜"
        f"RDyn {r_result.theme_ai_hw_weight * 100:.0f}%"
    )
    if m_result.theme_ai_hw_warning:
        lines.append(f"· R0 警示：{m_result.theme_ai_hw_warning}")
    if r_result.theme_ai_hw_warning:
        lines.append(f"· RDyn 警示：{r_result.theme_ai_hw_warning}")
    if theme_flag:
        lines.append(f"· {theme_flag}")
    lines.append(
        f"· 換股鎖定自：R0 {m_result.rebalance_execution_date.strftime('%Y-%m-%d')}｜"
        f"RDyn {r_result.rebalance_execution_date.strftime('%Y-%m-%d')}"
    )
    lines.append("")
    lines.append(LINE)
    lines.append("【二、本月持倉對照】（月內續抱，非今日買賣指令）")
    lines.append(f"· 錨定袖：{ANCHOR}（袖比重由主席定）")
    lines.append(
        f"· 動能共識持有（{len(hold_both)}）："
        f"{_fmt_list(_sorted_by_weight(hold_both, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 R0（{len(hold_m_only)}）："
        f"{_fmt_list(_sorted_by_weight(hold_m_only, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 RDyn（{len(hold_r_only)}）："
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
        f"· 僅 R0 主張新進（{len(enter_m_only)}）："
        f"{_fmt_list(_sorted_by_weight(enter_m_only, m_nw), m_nw)}"
    )
    lines.append(
        f"· 僅 RDyn 主張新進（{len(enter_r_only)}）："
        f"{_fmt_list(_sorted_by_weight(enter_r_only, r_nw), r_nw)}"
    )
    lines.append(
        f"· 共識淡出（{len(exit_both)}）："
        f"{_fmt_list(_sorted_by_weight(exit_both, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 R0 淡出（{len(exit_m_only)}）："
        f"{_fmt_list(_sorted_by_weight(exit_m_only, m_w), m_w)}"
    )
    lines.append(
        f"· 僅 RDyn 淡出（{len(exit_r_only)}）："
        f"{_fmt_list(_sorted_by_weight(exit_r_only, r_w), r_w)}"
    )
    lines.append(
        f"· 下月名單分歧（僅一方要）（{len(watch_list)}）："
        f"{_fmt_list(watch_list)}"
    )
    lines.append(f"· 錨定袖：維持 {ANCHOR}（不換股）；若 RDyn 轉防禦 → 提高錨定袖")
    lines.append("")
    lines.append(LINE)
    lines.append("【四、投資標的消息】（持倉／下月／分歧／0050）")
    if news_section.strip():
        lines.append(news_section.strip())
    else:
        lines.append("（本日無標的消息節錄）")
    lines.append("")
    lines.append(LINE)
    lines.append("【五、總經與盤態分析】")
    if macro_section.strip():
        lines.append(macro_section.strip())
    else:
        lines.append("（本日總經分析暫缺）")
    lines.append("")
    lines.append(LINE)
    lines.append("【六、委員會決議草案】（自動規則，主席可覆核）")
    lines.append("1. 執行基準：動能袖採 Apex-TW R0 下月名單與權重意圖。")
    lines.append(
        f"2. 核心袖：維持 {ANCHOR}；袖比重依 RDyn regime／0050 vs 200MA 人工調整。"
    )
    lines.append(
        f"3. 共識核心（兩邊都要）：優先配置 → {_fmt_list(exec_core)}"
    )
    lines.append(
        f"4. 分歧標的（僅一方）：列觀察／不自動加碼 → {_fmt_list(watch_list)}"
    )
    lines.append("5. 月內：無換股；僅均線警示追蹤，不因單日新聞交易。")
    lines.append(
        "6. 若 AI/半導任一方 ≥40% 警示：禁止再往同主題加碼，直至警示解除。"
    )
    lines.append(
        "7. RDyn 異議用途：壓力測試與集中度對照，不覆蓋 R0 主決議。"
    )
    lines.append("8. 台股換股成本含證交稅約 0.3%（賣出），月內勿過度周轉。")
    lines.append("")
    lines.append(LINE)
    lines.append("【七、附件索引】")
    lines.append("· 配置試算表 CSV（權重已填；總資金／0050 袖比重由人填）")
    lines.append("· alloc_committee_tw_*_next.csv = 基準執行（R0 權重＋0050 錨列）")
    lines.append("· Apex-TW R0／RDyn 完整引擎報告與市場簡報")
    lines.append("· 本紀要（committee_minutes_tw）")
    lines.append("")
    lines.append("※ 本紀要由系統每日固定格式產生，僅供參考，非投資建議。")
    lines.append(SEP)
    return "\n".join(lines)


def excerpt_tw_briefing(briefing: str, *, max_chars: int = 4200) -> str:
    """節錄簡報：大波動＋下月新聞＋持倉＋總經，供紀要第四章。"""
    text = (briefing or "").strip()
    if not text:
        return ""
    if "⚡ 大幅波動" in text:
        chunk = text[text.find("⚡ 大幅波動") :]
    elif "【下月關注" in text:
        chunk = text[text.find("【下月關注") :]
    else:
        chunk = text
    # Drop header brand lines if still present at start of chunk somehow
    if len(chunk) > max_chars:
        chunk = chunk[: max_chars - 20].rstrip() + "\n…（節錄，全文見附件簡報）"
    return chunk
