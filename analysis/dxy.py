"""L2.3 美元指数模块"""
from analysis.utils import _v, query_db_n_days_ago, rolling_correlation

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
