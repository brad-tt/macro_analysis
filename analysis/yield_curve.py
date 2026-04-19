"""L2.1 收益率曲线模块"""
import math
import db
from datetime import date, timedelta

def _v(d, key):
    """安全获取指标值，缺失返回 None"""
    item = d.get(key)
    if item is None:
        return None
    return item.get("value") if isinstance(item, dict) else None

def compute_yield_curve(data):
    dgs10  = _v(data, "DGS10")
    dgs2   = _v(data, "DGS2")
    dgs3mo = _v(data, "DGS3MO")

    if dgs10 is None or dgs2 is None or dgs3mo is None:
        # P0 缺失，降级处理
        return {
            "spread_2_10":        None,
            "spread_10_3m":       None,
            "inversion_days":     0,
            "recession_prob_12m": 0.5,
            "term_premium":       None,
            "curve_score":        0
        }

    spread_2_10  = dgs10 - dgs2
    spread_10_3m = dgs10 - dgs3mo

    inversion_days = count_consecutive_inversion_days(dgs10, dgs2)

    three_mo_avg = dgs3mo
    recession_prob_12m = 1 / (1 + math.exp(-(
        -0.6045 + (-0.0045 * three_mo_avg) +
        (-0.1861 * spread_10_3m * 100)
    )))

    curve_score = classify_curve_score(spread_2_10)

    return {
        "spread_2_10":        round(spread_2_10, 4),
        "spread_10_3m":       round(spread_10_3m, 4),
        "inversion_days":     inversion_days,
        "recession_prob_12m": round(recession_prob_12m, 4),
        "term_premium":       None,  # NSS模型拟合占位，待接入 nelson_siegel_svensson
        "curve_score":        curve_score
    }

def classify_curve_score(spread_2_10):
    if spread_2_10 > 1.0:   return 2
    if spread_2_10 > 0.2:   return 1
    if spread_2_10 > -0.8:  return -1
    return -2

def count_consecutive_inversion_days(dgs10_today, dgs2_today):
    """从数据库读取历史数据，统计连续倒挂天数"""
    today = date.today().isoformat()
    conn = db.get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT date, value FROM daily_indicators
        WHERE series_id='DGS10' AND date <= ?
        ORDER BY date DESC LIMIT 120
    """, (today,))
    dgs10_rows = {r["date"]: r["value"] for r in c.fetchall()}
    c.execute("""
        SELECT date, value FROM daily_indicators
        WHERE series_id='DGS2' AND date <= ?
        ORDER BY date DESC LIMIT 120
    """, (today,))
    dgs2_rows = {r["date"]: r["value"] for r in c.fetchall()}
    conn.close()

    inversion_days = 0
    for d_str in sorted(dgs10_rows.keys(), reverse=True):
        if d_str in dgs2_rows:
            if dgs2_rows[d_str] > dgs10_rows[d_str]:
                inversion_days += 1
            else:
                break
    return inversion_days
