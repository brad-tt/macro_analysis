"""L2.4 能源模块"""
import db
from datetime import date, timedelta

def _v(d, key):
    item = d.get(key)
    if item is None:
        return None
    return item.get("value") if isinstance(item, dict) else None

def compute_energy(data):
    wti = _v(data, "DCOILWTICO")
    cpi_val = _v(data, "CPIAUCSL")  # CPI 指数值
    vix = _v(data, "VIXCLS")

    wti_20d_ago = query_db_n_days_ago("DCOILWTICO", 20)
    wti_20d_delta = (wti - wti_20d_ago) if (wti is not None and wti_20d_ago is not None) else 0.0

    # CPI 同比计算（需12个月前数据）
    cpi_yoy = None
    if cpi_val is not None:
        cpi_12m_ago = query_db_n_days_ago("CPIAUCSL", 365)
        if cpi_12m_ago and cpi_12m_ago > 0:
            cpi_yoy = (cpi_val - cpi_12m_ago) / cpi_12m_ago * 100

    stagflation_flag = False
    if wti is not None and cpi_yoy is not None:
        pmi = query_latest_pmi()
        stagflation_flag = (wti > 90) and (cpi_yoy > 3.5) and (pmi is not None and pmi < 50)

    xle_20d_return = get_etf_return("XLE", 20)
    energy_divergence = (wti_20d_delta > 5) and (xle_20d_return < 0)

    # 油价传导时滞评分：WTI变动 → 4-6周后CPI响应
    # 基于 WTI 20d 变动幅度评估通胀传导压力
    oil_cpi_lag_score = 0
    if wti is not None and wti_20d_delta is not None:
        if wti_20d_delta > 15:    oil_cpi_lag_score = 2
        elif wti_20d_delta > 5:   oil_cpi_lag_score = 1
        elif wti_20d_delta < -15: oil_cpi_lag_score = -2
        elif wti_20d_delta < -5:  oil_cpi_lag_score = -1

    if wti is None:
        energy_score = 0
    elif wti < 70:       energy_score = 2
    elif wti < 85:       energy_score = 1
    elif wti < 95:       energy_score = -1
    else:                energy_score = -2

    return {
        "wti":                   round(wti, 2) if wti is not None else None,
        "wti_20d_delta":         round(wti_20d_delta, 2),
        "cpi_latest":            round(cpi_yoy, 2) if cpi_yoy is not None else None,
        "oil_cpi_lag_score":     oil_cpi_lag_score,
        "stagflation_flag":       stagflation_flag,
        "energy_divergence_flag": energy_divergence,
        "energy_score":           energy_score
    }

def query_db_n_days_ago(series_id, n):
    target = date.today() - timedelta(days=n)
    rows = db.get_latest_indicator_before(series_id, target.isoformat(), limit=1)
    return rows[0]["value"] if rows else None

def query_latest_pmi():
    return None

def get_etf_return(ticker, days):
    """获取ETF从N天前到今天的收益率（%）"""
    import yfinance as yf
    from datetime import timedelta
    end = date.today()
    start = end - timedelta(days=days + 5)
    try:
        obj = yf.Ticker(ticker)
        hist = obj.history(start=start, end=end + timedelta(days=1))
        if hist.empty or len(hist) < 2:
            return 0.0
        ret = (hist["Close"].iloc[-1] / hist["Close"].iloc[0] - 1) * 100
        return round(ret, 2)
    except Exception:
        return 0.0
