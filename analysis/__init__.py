"""L2 分析主模块"""
from datetime import date, timedelta
import json

from config.indicators import INDICATORS_MANIFEST
from analysis.yield_curve import compute_yield_curve
from analysis.fed_policy import compute_fed_policy
from analysis.dxy import compute_dxy
from analysis.energy import compute_energy
from analysis.gold import compute_gold
from analysis.cycle import compute_cycle_state
from analysis.utils import init_pivot_cache, rolling_correlation
import db


def _v(d, key):
    """安全获取指标值"""
    item = d.get(key) if isinstance(d, dict) else None
    if item is None:
        return None
    return item.get("value") if isinstance(item, dict) else None


# ─────────────────────────────────────────────
# L2.9 NARRATIVE_CONTEXT_BUILDER
# ─────────────────────────────────────────────
def build_narrative_context(date_str):
    """
    L2.9 — 构建定性叙事上下文，供 L3 Deep Report 使用
    从 qualitative_context 表读取数据并结构化
    """
    speeches = db.get_latest_qualitative("fed_speech_tracker", last_n_days=7) or []
    fed_tone = {
        "dominant_tone": _majority([s.get("hawkish_dovish_label") for s in speeches if s.get("hawkish_dovish_label")]),
        "recent_speakers": [s.get("speaker_name", "") for s in speeches[:3]],
        "key_phrases": [p for s in speeches[:3] for p in (s.get("key_phrases") or [])],
    }

    fomc_delta = db.get_qualitative(date_str, "fomc_statement_delta")

    calendar = db.get_qualitative(date_str, "economic_calendar_7d") or []
    upcoming_high = [e for e in calendar if e.get("importance_level") == "high"]

    headlines_data = (db.get_latest_qualitative("news_macro_headlines", last_n_days=1) or [[]])[0] if db.get_latest_qualitative("news_macro_headlines", last_n_days=1) else []
    news_context = [h.get("headline", "") for h in headlines_data]

    cot_data = db.get_latest_qualitative("market_positioning", last_n_days=7) or []
    positioning_context = _build_positioning_context(cot_data)

    return {
        "fed_tone": fed_tone,
        "fomc_delta": fomc_delta,
        "upcoming_events": upcoming_high,
        "news_context": news_context,
        "positioning_context": positioning_context,
    }


def _majority(items):
    from collections import Counter
    items = [i for i in items if i]
    if not items:
        return "neutral"
    counts = Counter(items)
    return counts.most_common(1)[0][0]


def _build_positioning_context(cot_data):
    ctx = []
    for item in cot_data:
        net_pos = item.get("net_speculative_position", 0)
        change = item.get("change_from_prior_week", 0)
        if net_pos and abs(change) > abs(net_pos * 0.1):
            direction = "增多" if change > 0 else "减仓"
            ctx.append(f"{item.get('instrument', 'Unknown')} 净投机持仓{direction}，当前净多{int(net_pos)}")
    return ctx


# ─────────────────────────────────────────────
# 主分析函数
# ─────────────────────────────────────────────
def run_analysis(target_date_str):
    """L2 主函数"""
    init_pivot_cache(target_date_str, window=45)

    data = {}
    for ind in INDICATORS_MANIFEST:
        row = db.get_indicator(target_date_str, ind["id"])
        if row:
            data[ind["id"]] = {
                "value": row["value"],
                "source": row["source"],
                "is_stale": row["is_stale"]
            }
        else:
            data[ind["id"]] = None

    curve_result  = compute_yield_curve(data)
    fed_result    = compute_fed_policy(data, base_date=target_date_str)
    dxy_result    = compute_dxy(data, base_date=target_date_str)
    energy_result = compute_energy(data, base_date=target_date_str)
    gold_result   = compute_gold(data, base_date=target_date_str)

    anomaly_flags = aggregate_anomaly_flags(fed_result, gold_result, dxy_result, data, target_date_str)

    snapshot_for_cycle = {
        "vix": _v(data, "VIXCLS"),
        "wti": _v(data, "WTI"),  # v3: WTI (was DCOILWTICO)
        "hy_spread": _v(data, "HY_SPREAD"),  # v3: HY_SPREAD
        "cpi_latest": energy_result.get("cpi_latest"),
    }
    cycle_state, cycle_confidence = compute_cycle_state(
        curve_result, fed_result, energy_result, dxy_result, snapshot_for_cycle
    )

    total_score = (
        fed_result["fed_score"] +
        curve_result["curve_score"] +
        dxy_result["dxy_score"] +
        energy_result["energy_score"] +
        gold_result["gold_score"]
    )

    daily_change = compute_daily_change(target_date_str, data)
    weekly_change = db.get_weekly_change(target_date_str)
    qualitative_context = build_narrative_context(target_date_str)

    s = {
        "yield_10y":     _v(data, "DGS10"),
        "yield_2y":      _v(data, "DGS2"),
        "yield_3mo":     _v(data, "DGS3MO"),
        "tips_10y":      _v(data, "DFII10"),
        "breakeven_10y": _v(data, "T10YIE"),
        # v3 命名：DXY（原 DTWEXBGS），WTI（原 DCOILWTICO）
        "dxy":           _v(data, "DXY"),
        "wti":           _v(data, "WTI"),
        "gold":          _v(data, "GOLD"),
        "vix":           _v(data, "VIXCLS"),
        "ig_spread":     _v(data, "IG_SPREAD"),
        "hy_spread":     _v(data, "HY_SPREAD"),
    }

    payload = {
        "date": target_date_str,
        "snapshot": s,
        "daily_change": daily_change,
        "weekly_change": weekly_change,
        "signals": {
            "fed_score":    fed_result["fed_score"],
            "curve_score":  curve_result["curve_score"],
            "dxy_score":    dxy_result["dxy_score"],
            "energy_score": energy_result["energy_score"],
            "gold_score":   gold_result["gold_score"],
            "total_score":  total_score,
        },
        "curve": {
            "spread_2_10":        curve_result["spread_2_10"],
            "spread_10_3m":       curve_result["spread_10_3m"],
            "inversion_days":     curve_result["inversion_days"],
            "recession_prob_12m": curve_result["recession_prob_12m"],
            "term_premium":       curve_result.get("term_premium"),
        },
        "fed": {
            "tips_5d_delta":         fed_result["tips_5d_delta"],
            "dxy_realrate_corr_30d": fed_result["dxy_realrate_corr_30d"],
        },
        "gold": {
            "driver":            gold_result["gold_driver"],
            "realrate_corr_30d": gold_result["gold_realrate_corr_30d"],
        },
        "energy": {
            "oil_cpi_lag_score":    energy_result.get("oil_cpi_lag_score", 0),
            "stagflation_flag":       energy_result["stagflation_flag"],
            "energy_divergence_flag": energy_result["energy_divergence_flag"],
        },
        "dxy": {
            "em_pressure_flag":   dxy_result["em_pressure_flag"],
            "20d_change_pct":     dxy_result["dxy_20d_change_pct"],
            # v3 新增：CN 利差字段
            "cn_us_10y_spread":   dxy_result.get("cn_us_10y_spread"),
            "usdcny":             dxy_result.get("usdcny"),
            "cny_pressure_flag":  dxy_result.get("cny_pressure_flag"),
            "cn_data_available":  dxy_result.get("cn_data_available"),
        },
        "cycle": {
            "state":      cycle_state,
            "confidence": cycle_confidence,
        },
        "anomaly_flags": anomaly_flags,
        "qualitative_context": qualitative_context,
    }

    db.upsert_signal(target_date_str, payload)
    l2_completion_assert(payload)
    return payload


