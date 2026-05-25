"""L3_DEEP: 每周深度报告推送 — v3 更新：POSITIONING 移除港股，专注美股"""
import json
import re
import logging
from datetime import datetime, date, timedelta

from anthropic import Anthropic
from config.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_DEEP = """你是一位专注于全球宏观经济与美股资产配置的资深分析师，拥有跨资产传导机制的深度研究背景。

你的分析风格要求：
1. 因果优先：每一个观察必须追问"为什么"，并解释传导路径
2. 前瞻而非复述：不要重复数字，要解释数字意味着什么会发生
3. 具体而非模糊：给出可验证的判断，而不是"可能""或许"
4. 层次递进：从数据事实 → 机制解释 → 市场含义 → 投资者行动

【数字使用规则】— 严格遵守，否则幻觉检测会截断内容：
- 只使用下方的"【核心数据】"中直接给出的数值
- 引用时必须原文引用，禁止重写单位、近似值或换算
  * 美债收益率：直接写"0.04%"，不要写"4bp"、"零点零四"或"约0"
  * WTI原油：直接写"100.72"，不要写"$100"、"100美元"或"约101"
  * 黄金：直接写"4857"，不要写"4800"、"近5000"或"$4XXX"
  * 利差：直接写"2.86%"，不要写"286bp"、"约3%"或"不到3"
- 禁止在内容中提及任何历史年份（如2008、1970、2020、2024等）
- 禁止用历史事件做比较时带出具体数字年份
- 除了直接复述【核心数据】里的原始数字，正文五节尽量不要出现任何阿拉伯数字、年份、bp、美元符号或百分号
- 如必须引用数字，每节最多 1 个，且必须与【核心数据】原文完全一致
- 不确定时宁可不写数字，也不要写近似值

输出格式要求（严格按以下标签结构输出，每个标签单独成行）：

[MACRO_NARRATIVE]
（内容，150-350中文字）

[CAUSAL_CHAIN]
（内容，必须包含"→"符号表示因果传导，100-300中文字）

[FED_QUALITATIVE]
（内容，80-250中文字）

[POSITIONING]
（内容，120-300中文字，必须提及"美股"以及标普500/纳斯达克/科技股等具体方向）

[WATCH_NEXT_WEEK]
（内容，50-200中文字）

绝对禁止：
- 使用"市场可能""或许会""不排除"等无法验证的表述超过1次
- 将多个传导链混在一起叙述（每段聚焦一个机制）
- 在 [POSITIONING] 中给出"保持观望"这类零信息量建议
- 任何章节出现超过3个数字
- 章节内容留空或不写
- 提及任何历史年份（2008、1970、2020、2024等）
"""

USER_PROMPT_TEMPLATE_DEEP = """报告日期：{date}
本期覆盖区间：{week_start} 至 {date}

【核心数据 - 严格按原文引用，不许改写单位或近似值】

  美债收益率: 10Y={yield_10y:.2f}%  2Y={yield_2y:.2f}%  3M={yield_3mo:.3f}%  2-10spread={spread_2_10:.4f}
  WTI原油: {wti:.2f}  黄金: {gold:.0f}  DTWEXBGS: {dxy:.1f}  VIX: {vix:.1f}
  信用利差: HY={hy_spread:.2f}%  IG={ig_spread:.2f}%
  TIPS实际利率={tips_10y:.2f}%  盈亏平衡通胀={breakeven_10y:.2f}%  CPI={cpi_yoy:.1f}%

【信号评分】Fed={fed_score} Curve={curve_score} DXY={dxy_score} Energy={energy_score} Gold={gold_score}  综合={total_score}/10（上周={prev_total_score} {score_delta}）

【周期状态】{cycle_state}（置信{cycle_confidence}%）

【近期新闻】
{news_summary}

【输出格式 - 严格按5个标签依次填写，内容不许留空】

[MACRO_NARRATIVE]
（150-350中文字）

[CAUSAL_CHAIN]
（100-300中文字，用→表示传导，如"高油价→运费上升→企业成本压力→美股盈利下修"）

[FED_QUALITATIVE]
（80-250中文字）

[POSITIONING]
（120-300中文字，必须含"美股"）

[WATCH_NEXT_WEEK]
（50-200中文字）
"""


