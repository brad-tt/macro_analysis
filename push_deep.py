"""L3_DEEP: 每周深度报告推送"""
import json
import re
import logging
from datetime import datetime, date, timedelta

from anthropic import Anthropic
from config.settings import ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_DEEP = """你是一位专注于全球宏观经济与港美股资产配置的资深分析师，拥有跨资产传导机制的深度研究背景。

你的分析风格要求：
1. 因果优先：每一个观察必须追问"为什么"，并解释传导路径
2. 前瞻而非复述：不要重复数字，要解释数字意味着什么会发生
3. 具体而非模糊：给出可验证的判断，而不是"可能""或许"
4. 层次递进：从数据事实 → 机制解释 → 市场含义 → 投资者行动

输入数据包含两部分：
- quantitative_payload: 结构化宏观指标和信号评分（JSON）
- qualitative_context: 联储措辞、新闻背景、市场持仓（JSON）

输出格式要求（严格按以下标签结构输出，每个标签单独成行）：

[MACRO_NARRATIVE]
（内容）

[CAUSAL_CHAIN]
（内容）

[FED_QUALITATIVE]
（内容）

[POSITIONING]
（内容）

[WATCH_NEXT_WEEK]
（内容）

绝对禁止：
- 引入输入数据中不存在的数字
- 使用"市场可能""或许会""不排除"等无法验证的表述超过1次
- 将多个传导链混在一起叙述（每段聚焦一个机制）
- 在 [POSITIONING] 中给出"保持观望"这类零信息量建议
"""

USER_PROMPT_TEMPLATE_DEEP = """报告日期：{date}
本期覆盖区间：{week_start} 至 {date}

定量数据（当日快照 + 本周变化）：
{quantitative_payload_json}

定性背景数据：
{qualitative_context_json}

上期（上周）综合评分：{prev_total_score}（本期：{current_total_score}，变化：{score_delta}）

请按指定格式生成深度周报内容。
"""


def generate_deep_report(payload, qualitative_context, prev_signal=None):
    """调用LLM生成深度周报"""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    week_start = (date.fromisoformat(payload["date"]) - timedelta(days=7)).isoformat()
    current_total_score = payload["signals"]["total_score"]
    prev_total_score = prev_signal["signals"]["total_score"] if prev_signal else 0
    score_delta = current_total_score - prev_total_score

    user_prompt = USER_PROMPT_TEMPLATE_DEEP.format(
        date=payload["date"],
        week_start=week_start,
        quantitative_payload_json=json.dumps(payload, ensure_ascii=False, indent=2),
        qualitative_context_json=json.dumps(qualitative_context, ensure_ascii=False, indent=2),
        prev_total_score=prev_total_score,
        current_total_score=current_total_score,
        score_delta=f"{'+' if score_delta >= 0 else ''}{score_delta}"
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2000,
        temperature=0.3,
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

    # 质量检查
    if "→" not in sections.get("CAUSAL_CHAIN", ""):
        logger.warning("[L3_DEEP] CAUSAL_CHAIN missing causal arrow '→'")
    if "港股" not in sections.get("POSITIONING", ""):
        logger.warning("[L3_DEEP] POSITIONING missing '港股'")
    if "美股" not in sections.get("POSITIONING", ""):
        logger.warning("[L3_DEEP] POSITIONING missing '美股'")

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
        numbers = re.findall(r"-?\d+\.?\d*", section_text)
        for n in numbers:
            if not approximately_exists(float(n), payload_numbers):
                hallucinated.append(n)
    return hallucinated


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


def approximately_exists(num, payload_numbers, tolerance=0.05):
    for pn in payload_numbers:
        if pn and abs(float(num) - float(pn)) < tolerance:
            return True
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

    def fmt_week_delta(key):
        v = payload.get("weekly_change", {}).get(f"{key}_7d_delta", 0)
        if v is None:
            return "N/A"
        return f"{'+' if v >= 0 else ''}{v:.2f}"

    def safe_val(val, fmt):
        return fmt.format(val) if isinstance(val, (int, float)) else "N/A"

    lines = [
        f"📊 *宏观周报 · 第{get_week_number(payload['date'])}周 · {payload['date']}*",
        f"周期：{CYCLE_LABEL.get(cyc['state'], '不确定')}（置信度 {cyc['confidence']}%）",
        "",
        "━━ 本周指标变化 ━━",
        f"{'指标':<10} {'当前值':>8} {'周变化':>10}",
        f"{'10Y美债':<10} {s.get('yield_10y', 0):.2f}%  {fmt_week_delta('yield_10y')}bp",
        f"{'2Y美债':<10} {s.get('yield_2y', 0):.2f}%  {fmt_week_delta('yield_2y')}bp",
        f"{'2-10利差':<10} {(payload['curve'].get('spread_2_10') or 0)*100:.0f}bp  {fmt_week_delta('spread_2_10')}bp",
        f"{'DXY':<10} {s.get('dxy', 0):.1f}  {fmt_week_delta('dxy')}",
        f"{'WTI':<10} ${s.get('wti', 0):.1f}  {fmt_week_delta('wti')}",
        f"{'黄金':<10} ${s.get('gold', 0):.0f}  {fmt_week_delta('gold')}",
        f"{'VIX':<10} {s.get('vix', 0):.1f}  {fmt_week_delta('vix')}",
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
        "━━ 港美股配置含义 ━━",
        llm_sections.get("POSITIONING", "（暂不可用）"),
        "",
        "━━ 下周关注 ━━",
        llm_sections.get("WATCH_NEXT_WEEK", "本周无重要经济数据发布"),
    ]

    if anom:
        anomaly_explanations = {
            "yield_policy_inversion":          "⚠️ 降息信号下长端利率不降反升，市场不信任联储路径",
            "gold_realrate_decorrelation":      "⚠️ 黄金与实际利率相关性转正，央行购金或避险需求主导",
            "em_pressure":                      "⚠️ 强美元+DXY>105，新兴市场资金外流风险上升",
            "gold_dxy_simultaneous_rise":       "⚠️ 金价与美元同涨，信用体系压力信号",
            "credit_vix_divergence":            "⚠️ 信用利差与VIX背离，风险定价内部分裂"
        }
        lines += ["", "━━ 异常信号 ━━"]
        for flag in anom:
            lines.append(anomaly_explanations.get(flag, f"⚠️ {flag}"))

    lines += ["", "_本报告由自动化系统生成，不构成投资建议_"]
    return "\n".join(lines)


def send_deep_report(payload, llm_sections):
    """发送深度报告到Telegram"""
    import telegram
    import asyncio

    qualitative_context = payload.get("qualitative_context", {})
    message = assemble_deep_report(payload, qualitative_context, llm_sections)

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        chat_id = TELEGRAM_CHAT_ID
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            logger.info("[L3_DEEP] Telegram deep report sent successfully")
        except Exception as e:
            logger.error(f"[L3_DEEP] Telegram send failed (Markdown): {e}")
            plain = strip_markdown(message)
            await bot.send_message(chat_id=chat_id, text=plain)

    asyncio.run(_send())


def strip_markdown(text):
    import re
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


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
