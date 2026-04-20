"""L2 共享工具函数"""
from datetime import date, timedelta
import db

_PIVOT_CACHE = None  # 模块级 pivot 表缓存


def init_pivot_cache(end_date_str, window=45):
    """预加载 pivot 缓存，避免 rolling_correlation 每次重复查询数据库"""
    global _PIVOT_CACHE
    _PIVOT_CACHE = db.get_historical_pivot_df(end_date_str, window)


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
    """计算两个指标序列的滚动相关性
    优先使用预加载的 pivot 缓存，缓存为空则 fallback 到 SQL 查询"""
    import numpy as np

    if _PIVOT_CACHE is not None and not _PIVOT_CACHE.empty:
        # 从缓存中提取两列，截取最近 window 天，去 NaN
        cols = [c for c in [series_a, series_b] if c in _PIVOT_CACHE.columns]
        if len(cols) == 2:
            sub = _PIVOT_CACHE[cols].dropna().tail(window)
            if len(sub) >= 10:
                corr = sub[series_a].corr(sub[series_b])
                return float(corr) if not np.isnan(corr) else 0.0

    # Fallback：原始 SQL 查询（保证兼容性）
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