def generate_deep_report(payload, qualitative_context, prev_signal=None):
    """调用LLM生成深度周报"""
    client_kwargs = {"api_key": LLM_API_KEY}
    if LLM_BASE_URL:
        client_kwargs["base_url"] = LLM_BASE_URL
    client = Anthropic(**client_kwargs)

    week_start = (date.fromisoformat(payload["date"]) - timedelta(days=7)).isoformat()
    current_total_score = payload["signals"]["total_score"]
    prev_total_score = prev_signal["signals"]["total_score"] if prev_signal else 0
    score_delta = current_total_score - prev_total_score

    sig = payload["signals"]
    s = payload["snapshot"]
    cyc = payload.get("cycle", {})
    energy = payload.get("energy", {})

    # 从定性上下文提取新闻摘要（最近7日最多5条）
    news_items = []
    nc = qualitative_context.get("news_context", [])
    if nc:
        for h in nc[:5]:
            if isinstance(h, dict):
                news_items.append(h.get("headline", ""))
            elif isinstance(h, str):
                news_items.append(h)
        if not news_items:
            news_items = nc[:5] if isinstance(nc, list) else []

    user_prompt = USER_PROMPT_TEMPLATE_DEEP.format(
        date=payload["date"],
        week_start=week_start,
        yield_10y=s.get("yield_10y", 0),
        yield_2y=s.get("yield_2y", 0),
        yield_3mo=s.get("yield_3mo", 0),
        spread_2_10=(payload.get("curve", {}).get("spread_2_10") or 0),
        wti=s.get("wti", 0),
        gold=s.get("gold", 0),
        dxy=s.get("dxy", 0),
        vix=s.get("vix", 0),
        hy_spread=s.get("hy_spread", 0),
        ig_spread=s.get("ig_spread", 0),
        tips_10y=s.get("tips_10y", 0),
        breakeven_10y=s.get("breakeven_10y", 0),
        cpi_yoy=energy.get("cpi_latest") or 0,
        fed_score=sig.get("fed_score", 0),
        curve_score=sig.get("curve_score", 0),
        dxy_score=sig.get("dxy_score", 0),
        energy_score=sig.get("energy_score", 0),
        gold_score=sig.get("gold_score", 0),
        total_score=current_total_score,
        prev_total_score=prev_total_score,
        score_delta=f"{'+' if score_delta >= 0 else ''}{score_delta}",
        cycle_state=cyc.get("state", "未知"),
        cycle_confidence=cyc.get("confidence", 0),
        news_summary="\n".join(f"  - {n}" for n in news_items) if news_items else "  （无近期新闻）",
    )

    response = client.messages.create(
        model=LLM_MODEL,
        max_tokens=4000,
        temperature=0.2,
        system=SYSTEM_PROMPT_DEEP,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw_output = ""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            raw_output += block.text + "\n"

    logger.info(f"[L3_DEEP] raw_output preview: {raw_output[:300]}")
    sections = validate_deep_report(raw_output, payload)
    return sections


def validate_deep_report(raw_output, payload):
    """验证L3_DEEP输出结构 + 字数 + 质量"""
    required_sections = [
        "[MACRO_NARRATIVE]",
        "[CAUSAL_CHAIN]",
        "[FED_QUALITATIVE]",
        "[POSITIONING]",
        "[WATCH_NEXT_WEEK]"
    ]
    for section in required_sections:
        if section not in raw_output:
            logger.warning(f"[L3_DEEP] Missing section: {section}")

    sections = parse_sections(raw_output)

    # 各节字数检查
    length_rules = {
        "MACRO_NARRATIVE":  (150, 350),
        "CAUSAL_CHAIN":     (100, 300),
        "FED_QUALITATIVE":  (80,  250),
        "POSITIONING":      (120, 300),
        "WATCH_NEXT_WEEK":  (50,  200)
    }
    for section_id, (min_len, max_len) in length_rules.items():
        text = sections.get(section_id, "")
        char_count = count_chinese_chars(text)
        if char_count > max_len:
            sections[section_id] = truncate_at_sentence(text, max_len)
            logger.warning(f"[L3_DEEP] {section_id} truncated to {max_len} chars")
        if char_count < min_len and char_count > 0:
            logger.warning(f"[L3_DEEP] {section_id} too short: {char_count} chars (min {min_len})")

    # 幻觉检测
    hallucinated = check_hallucinated_numbers(sections, payload)
    if hallucinated:
        logger.warning(f"[L3_DEEP] Hallucinated numbers: {hallucinated}")
        raise LLMOutputError(f"hallucinated numbers detected: {', '.join(sorted(set(hallucinated)))}")

    # 质量检查：CAUSAL_CHAIN 必须包含 "→" 符号
    if "→" not in sections.get("CAUSAL_CHAIN", ""):
        logger.warning("[L3_DEEP] CAUSAL_CHAIN missing causal arrow '→'")
    # v3: POSITIONING 必须包含"美股"，不得包含"港股"
    if "美股" not in sections.get("POSITIONING", ""):
        logger.warning("[L3_DEEP] POSITIONING missing '美股'")
    if "港股" in sections.get("POSITIONING", ""):
        logger.warning("[L3_DEEP] POSITIONING contains '港股' which is forbidden in v3")

    return sections


def parse_sections(raw_output):
    """按标签解析LLM输出"""
    sections = {}
    labels = ["[MACRO_NARRATIVE]", "[CAUSAL_CHAIN]", "[FED_QUALITATIVE]", "[POSITIONING]", "[WATCH_NEXT_WEEK]"]
    for i, label in enumerate(labels):
        next_label = labels[i+1] if i+1 < len(labels) else None
        pattern = rf"{re.escape(label)}\s*(.*?)(?={re.escape(next_label) if next_label else '$'})"
        match = re.search(pattern, raw_output, re.DOTALL)
        text = match.group(1).strip() if match else ""
        text = text.lstrip(']').lstrip('[').strip()
        sections[label.replace("[", "").replace("]", "")] = text
    return sections


def count_chinese_chars(text):
    return len([c for c in text if '\u4e00' <= c <= '\u9fff'])


def truncate_at_sentence(text, max_chars):
    """截断到最近句号"""
    truncated = text[:max_chars]
    last_period = max(truncated.rfind('。'), truncated.rfind('.'))
    if last_period > max_chars * 0.5:
        return truncated[:last_period+1]
    return truncated


def check_hallucinated_numbers(sections, payload):
    """检测输出中的数字是否在payload中存在"""
    payload_numbers = extract_all_numbers_from_payload(payload)
    hallucinated = []
    for section_text in sections.values():
        cleaned_text = sanitize_numeric_labels(section_text)
        numbers = re.findall(r"-?\d+\.?\d*", cleaned_text)
        for n in numbers:
            if not approximately_exists(float(n), payload_numbers):
                hallucinated.append(n)
    return hallucinated


def sanitize_numeric_labels(text):
    """移除宏观金融里常见的术语数字，避免把行业标签误判成幻觉。"""
    patterns = [
        r"\b10Y\b",
        r"\b2Y\b",
        r"\b3M\b",
        r"10年期",
        r"2年期",
        r"3个月",
        r"2-10(?:利差|spread)?",
        r"S&P\s*500",
        r"标普\s*500",
        r"标普500",
        r"纳斯达克\s*100",
        r"纳斯达克100",
        r"NASDAQ\s*100",
        r"Nasdaq\s*100",
    ]
    cleaned = text
    for pattern in patterns:
        cleaned = re.sub(pattern, "TERM", cleaned, flags=re.IGNORECASE)
    return cleaned


def extract_all_numbers_from_payload(payload):
    """提取payload中所有数值"""
    numbers = []
    def walk(obj):
        if isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, (int, float)):
            numbers.append(round(float(obj), 2))
    walk(payload)
    return numbers


