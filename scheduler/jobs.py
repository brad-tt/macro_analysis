"""
定时任务调度器
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger
    APSCHEDULER_AVAILABLE = True
except ImportError:
    APSCHEDULER_AVAILABLE = False
    BlockingScheduler = None


class MacroAnalysisJob:
    """
    宏观分析定时任务

    负责协调数据获取、报告生成、推送发送的完整流程。
    """

    def __init__(self,
                 fred_client,
                 yahoo_client,
                 calculator,
                 report_generator,
                 pusher):
        self.fred_client = fred_client
        self.yahoo_client = yahoo_client
        self.calculator = calculator
        self.report_generator = report_generator
        self.pusher = pusher

    def run(self):
        """执行一次完整的宏观分析流程"""
        logger.info("Starting macro analysis job...")

        try:
            # 1. 获取数据
            logger.info("Fetching data...")
            bond_data, sentiment_data = self.fred_client.get_all_data()
            stock_data, energy_data, forex_data, metals_data = self.yahoo_client.get_all_data()

            # 2. 计算指标
            logger.info("Calculating indicators...")
            indicators = self.calculator.calculate(
                bond_data, sentiment_data, stock_data,
                energy_data, forex_data, metals_data
            )

            # 3. 格式化数据
            data_summary = self.calculator.format_for_prompt(
                bond_data, sentiment_data, stock_data,
                energy_data, forex_data, metals_data,
                indicators
            )

            # 4. 生成报告
            logger.info("Generating report...")
            report = self.report_generator.generate(data_summary)

            if not report:
                logger.error("Failed to generate report")
                self.pusher.send_text("❌ 报告生成失败，请检查 API 配置")
                return

            # 5. 推送报告
            logger.info("Sending report...")
            success = self.pusher.send_report(report)

            if success:
                logger.info("Macro analysis job completed successfully")
            else:
                logger.error("Failed to send report")

        except Exception as e:
            logger.error(f"Macro analysis job failed: {e}")
            self.pusher.send_text(f"❌ 宏观分析任务失败: {str(e)}")


def create_scheduler(job: MacroAnalysisJob, hour: int = 8, minute: int = 0):
    """
    创建调度器

    Args:
        job: MacroAnalysisJob 实例
        hour: 每日执行小时 (北京时间)
        minute: 每日执行分钟

    Returns:
        BlockingScheduler 实例
    """
    if not APSCHEDULER_AVAILABLE:
        raise ImportError("APScheduler not available. Install with: pip install apscheduler")

    scheduler = BlockingScheduler()

    # 使用 CronTrigger 设置每日定时任务
    # 注意：APScheduler 使用本地时区，默认北京时间 UTC+8
    scheduler.add_job(
        job.run,
        CronTrigger(hour=hour, minute=minute),
        id='daily_macro_analysis',
        name='每日宏观分析',
        replace_existing=True
    )

    logger.info(f"Scheduler created. Daily run time: {hour:02d}:{minute:02d} (本地时间)")

    return scheduler


def run_scheduler(job: MacroAnalysisJob, hour: int = 8, minute: int = 0):
    """运行调度器（阻塞）"""
    scheduler = create_scheduler(job, hour, minute)

    try:
        logger.info("Starting scheduler...")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")
        scheduler.shutdown()
