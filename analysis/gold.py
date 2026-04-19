"""L2.5 黄金模块"""
import db
import numpy as np
from datetime import date, timedelta

def _v(d, key):
    item = d.get(key)
    if item is None:
        return None
    return item.get("value") if isinstance(item, dict) else None

def compute_gold(data):
    gold = _v(data, "GOLD")
    tips = _v(data, "DFII10")
    dxy  = _v(data, "DTWEXBGS")
    vix  = _v(data, "VIXCLS")

    gold_realrate_corr = rolling_correlation("GOLD", "DFII10", window=30)
    gold_dxy_corr      = rolling_correlation("GOLD", "DTWEXBGS", window=30)

    anomaly_gold_realrate_decorrelation = gold_realrate_corr > 0.2

    gold_5d_ago = query_db_n_days_ago("GOLD", 5)
    gold_5d_return = ((gold - gold_5d_ago) / gold_5d_ago) if (gold is not None and gold_5d_ago) else 0.0

    if anomaly_gold_realrate_decorrelation:
        gold_driver = "cb_buying"
    elif vix is not None and vix > 28 and gold_5d_ago and gold and gold > gold_5d_ago * 1.02:
        gold_driver = "haven"
    elif abs(gold_dxy_corr) > 0.5:
        gold_driver = "dxy"
    else:
        gold_driver = "real_rate"

    if tips is None:
        gold_score = 0
    elif tips < 0:       gold_score = 2
    elif tips < 1.0:     gold_score = 1
    elif tips < 2.0:     gold_score = -1
    else:                gold_score = -2

    return {
        "gold":                                round(gold, 2) if gold is not None else None,
        "gold_realrate_corr_30d":             round(gold_realrate_corr, 4),
        "gold_dxy_corr_30d":                  round(gold_dxy_corr, 4),
        "anomaly_gold_realrate_decorrelation": anomaly_gold_realrate_decorrelation,
        "gold_driver":                         gold_driver,
        "gold_score":                          gold_score
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