def approximately_exists(num, payload_numbers):
    """
    按数值量级自动选择容差，避免固定容差导致的误判。
    容差规则（覆盖宏观指标的典型量级）：
      < 10    → 收益率/利差/百分比类，容差 0.05
      10~200  → 指数/汇率类（DXY/VIX/EURUSD），容差 0.5
      200~500 → 中等价格（无此类指标，预留），容差 2.0
      > 500   → 大价格（黄金/SPX），容差 5.0
    """
    num = float(num)
    abs_num = abs(num)

    if abs_num < 10:
        tolerance = 0.05
    elif abs_num < 200:
        tolerance = 0.5
    elif abs_num < 500:
        tolerance = 2.0
    else:
        tolerance = 5.0

    for pn in payload_numbers:
        if pn is not None:
            try:
                if abs(num - float(pn)) < tolerance:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def get_week_number(target_date=None):
    """ISO周数"""
    if target_date is None:
        target_date = date.today()
    elif isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)
    return target_date.isocalendar()[1]


def assemble_deep_report(payload, qualitative_context, llm_sections):
    """组装深度报告Telegram消息"""
    s = payload["snapshot"]
    sig = payload["signals"]
    cyc = payload["cycle"]
    anom = payload.get("anomaly_flags", [])

    SCORE_EMOJI = {2: "🟢", 1: "🟡", 0: "⚪", -1: "🟡", -2: "🔴"}
    CYCLE_LABEL = {
        "expansion": "扩张期", "overheating": "过热期",
        "stagflation": "滞胀期", "recession": "衰退期",
        "recovery": "复苏期", "uncertain": "不确定"
    }

    def fmt_week_delta(key, scale=1.0, suffix=""):
        v = payload.get("weekly_change", {}).get(f"{key}_7d_delta", 0)
        if v is None:
            return "N/A"
        return f"{'+' if v >= 0 else ''}{v * scale:.2f}{suffix}"

    def safe_val(val, fmt):
        return fmt.format(val) if isinstance(val, (int, float)) else "N/A"

    lines = [
        f"📊 *宏观周报 · 第{get_week_number(payload['date'])}周 · {payload['date']}*",
        f"周期：{CYCLE_LABEL.get(cyc['state'], '不确定')}（置信度 {cyc['confidence']}%）",
        "",
        "━━ 本周指标变化 ━━",
        f"{'指标':<10} {'当前值':>8} {'周变化':>10}",
        f"{'10Y美债':<10} {s.get('yield_10y', 0):.2f}%  {fmt_week_delta('yield_10y', scale=100, suffix='bp')}",
        f"{'2Y美债':<10} {s.get('yield_2y', 0):.2f}%  {fmt_week_delta('yield_2y', scale=100, suffix='bp')}",
        f"{'2-10利差':<10} {(payload['curve'].get('spread_2_10') or 0)*100:.0f}bp  {fmt_week_delta('spread_2_10', scale=100, suffix='bp')}",
        f"{'DTWEXBGS':<10} {s.get('dxy', 0):.1f}  {fmt_week_delta('dxy', suffix='点')}",
        f"{'WTI':<10} ${s.get('wti', 0):.1f}  {fmt_week_delta('wti', suffix='美元')}",
        f"{'黄金':<10} ${s.get('gold', 0):.0f}  {fmt_week_delta('gold', suffix='美元')}",
        f"{'VIX':<10} {s.get('vix', 0):.1f}  {fmt_week_delta('vix', suffix='点')}",
        "",
        "━━ 信号评分 ━━",
        f"{SCORE_EMOJI.get(sig['fed_score'],'⚪')} 联储  "
        f"{SCORE_EMOJI.get(sig['curve_score'],'⚪')} 曲线  "
        f"{SCORE_EMOJI.get(sig['dxy_score'],'⚪')} 美元  "
        f"{SCORE_EMOJI.get(sig['energy_score'],'⚪')} 能源  "
        f"{SCORE_EMOJI.get(sig['gold_score'],'⚪')} 黄金",
        f"综合：{'+' if sig['total_score'] > 0 else ''}{sig['total_score']} / 10",
        "",
        "━━ 宏观解读 ━━",
        llm_sections.get("MACRO_NARRATIVE", "（暂不可用）"),
        "",
        "━━ 传导链聚焦 ━━",
        llm_sections.get("CAUSAL_CHAIN", "（暂不可用）"),
        "",
        "━━ 联储定性解读 ━━",
        llm_sections.get("FED_QUALITATIVE", "（暂不可用）"),
        "",
        "━━ 美股配置含义 ━━",   # v3: 移除"港股"，专注美股
        llm_sections.get("POSITIONING", "（暂不可用）"),
        "",
        "━━ 下周关注 ━━",
        llm_sections.get("WATCH_NEXT_WEEK", "本周无重要经济数据发布"),
    ]

    if anom:
        anomaly_explanations = {
            "yield_policy_inversion":          "⚠️ 降息信号下长端利率不降反升，市场不信任联储路径",
            "gold_realrate_decorrelation":      "⚠️ 黄金与实际利率相关性转正，央行购金或避险需求主导",
            "em_pressure":                      "⚠️ 强美元+DTWEXBGS>105，新兴市场资金外流风险上升",
            "gold_dxy_simultaneous_rise":       "⚠️ 金价与美元同涨，信用体系压力信号",
            "credit_vix_divergence":            "⚠️ 信用利差与VIX背离，风险定价内部分裂"
        }
        lines += ["", "━━ 异常信号 ━━"]
        for flag in anom:
            lines.append(anomaly_explanations.get(flag, f"⚠️ {flag}"))

    lines += ["", "_本报告由自动化系统生成，不构成投资建议_"]
    return "\n".join(lines)


