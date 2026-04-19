"""
调度器 - 三个任务
  1. 每日 05:30 (工作日) 静默运行 L1+L2
  2. 每周一 06:00 深度报告 L1+L2+L3_DEEP
  3. 每日 06:05 检查事件触发条件 L3_ALERT
保持运行: python scheduler.py
"""
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import subprocess
import logging
import os

log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(log_dir, "scheduler.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

scheduler = BlockingScheduler(timezone="Asia/Shanghai")


def run_script(script_name, *args):
    result = subprocess.run(
        ["python", script_name] + list(args),
        capture_output=True,
        text=True,
        cwd=os.path.dirname(__file__)
    )
    logging.info(result.stdout)
    if result.returncode != 0:
        logging.error(result.stderr)


# 每日 05:30 静默运行
scheduler.add_job(
    lambda: run_script("pipeline.py", "daily"),
    CronTrigger(day_of_week="mon-fri", hour=5, minute=30),
    id="daily_silent",
    misfire_grace_time=3600
)

# 每周一 06:00 深度报告
scheduler.add_job(
    lambda: run_script("pipeline.py", "weekly"),
    CronTrigger(day_of_week="mon", hour=6, minute=0),
    id="weekly_deep",
    misfire_grace_time=3600
)

# 每日 06:05 事件预警检查
scheduler.add_job(
    lambda: run_script("pipeline.py", "alert"),
    CronTrigger(day_of_week="mon-fri", hour=6, minute=5),
    id="event_alert",
    misfire_grace_time=3600
)


if __name__ == "__main__":
    import db
    db.init_db()
    logging.info("Scheduler started (3 jobs registered)")
    scheduler.start()
