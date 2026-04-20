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
import signal
import sys

log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)

logging.basicConfig(
    filename=os.path.join(log_dir, "scheduler.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)

logger = logging.getLogger(__name__)

# ── OpenBB MCP Server 管理 ──────────────────────────────────────
MCP_PID_FILE = os.path.join(log_dir, "openbb_mcp.pid")


def start_openbb_mcp():
    """启动 OpenBB MCP Server（若未运行）"""
    try:
        # 检查是否已有 MCP Server 在运行
        if os.path.exists(MCP_PID_FILE):
            with open(MCP_PID_FILE) as f:
                old_pid = f.read().strip()
            try:
                os.kill(int(old_pid), 0)  # 检查进程是否存在
                logger.info(f"[MCP] Server already running (PID {old_pid})")
                return
            except (OSError, ProcessLookupError):
                logger.info("[MCP] Stale PID file, will restart")

        # 检查端口是否可用
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        result = sock.connect_ex(("127.0.0.1", 8001))
        sock.close()
        if result == 0:
            logger.info("[MCP] Port 8001 already in use, assuming MCP server running")
            return

        # 启动 MCP Server
        logger.info("[MCP] Starting OpenBB MCP Server on port 8001...")
        proc = subprocess.Popen(
            ["python", "-m", "openbb_mcp", "--transport", "streamable-http", "--host", "127.0.0.1", "--port", "8001"],
            stdout=open(os.path.join(log_dir, "mcp_server.log"), "w"),
            stderr=subprocess.STDOUT,
            cwd=os.path.dirname(__file__),
        )
        with open(MCP_PID_FILE, "w") as f:
            f.write(str(proc.pid))
        logger.info(f"[MCP] Started with PID {proc.pid}")
    except FileNotFoundError:
        logger.warning("[MCP] openbb-mcp not found in PATH, skipping MCP server startup (non-fatal)")
    except Exception as e:
        logger.warning(f"[MCP] Failed to start: {e} (non-fatal, pipeline uses OpenBB Python API directly)")


def stop_openbb_mcp():
    """停止 OpenBB MCP Server"""
    try:
        if os.path.exists(MCP_PID_FILE):
            with open(MCP_PID_FILE) as f:
                pid = int(f.read().strip())
            os.kill(pid, signal.SIGTERM)
            os.remove(MCP_PID_FILE)
            logger.info(f"[MCP] Stopped PID {pid}")
    except Exception as e:
        logger.warning(f"[MCP] Stop error: {e}")


# 启动时尝试启动 MCP Server（不阻塞）
start_openbb_mcp()

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


def shutdown_handler(signum, frame):
    logger.info("Scheduler shutting down...")
    stop_openbb_mcp()
    scheduler.shutdown(wait=False)


if __name__ == "__main__":
    import db
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)
    db.init_db()
    logging.info("Scheduler started (3 jobs registered)")
    scheduler.start()
