"""
Telegram Bot 推送模块
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from telegram import Bot
    from telegram.constants import ParseMode
    TELEGRAM_AVAILABLE = True
except ImportError:
    TELEGRAM_AVAILABLE = False
    Bot = None


class TelegramPusher:
    """
    Telegram Bot 推送器

    用于将宏观分析报告推送到 Telegram。

    使用方式：
    1. 先通过 @BotFather 创建 Bot，获取 token
    2. 通过 @userinfobot 获取你的 chat_id
    3. 设置环境变量 TELEGRAM_BOT_TOKEN 和 TELEGRAM_CHAT_ID
    """

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token
        self.chat_id = chat_id
        self.bot = None

        if token and TELEGRAM_AVAILABLE:
            self.bot = Bot(token=token)
        elif not TELEGRAM_AVAILABLE:
            logger.warning("python-telegram-bot not available, install with: pip install python-telegram-bot")

    def send_text(self, text: str, chat_id: Optional[str] = None) -> bool:
        """
        发送文本消息

        Args:
            text: 消息内容
            chat_id: 可选，覆盖默认 chat_id

        Returns:
            是否发送成功
        """
        if not self.bot:
            logger.error("Telegram bot not initialized. Set TELEGRAM_BOT_TOKEN environment variable.")
            return False

        target_chat_id = chat_id or self.chat_id
        if not target_chat_id:
            logger.error("No chat_id specified")
            return False

        try:
            # Telegram 消息长度限制 4096 字符
            if len(text) > 4096:
                # 分段发送
                for i in range(0, len(text), 4096):
                    chunk = text[i:i + 4096]
                    self.bot.send_message(
                        chat_id=target_chat_id,
                        text=chunk,
                        parse_mode=ParseMode.MARKDOWN
                    )
            else:
                self.bot.send_message(
                    chat_id=target_chat_id,
                    text=text,
                    parse_mode=ParseMode.MARKDOWN
                )
            return True

        except Exception as e:
            logger.error(f"Failed to send telegram message: {e}")
            return False

    def send_report(self, report: str, chat_id: Optional[str] = None) -> bool:
        """
        发送分析报告

        Args:
            report: 报告内容
            chat_id: 可选，覆盖默认 chat_id

        Returns:
            是否发送成功
        """
        # 添加报告头部
        from datetime import datetime
        header = f"📊 **每日宏观分析** | {datetime.now().strftime('%Y-%m-%d')}\n\n"

        return self.send_text(header + report, chat_id)

    def send_health_check(self, message: str = "✅ 宏观分析系统运行正常") -> bool:
        """发送健康检查消息"""
        from datetime import datetime
        return self.send_text(f"🩺 *健康检查* | {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n{message}")


class TelegramBotManager:
    """Telegram Bot 管理器（用于交互式 Bot）"""

    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.bot = None

        if token and TELEGRAM_AVAILABLE:
            self.bot = Bot(token=token)

    async def send_message(self, chat_id: str, text: str) -> bool:
        """异步发送消息"""
        if not self.bot:
            return False

        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            return False
