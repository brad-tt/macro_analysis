"""L2.3 美元指数模块"""
import db
import numpy as np
from datetime import date, timedelta

def _v(d, key):
    item = d.get(key)
    if item is None:
        return None
    return item.get("value") if isinstance(item, dict) else None

def compute_dxy(data):
    dxy = _v(data, "DTWEXBGS")

    dxy_20d_ago = query_db_n_days_ago("DTWEXBGS", 20)

    if dxy is not None and dxy_20d_ago:
        dxy_trend = (dxy - dxy_20d_ago) / dxy_20d_ago * 100
    else:
        dxy_trend = 0.0

    dxy_oil_corr  = rolling_correlation("DTWEXBGS", "DCOILWTICO", window=30)
    dxy_gold_corr = rolling_correlation("DTWEXBGS", "GOLD", window=30)

    em_pressure_flag = (dxy is not None) and (dxy > 105) and (dxy_trend > 2)

    if dxy is None:
        dxy_score = 0
    elif dxy > 108:       dxy_score = -2
    elif dxy > 104:        dxy_score = -1
    elif dxy < 97:        dxy_score = 2
    elif dxy < 101:        dxy_score = 1
    else:                  dxy_score = 0

    return {
        "dxy":                round(dxy, 2) if dxy is not None else None,
        "dxy_20d_change_pct": round(dxy_trend, 2),
        "dxy_oil_corr_30d":   round(dxy_oil_corr, 4),
        "dxy_gold_corr_30d":  round(dxy_gold_corr, 4),
        "em_pressure_flag":   em_pressure_flag,
        "dxy_score":          dxy_score
    }

def query_db_n_days_ago(series_id, n):
    target = date.today() - timedelta(days=n)
    rows = db.get_latest_indicator_before(series_id, target.isoformat(), limit=1)
    return rows[0]["value"] if rows else None

def rolling_correlation(series_a, series_b, window):
    today = date.today().isoformat()
    conn = db.get_conn()
    c = conn.cursor()
    c.execute(f"SELECT value FROM daily_indicators WHERE series_id=? AND date <= ? ORDER BY date DESC LIMIT ?",
              (series_a, today, window))
    a_vals = [r["value"] for r in c.fetchall()]
    c.execute(f"SELECT value FROM daily_indicators WHERE series_id=? AND date <= ? ORDER BY date DESC LIMIT ?",
              (series_b, today, window))
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