def build_report_html(payload, message):
    """将报告内容解析为带样式的 HTML（每节独立渲染）"""
    week_num = get_week_number(payload["date"])
    cycle_state = payload.get("cycle", {}).get("state", "不确定")
    cycle_conf = payload.get("cycle", {}).get("confidence", 0)
    sig = payload.get("signals", {})
    total = sig.get("total_score", 0)

    CYCLE_COLORS = {
        "expansion": "#2E7D32", "overheating": "#C62828",
        "stagflation": "#E65100", "recession": "#6A1B9A",
        "recovery": "#1565C0", "uncertain": "#757575"
    }
    cycle_color = CYCLE_COLORS.get(cycle_state, "#757575")

    SCORE_EMOJI = {2: "🟢", 1: "🟡", 0: "⚪", -1: "🟡", -2: "🔴"}
    CYCLE_LABEL = {
        "expansion": "扩张期", "overheating": "过热期",
        "stagflation": "滞胀期", "recession": "衰退期",
        "recovery": "复苏期", "uncertain": "不确定"
    }

    s = payload["snapshot"]
    weekly = payload.get("weekly_change", {})

    def fmt_delta(key, scale=1.0, suffix=""):
        v = weekly.get(f"{key}_7d_delta", 0)
        if v is None:
            return "N/A"
        return f"{'+' if v >= 0 else ''}{v * scale:.2f}{suffix}"

    # 解析 message 中的各节内容
    import re
    section_pattern = r'━━\s*(.+?)\s*━━\s*\n(.*?)(?=\n━━|\n_*\Z)'
    matches = re.findall(section_pattern, message, re.DOTALL)

    sections_html = ""
    for heading, content in matches:
        clean_content = content.strip()
        # 转义但保留换行
        clean_content = (clean_content
                        .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                        .replace("\n", "<br>"))
        sections_html += f"""
  <div class="section">
    <h2>{heading}</h2>
    <p>{clean_content}</p>
  </div>"""

    # 信号评分行
    sig_items = [
        ("Fed", sig.get("fed_score", 0)),
        ("Curve", sig.get("curve_score", 0)),
        ("DTWEXBGS", sig.get("dxy_score", 0)),
        ("Energy", sig.get("energy_score", 0)),
        ("Gold", sig.get("gold_score", 0)),
    ]
    sig_bars = "".join(
        f'<span class="sig-item"><span class="sig-lbl">{lbl}</span><br>'
        f'<span class="sig-val">{SCORE_EMOJI.get(s,"⚪")}</span></span>'
        for lbl, s in sig_items
    )

    # 指标表格
    indicators = [
        ("10Y美债", f"{s.get('yield_10y', 0):.2f}%", fmt_delta("yield_10y", scale=100, suffix="bp")),
        ("2Y美债", f"{s.get('yield_2y', 0):.2f}%", fmt_delta("yield_2y", scale=100, suffix="bp")),
        ("2-10利差", f"{(payload['curve'].get('spread_2_10') or 0)*100:.0f}bp", fmt_delta("spread_2_10", scale=100, suffix="bp")),
        ("DTWEXBGS", f"{s.get('dxy', 0):.1f}", fmt_delta("dxy", suffix="点")),
        ("WTI", f"${s.get('wti', 0):.1f}", fmt_delta("wti", suffix="美元")),
        ("黄金", f"${s.get('gold', 0):.0f}", fmt_delta("gold", suffix="美元")),
        ("VIX", f"{s.get('vix', 0):.1f}", fmt_delta("vix", suffix="点")),
    ]
    rows_html = "".join(
        f'<tr><td class="ind-name">{name}</td><td class="ind-val">{val}</td><td class="ind-delta">{delta}</td></tr>'
        for name, val, delta in indicators
    )

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>宏观周报 {payload['date']}</title>
<style>
  body {{
    font-family: "Hiragino Sans GB", "PingFang SC", "Microsoft YaHei", "Helvetica Neue", Arial, sans-serif;
    background: #f0f2f7;
    margin: 0;
    padding: 20px;
    font-size: 13px;
    line-height: 1.6;
    color: #222;
  }}
  .container {{
    max-width: 700px;
    margin: 0 auto;
    background: #fff;
    border-radius: 10px;
    box-shadow: 0 4px 20px rgba(0,0,0,0.10);
    overflow: hidden;
  }}
  .header {{
    background: linear-gradient(135deg, #1a237e 0%, #283593 60%, #1565C0 100%);
    color: #fff;
    padding: 26px 32px 22px;
  }}
  .header h1 {{
    margin: 0 0 5px;
    font-size: 20px;
    font-weight: 600;
  }}
  .header .meta {{
    font-size: 12px;
    opacity: 0.85;
  }}
  .cycle-badge {{
    display: inline-block;
    background: {cycle_color};
    color: #fff;
    border-radius: 4px;
    padding: 3px 10px;
    font-size: 12px;
    margin-top: 10px;
    font-weight: 500;
  }}
  .scores-bar {{
    background: #f8f9ff;
    padding: 16px 32px;
    border-bottom: 1px solid #e8eaf6;
    display: flex;
    gap: 24px;
    align-items: center;
  }}
  .sig-item {{
    display: inline-block;
    text-align: center;
  }}
  .sig-lbl {{
    font-size: 11px;
    color: #666;
  }}
  .sig-val {{
    font-size: 20px;
  }}
  .total-score {{
    margin-left: auto;
    font-size: 16px;
    font-weight: 600;
    color: #1a237e;
  }}
  table.indicators {{
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }}
  table.indicators th {{
    background: #f5f6fa;
    padding: 8px 16px;
    text-align: left;
    font-weight: 600;
    color: #333;
    border-bottom: 2px solid #e8eaf6;
  }}
  table.indicators td {{
    padding: 7px 16px;
    border-bottom: 1px solid #f0f0f5;
  }}
  .ind-name {{ color: #444; }}
  .ind-val {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .ind-delta {{ text-align: right; color: #888; font-size: 12px; }}
  .section {{
    padding: 16px 32px;
    border-bottom: 1px solid #eee;
  }}
  .section h2 {{
    font-size: 13px;
    font-weight: 700;
    color: #1a237e;
    margin: 0 0 10px;
    padding-bottom: 6px;
    border-bottom: 2px solid #c5cae9;
    letter-spacing: 0.5px;
  }}
  .section p {{
    margin: 0;
    line-height: 1.75;
    color: #333;
    font-size: 13px;
  }}
  .footer {{
    padding: 14px 32px;
    background: #f0f2ff;
    font-size: 10px;
    color: #999;
    text-align: center;
  }}
  @page {{
    margin: 1.5cm;
    size: A4;
  }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📊 宏观周报 · 第{week_num}周</h1>
    <div class="meta">{payload['date']}</div>
    <div class="cycle-badge">{CYCLE_LABEL.get(cycle_state, '不确定')}（置信度 {cycle_conf}%）</div>
  </div>

  <div class="scores-bar">
    {sig_bars}
    <div class="total-score">综合 {total}/10</div>
  </div>

  <table class="indicators">
    <tr>
      <th>指标</th><th>当前值</th><th>周变化</th>
    </tr>
    {rows_html}
  </table>

  {sections_html}

  <div class="footer">本报告由自动化系统生成，不构成投资建议</div>
</div>
</body>
</html>"""
    return html


def send_deep_report(payload, llm_sections):
    """发送深度报告到Telegram（PDF格式）"""
    import telegram
    import asyncio

    qualitative_context = payload.get("qualitative_context", {})
    message = assemble_deep_report(payload, qualitative_context, llm_sections)
    html_content = build_report_html(payload, message)
    pdf_path = html_to_pdf(html_content)

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        chat_id = TELEGRAM_CHAT_ID
        with open(pdf_path, "rb") as f:
            await bot.send_document(chat_id=chat_id, document=f, filename=f"macro_report_{payload['date']}.pdf")
        logger.info("[L3_DEEP] Telegram PDF report sent successfully")

    asyncio.run(_send())


def strip_markdown(text):
    import re
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


class LLMOutputError(Exception):
    pass


def html_to_pdf(html_content, output_path=None):
    """HTML → PDF（Playwright Chromium）"""
    import tempfile
    from pathlib import Path
    from playwright.sync_api import sync_playwright

    if output_path is None:
        output_path = tempfile.mktemp(suffix=".pdf")

    tmp_dir = Path(tempfile.gettempdir())
    tmp_html = tmp_dir / "report.html"
    tmp_html.write_text(html_content, encoding="utf-8")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"file://{tmp_html.resolve()}")
            page.wait_for_load_state("networkidle")

            page.pdf(
                path=output_path,
                format="A4",
                margin={"top": "1.5cm", "right": "1.5cm", "bottom": "1.5cm", "left": "1.5cm"},
                print_background=True,
                display_header_footer=True,
                footer_template='<div style="font-size:9px;width:100%;text-align:center;color:#888;">'
                                 '<span class="pageNumber"></span> / <span class="totalPages"></span>'
                                 '</div>',
            )
            browser.close()
    finally:
        tmp_html.unlink(missing_ok=True)

    return output_path


class LLMOutputError(Exception):
    pass


def send_error_notification(date_str, phase, error_type, error_message):
    """L3 错误通知"""
    ERROR_MESSAGE_TEMPLATE = """
⚠️ 宏观简报系统异常
日期：{date}
失败阶段：{phase}
错误类型：{error_type}
错误详情：{error_message}
操作：今日简报已跳过，明日自动重试
"""
    msg = ERROR_MESSAGE_TEMPLATE.format(
        date=date_str, phase=phase, error_type=error_type, error_message=str(error_message)[:200]
    )
    try:
        import telegram
        import asyncio
        async def _send():
            bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        asyncio.run(_send())
    except:
        print(msg)
