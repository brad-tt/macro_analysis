"""L2.4 能源模块 — v3 更新：WTI 而非 DCOILWTICO"""
from datetime import date, timedelta
import db
from analysis.utils import _v, query_db_n_days_ago
from config.thresholds import ENERGY_THRESHOLDS as ET

def compute_energy(data, base_date=None):
    wti = _v(data, "WTI")  # v3: WTI (was DCOILWTICO)
    cpi_val = _v(data, "CPIAUCSL")
    vix = _v(data, "VIXCLS")

    wti_20d_ago = query_db_n_days_ago("WTI", 20, base_date=base_date)
    wti_20d_delta = (wti - wti_20d_ago) if (wti is not None and wti_20d_ago is not None) else 0.0

    # CPI 同比计算（需12个月前数据）
    cpi_yoy = None
    if cpi_val is not None:
        cpi_12m_ago = query_db_n_days_ago("CPIAUCSL", 365, base_date=base_date)
        if cpi_12m_ago and cpi_12m_ago > 0:
            cpi_yoy = (cpi_val - cpi_12m_ago) / cpi_12m_ago * 100
            # 合理性校验：CPI YoY 应在 -5% ~ 25% 之间
            if not (-5 <= cpi_yoy <= 25):
                import logging
                logging.warning(f"[energy] CPI YoY out of range: {cpi_yoy:.2f}%, cpi_val={cpi_val}, cpi_12m_ago={cpi_12m_ago}")
                cpi_yoy = None

    # 滞胀标志：WTI > $90 + CPI YoY > 3.5% + PMI < 50
    stagflation_flag = False
    if wti is not None and cpi_yoy is not None:
        pmi = query_latest_pmi()
        stagflation_flag = (
            wti > ET["wti_stagflation"] and
            cpi_yoy > ET["cpi_yoy_stagflation"] and
            pmi is not None and pmi < ET["pmi_stagflation"]
        )

    xle_20d_return = get_etf_return("XLE", 20)
    energy_divergence = (wti_20d_delta > ET["wti_divergence_delta"]) and (xle_20d_return < 0)

    # 油价传导时滞评分
    oil_cpi_lag_score = 0
    if wti is not None and wti_20d_delta is not None:
        if wti_20d_delta > ET["oil_lag_positive_major"]:
            oil_cpi_lag_score = 2
        elif wti_20d_delta > ET["oil_lag_positive_minor"]:
            oil_cpi_lag_score = 1
        elif wti_20d_delta < ET["oil_lag_negative_major"]:
            oil_cpi_lag_score = -2
        elif wti_20d_delta < ET["oil_lag_negative_minor"]:
            oil_cpi_lag_score = -1

    if wti is None:
        energy_score = 0
    elif wti < ET["wti_bearish_low"]:
        energy_score = 2
    elif wti < ET["wti_bearish_high"]:
        energy_score = 1
    elif wti < ET["wti_neutral"]:
        energy_score = -1
    else:
        energy_score = -2

    return {
        "wti":                   round(wti, 2) if wti is not None else None,
        "wti_20d_delta":         round(wti_20d_delta, 2),
        "cpi_latest":            round(cpi_yoy, 2) if cpi_yoy is not None else None,
        "oil_cpi_lag_score":     oil_cpi_lag_score,
        "stagflation_flag":      stagflation_flag,
        "energy_divergence_flag": energy_divergence,
        "energy_score":           energy_score
    }

def query_latest_pmi():
    """
    从 ism_pmi qualitative 数据源获取最新 PMI（爬取自 tradingeconomics.com）。
    FRED 的 MANUM 已于 2020-07 停止更新，不再使用。
    """
    import db as _db
    from datetime import date, timedelta
    try:
        pmi_data = _db.get_latest_qualitative("ism_pmi", last_n_days=7)
        if pmi_data and len(pmi_data) > 0:
            latest = pmi_data[0]
            val = latest.get("value")
            if val is not None:
                return round(float(val), 1)
    except Exception:
        pass

    try:
        from config.settings import FRED_API_KEY
        from openbb import obb
        if not FRED_API_KEY:
            return None
        obb.user.credentials.fred_api_key = FRED_API_KEY
        result = obb.economy.fred_series(symbol="MANUM", provider="fred",
                                        start_date=(date.today() - timedelta(days=60)).isoformat())
        df = result.to_df()
        if not df.empty:
            val = df["MANUM"].dropna().iloc[-1]
            return round(float(val), 1)
    except Exception:
        pass
    return None

def get_etf_return(ticker, days):
    """获取ETF从N天前到今天的收益率（%）"""
    from openbb import obb
    from datetime import timedelta
    end = date.today()
    start = end - timedelta(days=days + 5)
    try:
        result = obb.equity.price.historical(symbol=ticker, provider="yfinance",
                                             start_date=start.isoformat(), end_date=(end + timedelta(days=1)).isoformat())
        df = result.to_df()
        if df.empty or len(df) < 2:
            return 0.0
        prices = df["close"].dropna()
        if len(prices) < 2:
            return 0.0
        return (prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0] * 100
    except Exception:
        return 0.0