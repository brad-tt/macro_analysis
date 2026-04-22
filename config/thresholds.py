# config/thresholds.py — 硬编码魔法数字集中管理
# 使用方式：from config.thresholds import CYCLE_THRESHOLDS, DXY_THRESHOLDS, ENERGY_THRESHOLDS, GOLD_THRESHOLDS, FED_THRESHOLDS

CYCLE_THRESHOLDS = {
    # expansion 状态
    "pmi_expansion":           50,      # PMI > 50 视为扩张
    "vix_expansion":           20,      # VIX < 20 视为低波动扩张
    "hy_spread_delta_20d_sign": 0,      # HY利差20日变化 < 0 则信用改善

    # overheating 状态
    "cpi_overheating":          3.0,     # CPI YoY > 3% 过热
    "tips_5d_positive":         0.0,     # TIPS 5日变化 > 0 说明实际利率上行
    "spread_2_10_flat_threshold": 0.5, # |2-10利差| < 0.5% 曲线平坦过热
    "wti_overheating":          80,     # WTI > $80 过热

    # recession 状态
    "inversion_days_recession": 60,     # 曲线倒挂超60天
    "pmi_recession":            48,     # PMI < 48 衰退风险
    "hy_spread_recession":     5.0,   # HY利差 > 5% (500bp) 高收益债压力
    "vix_recession":            25,     # VIX > 25 恐慌

    # recovery 状态
    "spread_2_10_delta_recovery": 0.3,  # 2-10利差60日变化 > 0.3% 曲线陡化复苏
    "pmi_delta_recovery":        2,      # PMI 20日变化 > 2 制造业反弹
    "tips_5d_recovery_negative": -0.05, # TIPS 5日变化 < -0.05% 实际利率下行宽松
}

FED_THRESHOLDS = {
    # TIPS 5日变化 → fed_score
    "tips_positive_major":      0.15,   # > +0.15% → score -2（鹰派紧缩）
    "tips_positive_minor":      0.05,   # > +0.05% → score -1
    "tips_negative_major":     -0.15,   # < -0.15% → score +2（鸽派宽松）
    "tips_negative_minor":     -0.05,   # < -0.05% → score +1
    # anomaly: 实际利率上行 + FOMC偏鸽 → 政策失效信号
    "anomaly_yield_policy_inversion_tips": 0.10,
}

DTWEX_THRESHOLDS = {
    # DTWEXBGS → score（广义贸易加权美元指数）
    "dxy_strong":               108,    # DTWEXBGS > 108 → score -2（强美元压制）
    "dxy_moderate_high":       104,    # DTWEXBGS > 104 → score -1
    "dxy_moderate_low":        101,    # DTWEXBGS < 101 → score +1
    "dxy_weak":                97,     # DTWEXBGS < 97 → score +2（弱美元宽松）
    # EM 压力触发
    "em_pressure_dxy":          105,    # DXY > 105 + trend > 2% → EM压力
    "em_pressure_trend":        2.0,    # DXY 20日变化 > 2%
    # CN 利差（v3）
    "cny_pressure_spread":     -1.0,   # CN-US 10Y利差 < -1% 资本外流压力
    "cny_weakening_rate":      1.005, # USDCNY 20日变化 > 0.5% 人民币走弱
}

ENERGY_THRESHOLDS = {
    # 滞胀标志
    "wti_stagflation":          90,     # WTI > $90
    "cpi_yoy_stagflation":      3.5,   # CPI YoY > 3.5%
    "pmi_stagflation":          50,    # PMI < 50 制造业萎缩
    # 油价传导时滞评分
    "oil_lag_positive_major":   15,    # WTI 20日变化 > +$15 → score +2
    "oil_lag_positive_minor":    5,    # WTI 20日变化 > +$5 → score +1
    "oil_lag_negative_major":  -15,    # WTI 20日变化 < -$15 → score -2
    "oil_lag_negative_minor":   -5,    # WTI 20日变化 < -$5 → score -1
    # 能量 divergence
    "wti_divergence_delta":      5,    # WTI 20日变化 > $5 但 XLE < 0
    # WTI → energy_score
    "wti_bearish_low":          70,    # WTI < $70 → score +2（低油价宽松）
    "wti_bearish_high":         85,    # WTI < $85 → score +1
    "wti_neutral":              95,    # WTI < $95 → score -1
    "wti_bullish":              95,    # WTI >= $95 → score -2（高油价压制）
}

GOLD_THRESHOLDS = {
    # gold_driver 判断
    "realrate_corr_anomaly":    0.2,   # |corr(GOLD,DFII10)| > 0.2 → CB buying
    "vix_haven":                28,    # VIX > 28 + gold 5d > 2% → haven
    "dxy_corr_strong":         0.5,   # |corr(GOLD,DXY)| > 0.5 → DXY driver
    # TIPS → gold_score
    "tips_negative":           0,     # TIPS < 0% → score +2
    "tips_positive_low":       1.0,   # TIPS < 1% → score +1
    "tips_positive_high":      2.0,   # TIPS < 2% → score -1; >= 2% → score -2
}