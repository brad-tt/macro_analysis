"""L3: 推送模块 - LLM生成 + Telegram发送"""
import json
import re
import logging
from datetime import datetime

from anthropic import Anthropic
from config.settings import ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一位资深宏观分析师，专注于全球宏观经济与港美股资产配置研究。

输入格式：JSON（包含当日宏观指标快照、五维信号评分、传导机制计算结果）
输出格式：严格按以下三段结构输出，不得添加额外段落

[NARRATIVE]
用中文撰写宏观叙事，字数限制：100-200字。
必须包含：当前宏观周期状态 + 本日最重要的一个传导变化 + 与昨日的对比（若有数据）。
禁止引入输入JSON中不存在的数字。

[HK_US_IMPLICATION]
针对同时持有港股和美股的投资者，用2-3句中文说明当前宏观环境的直接含义。
必须具体，不得使用"市场可能..."等模糊表述。

[WATCH_THIS_WEEK]
列出1-2个本周需要关注的宏观事件或数据发布（格式：事件名 · 预期日期 · 关注原因一句话）。
数据来源：仅使用输入JSON中的 upcoming_events 字段，若该字段为空则输出"本周无重要数据发布"。
"""


def generate_report(payload):
    """调用LLM生成中文宏观简报"""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    user_prompt = f"""今日日期：{payload['date']}

宏观数据：
{json.dumps(payload, ensure_ascii=False, indent=2)}
"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1200,
        temperature=0.3,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}]
    )

    # 兼容 ThinkingBlock（思考过程块，无 .text 属性）
    # 收集所有 TextBlock 的文本（可能有多个）
    raw_output = ""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            raw_output += block.text + "\n"

    logger.info(f"[L3] raw_output preview: {raw_output[:200]}")
    sections = validate_llm_output(raw_output, payload)
    return sections


def validate_llm_output(raw_output, payload):
    """验证LLM输出结构 + 幻觉检测"""
    # 各section必须有，否则用占位符（不整体失败）
    narrative       = extract_section(raw_output, "NARRATIVE")       if "[NARRATIVE]"          in raw_output else "（当日宏观叙事暂不可用）"
    hk_implication = extract_section(raw_output, "HK_US_IMPLICATION") if "[HK_US_IMPLICATION]" in raw_output else "（港美股含义暂不可用）"
    watch_this_week = extract_section(raw_output, "WATCH_THIS_WEEK") if "[WATCH_THIS_WEEK]"   in raw_output else "本周无重要数据发布"

    char_count = len([c for c in narrative if '\u4e00' <= c <= '\u9fff'])
    if char_count > 200:
        narrative = truncate_at_sentence(narrative, max_chars=200)
    if char_count < 20:
        raise LLMOutputError(f"Narrative too short ({char_count} chars), retry")

    # 幻觉检测（仅警告，不中断）
    numbers_in_output = extract_numbers(narrative)
    numbers_in_payload = extract_all_numbers_from_payload(payload)
    hallucinated = [n for n in numbers_in_output if not approximately_exists(n, numbers_in_payload)]
    if hallucinated:
        logger.warning(f"Hallucinated numbers detected: {hallucinated}")

    return {
        "narrative":          narrative,
        "hk_us_implication":  hk_implication,
        "watch_this_week":    watch_this_week,
    }


def extract_section(text, section):
    pattern = rf"{re.escape(section)}\s*(.*?)(?=\[|$)"
    match = re.search(pattern, text, re.DOTALL)
    result = match.group(1).strip() if match else ""
    # 去除首尾的 ] 或 [ 杂字符
    result = result.lstrip(']').lstrip('[').strip()
    return result


def extract_numbers(text):
    return set(float(n) for n in re.findall(r"-?\d+\.?\d*", text))


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
            numbers.append(round(obj, 2))
    walk(payload)
    return numbers


def approximately_exists(num, payload_numbers, tolerance=0.05):
    """检查数字是否在payload数值集合中（允许误差）"""
    for pn in payload_numbers:
        if pn and abs(float(num) - float(pn)) < tolerance:
            return True
    return False


def truncate_at_sentence(text, max_chars):
    """截断到最近句号"""
    truncated = text[:max_chars]
    last_period = max(truncated.rfind('。'), truncated.rfind('.'))
    if last_period > max_chars * 0.5:
        return truncated[:last_period+1]
    return truncated