def compute_daily_change(target_date_str, data):
    """用 get_latest_indicator_before 自动回溯到最近交易日"""
    snapshot_keys = ["yield_10y","yield_2y","yield_3mo","tips_10y","breakeven_10y",
                     "dxy","wti","gold","vix","ig_spread","hy_spread"]
    id_map = {
        # v3 命名：DXY, WTI；IG_SPREAD, HY_SPREAD
        "yield_10y":"DGS10","yield_2y":"DGS2","yield_3mo":"DGS3MO",
        "tips_10y":"DFII10","breakeven_10y":"T10YIE","dxy":"DXY",
        "wti":"WTI","gold":"GOLD","vix":"VIXCLS",
        "ig_spread":"IG_SPREAD","hy_spread":"HY_SPREAD"
    }
    dc = {}
    for sk in snapshot_keys:
        today_val = _v(data, id_map.get(sk, ""))
        if today_val is None:
            continue
        prev_rows = db.get_latest_indicator_before(id_map.get(sk, ""), target_date_str, limit=1)
        if prev_rows:
            prev_val = prev_rows[0]["value"]
            if prev_val is not None and prev_val != 0:
                dc[f"{sk}_1d_delta"] = round(today_val - prev_val, 4)
    return dc


def aggregate_anomaly_flags(fed_result, gold_result, dxy_result, data, target_date_str):
    flags = []
    if fed_result.get("anomaly_yield_policy_inversion"):
        flags.append("yield_policy_inversion")
    if gold_result.get("anomaly_gold_realrate_decorrelation"):
        flags.append("gold_realrate_decorrelation")
    if dxy_result.get("em_pressure_flag"):
        flags.append("em_pressure")

    gold_5d_ago = db.get_latest_indicator_before("GOLD", target_date_str, limit=1)
    dxy_5d_ago  = db.get_latest_indicator_before("DXY", target_date_str, limit=1)  # v3: DXY (was DTWEXBGS)
    gold_today  = _v(data, "GOLD")
    dxy_today   = _v(data, "DXY")  # v3: DXY (was DTWEXBGS)

    if gold_5d_ago and dxy_5d_ago and gold_today and dxy_today:
        gold_5d_ret = (gold_today - gold_5d_ago[0]["value"]) / gold_5d_ago[0]["value"]
        dxy_5d_ret  = (dxy_today  - dxy_5d_ago[0]["value"])  / dxy_5d_ago[0]["value"]
        if gold_5d_ret > 0.02 and dxy_5d_ret > 0.01:
            flags.append("gold_dxy_simultaneous_rise")

    hy_vix_corr = rolling_correlation("HY_SPREAD", "VIXCLS", window=30)  # v3: HY_SPREAD (was BAMLH0A0HYM2)
    if hy_vix_corr < 0.3:
        flags.append("credit_vix_divergence")
    return flags


def l2_completion_assert(payload):
    required_keys = {
        "date","snapshot","daily_change","weekly_change","signals",
        "curve","fed","gold","energy","dxy","cycle","anomaly_flags","qualitative_context"
    }
    assert set(payload.keys()) == required_keys, f"Payload keys mismatch: {set(payload.keys()) ^ required_keys}"
    sig = payload["signals"]
    assert sig["total_score"] == sum([
        sig["fed_score"], sig["curve_score"], sig["dxy_score"],
        sig["energy_score"], sig["gold_score"]
    ])
    assert payload["cycle"]["state"] in [
        "expansion","overheating","stagflation","recession","recovery","uncertain"
    ]
    assert isinstance(payload["anomaly_flags"], list)
    print("[L2] PASS: payload validated")
