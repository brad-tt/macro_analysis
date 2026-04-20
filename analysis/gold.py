"""L2.5 黄金模块 — v3 更新：DXY 而非 DTWEXBGS"""
from analysis.utils import _v, query_db_n_days_ago, rolling_correlation
from config.thresholds import GOLD_THRESHOLDS as GT

def compute_gold(data):
    gold = _v(data, "GOLD")
    tips = _v(data, "DFII10")
    dxy  = _v(data, "DXY")
    vix  = _v(data, "VIXCLS")

    gold_realrate_corr = rolling_correlation("GOLD", "DFII10", window=30)
    gold_dxy_corr      = rolling_correlation("GOLD", "DXY", window=30)

    anomaly_gold_realrate_decorrelation = gold_realrate_corr > GT["realrate_corr_anomaly"]

    gold_5d_ago = query_db_n_days_ago("GOLD", 5)
    gold_5d_return = ((gold - gold_5d_ago) / gold_5d_ago) if (gold is not None and gold_5d_ago) else 0.0

    if anomaly_gold_realrate_decorrelation:
        gold_driver = "cb_buying"
    elif vix is not None and vix > GT["vix_haven"] and gold_5d_ago and gold and gold > gold_5d_ago * 1.02:
        gold_driver = "haven"
    elif abs(gold_dxy_corr) > GT["dxy_corr_strong"]:
        gold_driver = "dxy"
    else:
        gold_driver = "real_rate"

    if tips is None:
        gold_score = 0
    elif tips < 0:
        gold_score = 2
    elif tips < GT["tips_positive_low"]:
        gold_score = 1
    elif tips < GT["tips_positive_high"]:
        gold_score = -1
    else:
        gold_score = -2

    return {
        "gold":                                round(gold, 2) if gold is not None else None,
        "gold_realrate_corr_30d":             round(gold_realrate_corr, 4),
        "gold_dxy_corr_30d":                  round(gold_dxy_corr, 4),
        "anomaly_gold_realrate_decorrelation": anomaly_gold_realrate_decorrelation,
        "gold_driver":                         gold_driver,
        "gold_score":                          gold_score
    }