"""L2.2 联储政策模块"""
import db
import numpy as np
from datetime import date, timedelta

def _v(d, key):
    item = d.get(key)
    if item is None:
        return None
    return item.get("value") if isinstance(item, dict) else None

def compute_fed_policy(data):
    tips_10y   = _v(data, "DFII10")
    breakeven   = _v(data, "T10YIE")

    tips_5d_delta = None
    if tips_10y is not None:
        prev_tips = query_db_n_days_ago("DFII10", 5)
        if prev_tips is not None:
            tips_5d_delta = tips_10y - prev_tips

    dxy_realrate_corr = rolling_correlation("DTWEXBGS", "DFII10", window=30)

    if tips_5d_delta is None:
        fed_score = 0
    elif tips_5d_delta > 0.15:
        fed_score = -2
    elif tips_5d_delta > 0.05:
        fed_score = -1
    elif tips_5d_delta < -0.15:
        fed_score = 2
    elif tips_5d_delta < -0.05:
        fed_score = 1
    else:
        fed_score = 0

    anomaly_yield_policy_inversion = (
        tips_5d_delta is not None and tips_5d_delta > 0.10 and
        query_recent_fomc_stance() == "dovish"
    )

    return {
        "tips_5d_delta":          round(tips_5d_delta, 4) if tips_5d_delta is not None else None,
        "dxy_realrate_corr_30d": round(dxy_realrate_corr, 4),
        "fed_score":              fed_score,
        "anomaly_yield_policy_inversion": anomaly_yield_policy_inversion
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

def query_recent_fomc_stance():
    return "neutral"
