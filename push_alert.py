"""L3_ALERT: 事件触发预警推送"""
import json
import re
import logging
from datetime import datetime

from anthropic import Anthropic
from config.settings import ANTHROPIC_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
import db

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_ALERT = """你是宏观分析师。当前有一个或多个宏观指标发生了超预期变化，需要立即向投资者发送简短预警。

要求：
1. 直接说明是什么变化，数字精确
2. 解释该变化在传导链中的位置（触发了哪个传导链，处于哪个节点）
3. 给出对港美股的即时影响方向（24-48小时维度）
4. 总字数：150-250字，不得超过

禁止：事件背景的长篇介绍、重复已知数字、"投资者应关注"等废话
"""

USER_PROMPT_ALERT_TEMPLATE = """触发条件：{triggered_conditions}
当前数据快照：{snapshot_json}
与昨日/上期对比：{delta_json}
相关新闻标题（如有）：{relevant_headlines}
"""

TRIGGER_CONDITIONS = {
    "anomaly_flags_new":            lambda curr, prev: bool(curr.get("anomaly_flags")) and not bool(prev.get("anomaly_flags")),
    "signal_score_jump":            lambda c, p: any(abs(c["signals"][k] - p["signals"][k]) >= 2
                                                   for k in ["fed_score","curve_score","dxy_score","energy_score","gold_score"]),
    "total_score_threshold_cross":  lambda c, p: (c["signals"]["total_score"] >= 5 and p["signals"]["total_score"] < 5) or
                                                   (c["signals"]["total_score"] <= -3 and p["signals"]["total_score"] > -3),
    "yield_spike":                  lambda c, p: abs(c.get("snapshot", {}).get("yield_10y", 0) - p.get("snapshot", {}).get("yield_10y", 0)) > 0.15,
    "oil_spike":                   lambda c, p: (abs(c.get("snapshot", {}).get("wti", 0) - p.get("snapshot", {}).get("wti", 0)) /
                                                   max(p.get("snapshot", {}).get("wti", 1), 1)) > 0.04,
    "dxy_spike":                   lambda c, p: abs(c.get("snapshot", {}).get("dxy", 0) - p.get("snapshot", {}).get("dxy", 0)) > 1.5,
    "gold_spike":                  lambda c, p: (abs(c.get("snapshot", {}).get("gold", 0) - p.get("snapshot", {}).get("gold", 0)) /
                                                   max(p.get("snapshot", {}).get("gold", 1), 1)) > 0.025,
    "vix_threshold":               lambda c, p: c.get("snapshot", {}).get("vix", 0) > 30,
    "fomc_new_statement":           lambda c, p: c.get("qualitative_context", {}).get("fomc_delta") and not p.get("qualitative_context", {}).get("fomc_delta"),
    "cpi_published":              lambda c, p: False,  # 需要外部事件触发
    "nonfarm_published":          lambda c, p: False,  # 需要外部事件触发
}


def check_alert_conditions(curr_signal, prev_signal):
    """检查是否满足预警条件"""
    if prev_signal is None:
        return []
    triggered = []
    for cond_name, cond_fn in TRIGGER_CONDITIONS.items():
        try:
            if cond_fn(curr_signal, prev_signal):
                triggered.append(cond_name)
        except Exception as e:
            logger.warning(f"[L3_ALERT] Condition check '{cond_name}' failed: {e}")
    return triggered


def generate_alert(triggered_conditions, payload, qualitative_context):
    """调用LLM生成预警内容"""
    client = Anthropic(api_key=ANTHROPIC_API_KEY)

    snapshot = payload.get("snapshot", {})
    prev_payload = {}

    user_prompt = USER_PROMPT_ALERT_TEMPLATE.format(
        triggered_conditions=", ".join(triggered_conditions),
        snapshot_json=json.dumps(snapshot, ensure_ascii=False, indent=2),
        delta_json=json.dumps(payload.get("daily_change", {}), ensure_ascii=False, indent=2),
        relevant_headlines=json.dumps(qualitative_context.get("news_context", [])[:3], ensure_ascii=False)
    )

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=600,
        temperature=0.2,
        system=SYSTEM_PROMPT_ALERT,
        messages=[{"role": "user", "content": user_prompt}]
    )

    raw_output = ""
    for block in response.content:
        if hasattr(block, "text") and block.text:
            raw_output += block.text + "\n"

    logger.info(f"[L3_ALERT] raw_output: {raw_output[:300]}")
    return raw_output.strip()


def assemble_alert(triggered_conditions, payload, llm_content):
    """组装预警消息"""
    TRIGGER_LABELS = {
        "anomaly_flags_new":            "⚡ 新增异常信号",
        "signal_score_jump":            "⚡ 信号评分突变",
        "total_score_threshold_cross":  "⚡ 综合评分越过关键阈值",
        "yield_spike":                  "⚡ 利率剧烈波动",
        "oil_spike":                    "⚡ 油价异常波动",
        "dxy_spike":                    "⚡ 美元指数急变",
        "gold_spike":                   "⚡ 黄金异常波动",
        "vix_threshold":                "⚡ VIX 突破警戒位",
        "fomc_new_statement":           "⚡ FOMC 新声明发布",
        "cpi_published":                "⚡ 新CPI数据公布",
        "nonfarm_published":            "⚡ 非农就业数据公布"
    }

    trigger_label = TRIGGER_LABELS.get(triggered_conditions[0], "⚡ 宏观事件预警")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")

    lines = [
        f"{trigger_label}",
        f"时间：{now_str}",
        "",
        llm_content,
        "",
        "_事件提醒，不构成投资建议_"
    ]
    return "\n".join(lines)


def send_alert(triggered_conditions, payload, llm_content):
    """发送预警到Telegram"""
    import telegram
    import asyncio

    message = assemble_alert(triggered_conditions, payload, llm_content)

    async def _send():
        bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
        chat_id = TELEGRAM_CHAT_ID
        try:
            await bot.send_message(chat_id=chat_id, text=message, parse_mode="Markdown")
            logger.info("[L3_ALERT] Telegram alert sent successfully")
        except Exception as e:
            logger.error(f"[L3_ALERT] Telegram send failed: {e}")
            plain = strip_markdown(message)
            await bot.send_message(chat_id=chat_id, text=plain)

    asyncio.run(_send())


def strip_markdown(text):
    import re
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'_{1,2}([^_]+)_{1,2}', r'\1', text)
    text = re.sub(r'`([^`]+)`', r'\1', text)
    return text
