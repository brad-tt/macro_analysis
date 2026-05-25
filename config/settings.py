import os
from dotenv import load_dotenv

load_dotenv()

FRED_API_KEY = os.environ.get("FRED_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.environ.get("ANTHROPIC_BASE_URL", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
LLM_API_KEY = os.environ.get("LLM_API_KEY") or DEEPSEEK_API_KEY or ANTHROPIC_API_KEY
LLM_BASE_URL = os.environ.get("LLM_BASE_URL") or ANTHROPIC_BASE_URL
LLM_MODEL = os.environ.get("LLM_MODEL") or ANTHROPIC_MODEL
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# OpenBB MCP Server 配置（可选）
OPENBB_MCP_HOST = os.environ.get("OPENBB_MCP_HOST", "127.0.0.1")
OPENBB_MCP_PORT = int(os.environ.get("OPENBB_MCP_PORT", "8001"))

DB_PATH = os.environ.get("DB_PATH", "./data/macro_data.db")
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