def assemble_telegram_message(payload, llm_sections):
    """组装Telegram消息"""
    SCORE_EMOJI = {2: "🟢", 1: "🟡", 0: "⚪", -1: "🟡", -2: "🔴"}
    CYCLE_LABEL = {
        "expansion":   "扩张期",
        "overheating": "过热期",
        "stagflation": "滞胀期",
        "recession":   "衰退期",
        "recovery":    "复苏期",
        "uncertain":   "不确定"
    }

    s = payload["snapshot"]
    sig = payload["signals"]
    cyc = payload["cycle"]
    anom = payload.get("anomaly_flags", [])
    dc = payload.get("daily_change", {})

    def fmt_delta(key):
        v = dc.get(f"{key}_1d_delta", 0) or 0
        return f"{'+' if v >= 0 else ''}{v:.2f}"

    lines = [
        f"📊 *宏观早报 · {payload['date']}*",
        f"周期状态：{CYCLE_LABEL.get(cyc['state'], '不确定')}（置信度 {cyc['confidence']}%）",
        "",
        "━━ 指标快照 ━━",
        f"10Y美债  {s.get('yield_10y', 'N/A'):.2f}%  `{fmt_delta('yield_10y')}bp`" if isinstance(s.get('yield_10y'), (int,float)) else f"10Y美债  N/A",
        f"2Y美债   {s.get('yield_2y', 'N/A'):.2f}%  `{fmt_delta('yield_2y')}bp`" if isinstance(s.get('yield_2y'), (int,float)) else f"2Y美债   N/A",
        f"2-10利差 {payload['curve'].get('spread_2_10', 0)*100:.0f}bp" if payload['curve'].get('spread_2_10') is not None else "2-10利差  N/A",
        f"DXY      {s.get('dxy', 'N/A'):.1f}  `{fmt_delta('dxy')}`" if isinstance(s.get('dxy'), (int,float)) else f"DXY      N/A",
        f"WTI      ${s.get('wti', 'N/A'):.1f}  `{fmt_delta('wti')}`" if isinstance(s.get('wti'), (int,float)) else f"WTI      N/A",
        f"黄金     ${s.get('gold', 'N/A'):.0f}  `{fmt_delta('gold')}`" if isinstance(s.get('gold'), (int,float)) else f"黄金     N/A",
        f"VIX      {s.get('vix', 'N/A'):.1f}  `{fmt_delta('vix')}`" if isinstance(s.get('vix'), (int,float)) else f"VIX      N/A",
        "",
        "━━ 信号评分 ━━",
        f"{SCORE_EMOJI.get(sig['fed_score'],'⚪')} 联储政策  {SCORE_EMOJI.get(sig['curve_score'],'⚪')} 收益率曲线  {SCORE_EMOJI.get(sig['dxy_score'],'⚪')} 美元",
        f"{SCORE_EMOJI.get(sig['energy_score'],'⚪')} 能源       {SCORE_EMOJI.get(sig['gold_score'],'⚪')} 黄金",
        f"综合评分：{'+' if sig['total_score'] > 0 else ''}{sig['total_score']} / 10",
        "",
        "━━ 宏观解读 ━━",
        llm_sections["narrative"],
        "",
        "━━ 港美股含义 ━━",
        llm_sections["hk_us_implication"],
        "",
        "━━ 本周关注 ━━",
        llm_sections["watch_this_week"],
    ]

    if anom:
        anomaly_text = "\n".join([f"⚠️ {a}" for a in anom])
        lines += ["", "━━ 异常信号 ━━", anomaly_text]

    lines += ["", "_本简报由自动化系统生成，不构成投资建议_"]
    return "\n".join(lines)


def send_telegram(message):
    """发送Telegram消息（python-telegram-bot v20+ 为异步，需用 asyncio.run）"""
    import telegram
    import asyncio

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        chat_id = TELEGRAM_CHAT_ID
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            logger.info("[L3] Telegram message sent successfully")
        except Exception as e:
            logger.error(f"[L3] Telegram send failed (Markdown): {e}")
            plain = strip_markdown(message)
            await bot.send_message(chat_id=chat_id, text=plain)

    asyncio.run(_send())


def strip_markdown(text):
    """去除所有Markdown格式符号"""
    import re
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text


class LLMOutputError(Exception):
    pass


def send_error_notification(date_str, phase, error_type, error_message):
    """L3.5 错误通知"""
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
