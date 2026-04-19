"""L2 共享工具函数"""
from datetime import date, timedelta
import db


def _v(d, key):
    """安全获取指标值"""
    item = d.get(key) if isinstance(d, dict) else None
    if item is None:
        return None
    return item.get("value") if isinstance(item, dict) else None


def query_db_n_days_ago(series_id, n):
    """从数据库查询N天前的指标值（自动跳过周末/假日回溯）"""
    target = date.today() - timedelta(days=n)
    rows = db.get_latest_indicator_before(series_id, target.isoformat(), limit=1)
    return rows[0]["value"] if rows else None


def rolling_correlation(series_a, series_b, window=30):
    """计算两个指标序列的滚动相关性"""
    import numpy as np
    today = date.today().isoformat()
    conn = db.get_conn()
    c = conn.cursor()
    c.execute(
        f"SELECT value FROM daily_indicators WHERE series_id=? AND date <= ? ORDER BY date DESC LIMIT ?",
        (series_a, today, window)
    )
    a_vals = [r["value"] for r in c.fetchall()]
    c.execute(
        f"SELECT value FROM daily_indicators WHERE series_id=? AND date <= ? ORDER BY date DESC LIMIT ?",
        (series_b, today, window)
    )
    b_vals = [r["value"] for r in c.fetchall()]
    conn.close()
    if len(a_vals) < 10 or len(b_vals) < 10:
        return 0.0
    a_vals = list(reversed(a_vals))
    b_vals = list(reversed(b_vals))
    min_len = min(len(a_vals), len(b_vals))
    if min_len < 10:
        return 0.0
    corr = np.corrcoef(a_vals[-min_len:], b_vals[-min_len:])[0, 1]
    return float(corr) if not np.isnan(corr) else 0.0
