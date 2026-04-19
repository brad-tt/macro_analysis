"""
宏观分析系统配置
"""
import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    # API Keys - 稍后补充
    telegram_token: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    fred_api_key: Optional[str] = None  # FRED 可选，部分数据无需 key

    # Claude Model
    claude_model: str = "claude-opus-4-6"

    # 调度时间 (北京时间)
    daily_push_hour: int = 8
    daily_push_minute: int = 0

    # 数据源
    use_vix: bool = True
    use_ted_spread: bool = True

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN"),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            fred_api_key=os.getenv("FRED_API_KEY"),
        )


# 全局配置实例
config = Config.from_env()
