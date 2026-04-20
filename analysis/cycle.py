"""L2.6 宏观周期状态机"""
import db
from datetime import date, timedelta
from analysis.utils import query_db_n_days_ago
from config.settings import FRED_API_KEY

CYCLE_RULES = [
    {
        "state": "expansion",
        "conditions": [
            ("curve_score", lambda x: x > 0),
            ("pmi", lambda pmi: pmi and pmi > 50),
            ("hy_spread_delta_20d", lambda d: d is not None and d < 0),
            ("vix", lambda v: v < 20),
        ],
        "weight": 1.0
    },
    {
        "state": "overheating",
        "conditions": [
            ("cpi", lambda c: c and c > 3.0),
            ("tips_5d_delta", lambda d: d is not None and d > 0),
            ("abs_spread_2_10", lambda s: s is not None and abs(s) < 0.5),
            ("wti", lambda w: w and w > 80),
        ],
        "weight": 1.0
    },
    {
        "state": "stagflation",
        "conditions": [
            ("stagflation_flag", lambda f: f == True),
        ],
        "weight": 1.5
    },
    {
        "state": "recession",
        "conditions": [
            ("inversion_days", lambda d: d > 60),
            ("pmi", lambda p: p and p < 48),
            ("hy_spread", lambda s: s and s > 500),
            ("vix", lambda v: v > 25),
        ],
        "weight": 1.0
    },
    {
        "state": "recovery",
        "conditions": [
            ("spread_2_10_delta_60d", lambda d: d is not None and d > 0.3),
            ("pmi_delta_20d", lambda d: d is not None and d > 2),
            ("tips_5d_delta", lambda d: d is not None and d < -0.05),
        ],
        "weight": 1.0
    },
]

def compute_cycle_state(curve_result, fed_result, energy_result, dxy_result, snapshot):
    pmi = query_latest_pmi()
    hy_spread = snapshot.get("hy_spread")
    vix = snapshot.get("vix")
    wti = snapshot.get("wti")
    cpi = snapshot.get("cpi_latest") or energy_result.get("cpi_latest")
    curve_score = curve_result["curve_score"]
    spread_2_10 = curve_result["spread_2_10"]
    tips_5d_delta = fed_result["tips_5d_delta"]
    stagflation_flag = energy_result.get("stagflation_flag", False)
    inversion_days = curve_result["inversion_days"]

    hy_spread_20d_ago = query_db_n_days_ago("HY_SPREAD", 20)  # v3: HY_SPREAD (was BAMLH0A0HYM2)
    hy_spread_delta_20d = hy_spread - hy_spread_20d_ago if (hy_spread and hy_spread_20d_ago) else None

    spread_2_10_60d_ago = query_db_n_days_ago("DGS10", 60)
    spread_2_10_2y_ago  = query_db_n_days_ago("DGS2", 60)
    spread_2_10_delta_60d = (
        (spread_2_10 - (spread_2_10_60d_ago - (query_db_n_days_ago("DGS2", 60) or spread_2_10_2y_ago or spread_2_10)))
        if spread_2_10_60d_ago else None
    )

    # PMI 20天变化：使用ISM制造业PMI (MANUM)，不再用SPX代替
    pmi_20d_ago = query_db_n_days_ago("MANUM", 20)
    pmi_delta_20d = (pmi - pmi_20d_ago) if (pmi and pmi_20d_ago) else None

    context = {
        "curve_score": curve_score,
        "pmi": pmi,
        "hy_spread_delta_20d": hy_spread_delta_20d,
        "vix": vix,
        "cpi": cpi,
        "tips_5d_delta": tips_5d_delta,
        "abs_spread_2_10": abs(spread_2_10) if spread_2_10 is not None else None,
        "wti": wti,
        "stagflation_flag": stagflation_flag,
        "inversion_days": inversion_days,
        "spread_2_10_delta_60d": spread_2_10_delta_60d,
        "pmi_delta_20d": pmi_delta_20d,
        "hy_spread": hy_spread,
    }

    scores = {}
    for rule in CYCLE_RULES:
        satisfied = 0
        for field, cond in rule["conditions"]:
            val = context.get(field)
            try:
                if cond(val):
                    satisfied += 1
            except Exception:
                pass
        total = len(rule["conditions"])
        scores[rule["state"]] = (satisfied / total) * rule["weight"] if total > 0 else 0

    if not scores:
        return "uncertain", 0

    best_state = max(scores, key=scores.get)
    best_score = scores[best_state]

    if best_score < 0.5:
        return "uncertain", int(best_score * 100)

    return best_state, int(best_score * 100)

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
