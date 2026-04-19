#!/usr/bin/env python3
"""
每日宏观分析系统

用法:
    python main.py              # 运行一次分析
    python main.py --scheduler  # 启动定时调度
    python main.py --help       # 查看帮助
"""
import argparse
import logging
import os
import sys

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config
from data.fred_client import FredClient
from data.yahoo_client import YahooFinanceClient
from data.indicators import MacroIndicatorCalculator
from analysis.report_generator import ReportGenerator
from delivery.telegram_bot import TelegramPusher
from scheduler.jobs import MacroAnalysisJob, run_scheduler

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def run_once():
    """运行一次分析"""
    # 初始化组件
    fred_client = FredClient(api_key=config.fred_api_key)
    yahoo_client = YahooFinanceClient()
    calculator = MacroIndicatorCalculator()
    report_generator = ReportGenerator(api_key=config.anthropic_api_key, model=config.claude_model)
    pusher = TelegramPusher(token=config.telegram_token)

    # 创建任务
    job = MacroAnalysisJob(
        fred_client=fred_client,
        yahoo_client=yahoo_client,
        calculator=calculator,
        report_generator=report_generator,
        pusher=pusher
    )

    # 执行
    job.run()


def run_scheduled():
    """运行定时调度"""
    # 初始化组件
    fred_client = FredClient(api_key=config.fred_api_key)
    yahoo_client = YahooFinanceClient()
    calculator = MacroIndicatorCalculator()
    report_generator = ReportGenerator(api_key=config.anthropic_api_key, model=config.claude_model)
    pusher = TelegramPusher(token=config.telegram_token)

    # 创建任务
    job = MacroAnalysisJob(
        fred_client=fred_client,
        yahoo_client=yahoo_client,
        calculator=calculator,
        report_generator=report_generator,
        pusher=pusher
    )

    # 运行调度
    run_scheduler(job, hour=config.daily_push_hour, minute=config.daily_push_minute)


def check_config():
    """检查配置"""
    missing = []

    if not config.telegram_token:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not config.anthropic_api_key:
        missing.append("ANTHROPIC_API_KEY")
    if not config.fred_api_key:
        missing.append("FRED_API_KEY (可选，部分数据可正常获取)")

    if missing:
        print("⚠️  缺少以下环境变量:")
        for var in missing:
            print(f"   - {var}")
        print("\n请在 .env 文件或环境中设置这些变量")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="每日宏观分析系统")
    parser.add_argument("--scheduler", action="store_true", help="启动定时调度")
    parser.add_argument("--check", action="store_true", help="检查配置")
    args = parser.parse_args()

    if args.check:
        return 0 if check_config() else 1

    if args.scheduler:
        if not check_config():
            return 1
        run_scheduled()
    else:
        # 不强制检查配置，允许测试数据层
        run_once()

    return 0


if __name__ == "__main__":
    sys.exit(main())
