"""
Claude API 报告生成器
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False


class ReportGenerator:
    """
    使用 Claude API 生成宏观分析报告

    需要设置环境变量 ANTHROPIC_API_KEY 或在 config 中配置。
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-opus-4-6"):
        self.api_key = api_key
        self.model = model
        self.client = None

        if api_key and ANTHROPIC_AVAILABLE:
            self.client = Anthropic(api_key=api_key)
        elif not ANTHROPIC_AVAILABLE:
            logger.warning("anthropic not available, install with: pip install anthropic")

    def generate(self, data_summary: str, date: Optional[str] = None) -> Optional[str]:
        """
        生成宏观分析报告

        Args:
            data_summary: 格式化后的宏观数据摘要
            date: 分析日期

        Returns:
            生成的报告文本，失败返回 None
        """
        if not self.client:
            logger.error("Claude client not initialized. Set ANTHROPIC_API_KEY environment variable.")
            return None

        if date is None:
            date = datetime.now().strftime("%Y年%m月%d日")

        # 导入提示词模板
        from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE

        user_prompt = USER_PROMPT_TEMPLATE.format(
            date=date,
            data_summary=data_summary
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[
                    {
                        "role": "user",
                        "content": user_prompt
                    }
                ]
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Failed to generate report: {e}")
            return None

    def generate_with_retry(self, data_summary: str, date: Optional[str] = None, max_retries: int = 3) -> Optional[str]:
        """带重试的报告生成"""
        for attempt in range(max_retries):
            result = self.generate(data_summary, date)
            if result:
                return result
            logger.warning(f"Report generation attempt {attempt + 1} failed, retrying...")
        return None
