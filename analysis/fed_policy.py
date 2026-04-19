"""L2.2 联储政策模块"""
import db
from analysis.utils import _v, query_db_n_days_ago, rolling_correlation

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

def query_recent_fomc_stance():
    """
    从 qualitative_context 读取近7日 Fed 讲话的鹰/鸽立场。
    返回 'dovish' | 'hawkish' | 'neutral'
    """
    speeches = db.get_latest_qualitative("fed_speech_tracker", last_n_days=7)
    if not speeches:
        return "neutral"
    # speeches 是 list of list，每个元素是 dict 或 None
    all_items = speeches[0] if isinstance(speeches[0], list) else speeches
    labels = [s.get("hawkish_dovish_label") for s in all_items if s and s.get("hawkish_dovish_label")]
    if not labels:
        return "neutral"
    from collections import Counter
    majority = Counter(labels).most_common(1)[0][0]
    return majority
