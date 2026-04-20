"""L2.3 美元指数模块 — v3 更新：补充中美利差节点"""
from analysis.utils import _v, query_db_n_days_ago, rolling_correlation
from config.thresholds import DXY_THRESHOLDS as DT

def compute_dxy(data, base_date=None):
    # v3 命名：DXY 而非 DTWEXBGS
    dxy = _v(data, "DXY")

    dxy_20d_ago = query_db_n_days_ago("DXY", 20, base_date=base_date)

    if dxy is not None and dxy_20d_ago:
        dxy_trend = (dxy - dxy_20d_ago) / dxy_20d_ago * 100
    else:
        dxy_trend = 0.0

    dxy_oil_corr  = rolling_correlation("DXY", "WTI", window=30)
    dxy_gold_corr = rolling_correlation("DXY", "GOLD", window=30)

    em_pressure_flag = (
        dxy is not None and
        dxy > DT["em_pressure_dxy"] and
        dxy_trend > DT["em_pressure_trend"]
    )

    if dxy is None:
        dxy_score = 0
    elif dxy > DT["dxy_strong"]:
        dxy_score = -2
    elif dxy > DT["dxy_moderate_high"]:
        dxy_score = -1
    elif dxy < DT["dxy_weak"]:
        dxy_score = 2
    elif dxy < DT["dxy_moderate_low"]:
        dxy_score = 1
    else:
        dxy_score = 0

    # ── 中美利差节点（v3 新增）──────────────────────────────────
    cn10y  = data.get("CN10Y",  {}).get("value") if isinstance(data.get("CN10Y"), dict) else None
    usdcny = data.get("USDCNY", {}).get("value") if isinstance(data.get("USDCNY"), dict) else None
    dgs10  = _v(data, "DGS10")

    cn_us_spread      = None
    cny_pressure_flag = False
    cn_data_available = (cn10y is not None and usdcny is not None)

    if cn_data_available and dgs10 is not None:
        cn_us_spread = round(cn10y - dgs10, 4)

        usdcny_20d    = query_db_n_days_ago("USDCNY", 20, base_date=base_date)
        cny_weakening = (usdcny > usdcny_20d * DT["cny_weakening_rate"]) if usdcny_20d else False

        # 中美利差扩大（<-1%）且人民币同步走弱 → 双重 DXY 上行压力
        cny_pressure_flag = (cn_us_spread < DT["cny_pressure_spread"]) and cny_weakening

    return {
        "dxy":                 round(dxy, 2) if dxy is not None else None,
        "dxy_20d_change_pct":  round(dxy_trend, 2),
        "dxy_oil_corr_30d":    round(dxy_oil_corr, 4),
        "dxy_gold_corr_30d":   round(dxy_gold_corr, 4),
        "em_pressure_flag":    em_pressure_flag,
        "dxy_score":           dxy_score,
        "cn_us_10y_spread":    cn_us_spread,
        "usdcny":              usdcny,
        "cny_pressure_flag":   cny_pressure_flag,
        "cn_data_available":   cn_data_available,
    }