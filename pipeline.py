"""
宏观分析流水线入口
三种运行模式:
  --mode daily    : 每日静默运行 L1+L2，不推送
  --mode weekly   : 每周深度报告 L1+L2+L3_DEEP
  --mode alert    : 事件触发检查，满足条件则L3_ALERT
"""
import sys
import logging
from datetime import date, timedelta

from config.settings import LOG_LEVEL
import db
import fetch
import analysis
import push_deep
import push_alert

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[
        logging.FileHandler("./logs/pipeline.log"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def run_daily_silent(target_date=None):
    """每日 05:30 静默运行：L1 + L2，不推送"""
    if target_date is None:
        target_date = date.today().isoformat()

    logger.info(f"[PIPELINE/DAILY] Starting for {target_date}")

    # L1: 数据获取
    try:
        logger.info("[L1] Starting data fetch")
        fetch.fetch_all_indicators(target_date)
        fetch.l1_completion_assert(target_date)
        logger.info("[L1] Completed")
    except fetch.FatalError as e:
        logger.error(f"[L1] FATAL: {e}")
        push_deep.send_error_notification(target_date, "L1", "FatalError", str(e))
        return
    except Exception as e:
        logger.error(f"[L1] ERROR: {e}", exc_info=True)
        push_deep.send_error_notification(target_date, "L1", type(e).__name__, str(e))
        return

    # L2: 分析
    try:
        logger.info("[L2] Starting analysis")
        payload = analysis.run_analysis(target_date)
        logger.info("[L2] Completed")
    except Exception as e:
        logger.error(f"[L2] ERROR: {e}", exc_info=True)
        push_deep.send_error_notification(target_date, "L2", type(e).__name__, str(e))
        return

    logger.info(f"[PIPELINE/DAILY] Done for {target_date} (no push)")


def run_weekly_deep(target_date=None):
    """每周一 06:00：L1 + L2 + L3_DEEP"""
    if target_date is None:
        target_date = date.today().isoformat()

    logger.info(f"[PIPELINE/WEEKLY] Starting for {target_date}")

    # L1: 数据获取
    try:
        logger.info("[L1] Starting data fetch")
        fetch.fetch_all_indicators(target_date)
        fetch.l1_completion_assert(target_date)
        logger.info("[L1] Completed")
    except fetch.FatalError as e:
        logger.error(f"[L1] FATAL: {e}")
        push_deep.send_error_notification(target_date, "L1", "FatalError", str(e))
        return
    except Exception as e:
        logger.error(f"[L1] ERROR: {e}", exc_info=True)
        push_deep.send_error_notification(target_date, "L1", type(e).__name__, str(e))
        return

    # L2: 分析
    try:
        logger.info("[L2] Starting analysis")
        payload = analysis.run_analysis(target_date)
        logger.info("[L2] Completed")
    except Exception as e:
        logger.error(f"[L2] ERROR: {e}", exc_info=True)
        push_deep.send_error_notification(target_date, "L2", type(e).__name__, str(e))
        return

    # L3_DEEP: 深度报告
    try:
        logger.info("[L3_DEEP] Starting deep report")
        qualitative_context = payload.get("qualitative_context", {})
        prev_signal = get_prev_signal(target_date)
        llm_sections = push_deep.generate_deep_report(payload, qualitative_context, prev_signal)
        push_deep.send_deep_report(payload, llm_sections)

        from datetime import datetime
        message = push_deep.assemble_deep_report(payload, qualitative_context, llm_sections)
        db.update_report(
            date=target_date,
            content=message,
            sent_at=datetime.now().isoformat(),
            send_status="success"
        )
        logger.info("[L3_DEEP] Completed and report saved")
    except push_deep.LLMOutputError as e:
        logger.error(f"[L3_DEEP] LLM output validation failed: {e}")
        push_deep.send_error_notification(target_date, "L3_DEEP", "LLMOutputError", str(e))
    except Exception as e:
        logger.error(f"[L3_DEEP] ERROR: {e}", exc_info=True)
        try:
            db.update_report(date=target_date, content="", send_status="failed")
        except:
            pass
        push_deep.send_error_notification(target_date, "L3_DEEP", type(e).__name__, str(e))

    logger.info(f"[PIPELINE/WEEKLY] Done for {target_date}")


def run_event_alert(target_date=None):
    """事件触发：检查条件 → L3_ALERT"""
    if target_date is None:
        target_date = date.today().isoformat()

    logger.info(f"[PIPELINE/ALERT] Starting for {target_date}")

    # L1: 数据获取
    try:
        logger.info("[L1] Starting data fetch")
        fetch.fetch_all_indicators(target_date)
        fetch.l1_completion_assert(target_date)
        logger.info("[L1] Completed")
    except fetch.FatalError as e:
        logger.error(f"[L1] FATAL: {e}")
        return
    except Exception as e:
        logger.error(f"[L1] ERROR: {e}", exc_info=True)
        return

    # L2: 分析
    try:
        logger.info("[L2] Starting analysis")
        payload = analysis.run_analysis(target_date)
        logger.info("[L2] Completed")
    except Exception as e:
        logger.error(f"[L2] ERROR: {e}", exc_info=True)
        return

    # 检查预警条件
    prev_signal = get_prev_signal(target_date)
    triggered = push_alert.check_alert_conditions(payload, prev_signal)

    if not triggered:
        logger.info(f"[PIPELINE/ALERT] No conditions triggered for {target_date}")
        return

    logger.info(f"[PIPELINE/ALERT] Triggered: {triggered}")

    # L3_ALERT: 发送预警
    try:
        qualitative_context = payload.get("qualitative_context", {})
        llm_content = push_alert.generate_alert(triggered, payload, qualitative_context)
        push_alert.send_alert(triggered, payload, llm_content)

        from datetime import datetime
        message = push_alert.assemble_alert(triggered, payload, llm_content)
        db.update_report(
            date=target_date,
            content=message,
            sent_at=datetime.now().isoformat(),
            send_status="success"
        )
        logger.info("[L3_ALERT] Alert sent and saved")
    except Exception as e:
        logger.error(f"[L3_ALERT] ERROR: {e}", exc_info=True)
        try:
            db.update_report(date=target_date, content="", send_status="failed")
        except:
            pass

    logger.info(f"[PIPELINE/ALERT] Done for {target_date}")


def get_prev_signal(target_date_str):
    """获取上一个工作日的signal"""
    target = date.fromisoformat(target_date_str)
    for days_back in range(1, 8):
        prev_date = (target - timedelta(days=days_back)).isoformat()
        _, signal = db.get_signal(prev_date)
        if signal:
            return signal
    return None


def send_error_notification(date_str, phase, error_type, error_message):
    """通用错误通知"""
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
        from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
        async def _send():
            bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
            await bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=msg)
        asyncio.run(_send())
    except Exception as e:
        print(f"[send_error_notification] failed: {e}\n{msg}")


if __name__ == "__main__":
    db.init_db()
    mode = sys.argv[1] if len(sys.argv) > 1 else "daily"
    target = sys.argv[2] if len(sys.argv) > 2 else None

    if mode == "daily":
        run_daily_silent(target)
    elif mode == "weekly":
        run_weekly_deep(target)
    elif mode == "alert":
        run_event_alert(target)
    else:
        print(f"Unknown mode: {mode}. Use: daily | weekly | alert")
