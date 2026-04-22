"""L2.3 美元指数模块 — DTWEXBGS 广义贸易加权指数"""
from analysis.utils import _v, query_db_n_days_ago, rolling_correlation
from config.thresholds import DTWEX_THRESHOLDS as DT

def compute_dxy(data, base_date=None):
    # DTWEXBGS: 广义贸易加权美元指数（Broad Trade Weighted USD Index）
    # 覆盖全球数十个贸易伙伴，比6币种现货DXY更全面反映全球金融环境
    dtwex = _v(data, "DTWEXBGS")

    dtwex_20d_ago = query_db_n_days_ago("DTWEXBGS", 20, base_date=base_date)

    if dtwex is not None and dtwex_20d_ago:
        dtwex_trend = (dtwex - dtwex_20d_ago) / dtwex_20d_ago * 100
    else:
        dtwex_trend = 0.0

    dtwex_oil_corr   = rolling_correlation("DTWEXBGS", "WTI", window=30)
    dtwex_gold_corr  = rolling_correlation("DTWEXBGS", "GOLD", window=30)

    em_pressure_flag = (
        dtwex is not None and
        dtwex > DT["em_pressure_dxy"] and
        dtwex_trend > DT["em_pressure_trend"]
    )

    if dtwex is None:
        dtwex_score = 0
    elif dtwex > DT["dxy_strong"]:
        dtwex_score = -2
    elif dtwex > DT["dxy_moderate_high"]:
        dtwex_score = -1
    elif dtwex < DT["dxy_weak"]:
        dtwex_score = 2
    elif dtwex < DT["dxy_moderate_low"]:
        dtwex_score = 1
    else:
        dtwex_score = 0

    # ── 中美利差节点 ─────────────────────────────────────────────
    cn10y  = data.get("CN10Y",  {}).get("value") if isinstance(data.get("CN10Y"), dict) else None
    usdcny = data.get("USDCNY", {}).get("value") if isinstance(data.get("USDCNY"), dict) else None
    dgs10  = _v(data, "DGS10")

    cn_us_spread       = None
    cny_pressure_flag  = False
    cn_data_available  = (cn10y is not None and usdcny is not None)

    if cn_data_available and dgs10 is not None:
        cn_us_spread = round(cn10y - dgs10, 4)

        usdcny_20d    = query_db_n_days_ago("USDCNY", 20, base_date=base_date)
        cny_weakening = (usdcny > usdcny_20d * DT["cny_weakening_rate"]) if usdcny_20d else False

        # 中美利差扩大（<-1%）且人民币同步走弱 → 双重美元上行压力
        cny_pressure_flag = (cn_us_spread < DT["cny_pressure_spread"]) and cny_weakening

    # 返回字典 key 保持 "dxy" 前缀，与 payload 结构兼容
    return {
        "dxy":                 round(dtwex, 2) if dtwex is not None else None,
        "dxy_20d_change_pct":  round(dtwex_trend, 2),
        "dxy_oil_corr_30d":    round(dtwex_oil_corr, 4),
        "dxy_gold_corr_30d":   round(dtwex_gold_corr, 4),
        "em_pressure_flag":     em_pressure_flag,
        "dxy_score":           dtwex_score,
        "cn_us_10y_spread":    cn_us_spread,
        "usdcny":              usdcny,
        "cny_pressure_flag":   cny_pressure_flag,
        "cn_data_available":   cn_data_available,
    }
