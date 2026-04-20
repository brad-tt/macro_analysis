"""
L1 数据采集 — v3 版本
数据来源策略：
  P0/P1 指标：OpenBB ODP 主接口
  CN 指标：akshare（仅 USDCNY 和 CN10Y 两个数据点）
"""
import time
import logging
from datetime import date, timedelta

from config.settings import FRED_API_KEY
from config.indicators import INDICATORS_MANIFEST
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_INTERVAL = 5


def _init_openbb():
    """初始化 OpenBB 并注入 FRED API Key"""
    try:
        from openbb import obb
        if FRED_API_KEY:
            obb.user.credentials.fred_api_key = FRED_API_KEY
        return obb
    except ImportError:
        logger.error("[L1] OpenBB not installed: pip install openbb openbb-fred openbb-yfinance")
        raise


def _is_stale_computed(fetched_date, target_date):
    """
    计算数据是否为 stale。
    规则：
    - fetched_date >= target_date → 非 stale
    - 周一早间运行（target_date==today==Monday）：最近4个日历天内的数据 → 非 stale
      （期间周末+Good Friday假日休市，最近有效交易日是上周三4/15）
    - 其他情况：fetched_date < target_date → stale
    """
    if fetched_date is None:
        return 1
    if fetched_date >= target_date:
        return 0
    # fetched_date < target_date
    today = date.today()
    if target_date == today and today.weekday() == 0:
        # 周一：允许最近4个日历天内的数据（周一至周四，周四可能因假日休市）
        # 实际场景：4/17周四(Good Friday)休市，数据最近到4/16周三
        for days_back in [1, 2, 3, 4]:
            last_trading = today - timedelta(days=days_back)
            if fetched_date >= last_trading:
                return 0
    return 1


def _fetch_treasury_rates(target_date):
    """
    一次性调用 treasury_rates()，返回 {series_id: value} 字典。
    将 DGS10/DGS2/DGS3MO 三个指标从同一次 API 调用中提取。
    """
    from openbb import obb
    import pandas as pd

    column_map = {
        "DGS10":  "year_10",
        "DGS2":   "year_2",
        "DGS3MO": "month_3",
    }

    try:
        result = obb.fixedincome.government.treasury_rates()
        df = result.to_df()

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        df = df.sort_index()
        valid = df[df.index <= pd.Timestamp(target_date)]
        if valid.empty:
            valid = df.tail(5)

        latest_row = valid.iloc[-1]
        fetched_date = valid.index[-1].date()

        results = {}
        for series_id, col_name in column_map.items():
            if col_name not in latest_row:
                logger.warning(f"[L1] treasury_rates: column '{col_name}' not found")
                continue
            val = float(latest_row[col_name])
            lo, hi = next(i["valid_range"] for i in INDICATORS_MANIFEST if i["id"] == series_id)
            if not (lo <= val <= hi):
                logger.warning(f"[L1] {series_id}={val} out of range [{lo},{hi}]")
                prev = db.get_latest_indicator_before(series_id, target_date.isoformat())
                if prev:
                    results[series_id] = {"value": prev[0]["value"], "fetched_date": prev[0]["date"], "is_stale": 1}
                else:
                    results[series_id] = {"value": None, "fetched_date": None, "is_stale": 1}
            else:
                results[series_id] = {
                    "value": val,
                    "fetched_date": fetched_date,
                    "is_stale": _is_stale_computed(fetched_date, target_date)
                }
        return results

    except Exception as e:
        logger.warning(f"[L1] treasury_rates fetch failed: {e}")
        results = {}
        for series_id in column_map:
            prev = db.get_latest_indicator_before(series_id, target_date.isoformat())
            if prev:
                results[series_id] = {"value": prev[0]["value"], "fetched_date": prev[0]["date"], "is_stale": 1}
            else:
                results[series_id] = {"value": None, "fetched_date": None, "is_stale": 1}
        return results


def fetch_openbb_indicator(indicator, target_date):
    """
    通过 OpenBB 采集单个指标的最新值。
    支持 fred_series 和 yfinance historical 两种调用模式。
    """
    from openbb import obb
    import pandas as pd

    openbb_call = indicator.get("openbb_call", "")
    if not openbb_call:
        return None, None, 1

    try:
        # 执行 openbb_call 字符串
        result = eval(openbb_call)

        # 转换为 DataFrame
        if hasattr(result, "to_df"):
            df = result.to_df()
        elif isinstance(result, pd.DataFrame):
            df = result
        else:
            df = pd.DataFrame(result)

        # 标准化日期索引
        if "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"])
            df = df.set_index("date")
        elif not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)

        df = df.sort_index()

        # 找到 <= target_date 的最近值
        valid = df[df.index <= pd.Timestamp(target_date)]
        if valid.empty:
            valid = df.tail(5)

        # 提取 value 列
        value_col = None
        for col in ["value", "close", "rate", "index"]:
            if col in valid.columns:
                value_col = col
                break
        if value_col is None:
            value_col = valid.columns[-1]

        latest_val = valid[value_col].dropna().iloc[-1] if not valid[value_col].dropna().empty else None
        fetched_date = valid.index[-1].date() if not valid.empty else None

        if latest_val is None:
            return None, None, 1

        # 合理性校验
        lo, hi = indicator["valid_range"]
        if not (lo <= latest_val <= hi):
            logger.warning(f"[{indicator['id']}] value {latest_val} out of range [{lo}, {hi}]")
            prev = db.get_latest_indicator_before(indicator["id"], target_date.isoformat())
            if prev:
                return prev[0]["value"], prev[0]["date"], 1
            return None, None, 1

        is_stale = _is_stale_computed(fetched_date, target_date)
        return float(latest_val), fetched_date, is_stale

    except Exception as e:
        logger.warning(f"[{indicator['id']}] OpenBB fetch failed: {e}")
        prev = db.get_latest_indicator_before(indicator["id"], target_date.isoformat())
        if prev:
            logger.info(f"[{indicator['id']}] Falling back to DB value: {prev[0]['value']}")
            return prev[0]["value"], prev[0]["date"], 1
        return None, None, 1


def fetch_single_indicator(indicator, target_date):
    """单个指标抓取，带重试"""
    for attempt in range(MAX_RETRIES):
        try:
            value, fetched_date, is_stale = fetch_openbb_indicator(indicator, target_date)
            if value is not None:
                return value, fetched_date, is_stale
        except Exception as e:
            logger.warning(f"[{indicator['id']}] attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_INTERVAL)
    return None, None, 1


def fetch_akshare_cn_indicators():
    """
    akshare 专属：仅采集 USDCNY 和 CN10Y 两个数据点。
    失败时记录警告，不触发 FATAL。
    """
    import akshare as ak

    results = {}

    # USD/CNY — 使用 fx_spot_quote（currency_boc_sina 已改版，无货币名字段）
    try:
        df = ak.fx_spot_quote()
        usd_row = df[df["货币对"].str.contains("USD/CNY", na=False)]
        if not usd_row.empty:
            # 买报价和卖报价的中价
            buy = float(usd_row.iloc[-1]["买报价"])
            sell = float(usd_row.iloc[-1]["卖报价"])
            usdcny = (buy + sell) / 2
        else:
            logger.warning(f"[L1] USDCNY: USD/CNY row not found in fx_spot_quote")
            usdcny = None

        if usdcny and 6.0 <= usdcny <= 8.5:
            results["USDCNY"] = {"value": usdcny, "source": "akshare", "is_stale": 0, "fetched_date": date.today().isoformat()}
            logger.info(f"[L1] USDCNY={usdcny}")
        else:
            logger.warning(f"[L1] USDCNY={usdcny} out of range or None")
    except Exception as e:
        logger.warning(f"[L1] USDCNY fetch failed: {e}")

    # 中国10年国债收益率
    try:
        df = ak.bond_zh_us_rate(start_date="20200101")
        cols = df.columns.tolist()
        cn10y_col = next((c for c in cols if "中国国债收益率10年" in c or "中国国债10年" in c), None)
        if cn10y_col:
            cn10y = float(df[cn10y_col].dropna().iloc[-1])
        else:
            logger.warning(f"[L1] CN10Y: '中国国债10年' column not found. Columns: {cols}")
            cn10y = None

        if cn10y and 1.0 <= cn10y <= 6.0:
            results["CN10Y"] = {"value": cn10y, "source": "akshare", "is_stale": 0, "fetched_date": date.today().isoformat()}
            logger.info(f"[L1] CN10Y={cn10y}")
        else:
            logger.warning(f"[L1] CN10Y={cn10y} out of range or None")
    except Exception as e:
        logger.warning(f"[L1] CN10Y fetch failed: {e}")

    return results


def fetch_all_indicators(target_date_str):
    """L1主函数：抓取所有指标"""
    target_date = date.fromisoformat(target_date_str)
    results = {}
    missing_p0 = []

    # 初始化 OpenBB（注入 FRED API Key）
    try:
        _init_openbb()
    except ImportError:
        raise FatalError("OpenBB not installed. Run: pip install openbb openbb-fred openbb-yfinance")

    # ── 第一批：美债收益率（一次性调用 treasury_rates）────────────
    treasury_results = _fetch_treasury_rates(target_date)
    treasury_ids = ["DGS10", "DGS2", "DGS3MO"]
    for series_id in treasury_ids:
        data = treasury_results.get(series_id, {})
        value = data.get("value")
        if value is not None:
            results[series_id] = {
                "value": value,
                "source": "openbb",
                "is_stale": data.get("is_stale", 0),
                "fetched_date": str(data.get("fetched_date")) if data.get("fetched_date") else None
            }
            db.upsert_indicator(
                date=target_date_str, series_id=series_id,
                value=value, source="openbb", is_stale=data.get("is_stale", 0)
            )
        else:
            results[series_id] = None
            if series_id in [i["id"] for i in INDICATORS_MANIFEST if i["priority"] == "P0"]:
                missing_p0.append(series_id)

    # ── 第二批：FRED/yfinance 指标（逐个抓取）────────────────
    openbb_indicators = [i for i in INDICATORS_MANIFEST
                         if i["source"] == "openbb" and i["id"] not in treasury_ids]
    for indicator in openbb_indicators:
        value, fetched_date, is_stale = fetch_single_indicator(indicator, target_date)
        if value is not None:
            results[indicator["id"]] = {
                "value": value,
                "source": "openbb",
                "is_stale": is_stale,
                "fetched_date": str(fetched_date) if fetched_date else None
            }
            db.upsert_indicator(
                date=target_date_str, series_id=indicator["id"],
                value=value, source="openbb", is_stale=is_stale
            )
        else:
            results[indicator["id"]] = None
            if indicator["priority"] == "P0":
                missing_p0.append(indicator["id"])

    # ── 第三批：akshare CN 指标（独立失败不影响主流程）─────────
    cn_results = fetch_akshare_cn_indicators()
    for cid, data in cn_results.items():
        results[cid] = data
        db.upsert_indicator(
            date=target_date_str, series_id=cid,
            value=data["value"], source="akshare", is_stale=0
        )
    for cid in ["USDCNY", "CN10Y"]:
        if cid not in results or results[cid] is None:
            logger.warning(f"[L1] {cid} unavailable")

    # P0 中止条件
    if len(missing_p0) >= 4:
        raise FatalError(f"P0 indicators missing >= 4: {missing_p0}")

    # L1.2 定性数据采集
    try:
        import fetch_qualitative
        fetch_qualitative.fetch_all_qualitative(target_date_str)
    except Exception as e:
        logger.warning(f"[L1.2] Qualitative fetch failed: {e}")

    return results


class FatalError(Exception):
    pass


def l1_completion_assert(target_date_str):
    target = date.fromisoformat(target_date_str)
    today = date.today()
    count = db.count_indicators(target_date_str)
    assert count >= 12, f"Indicator count {count} < 12"
    p0_non_stale = db.count_p0_non_stale(target_date_str)

    is_weekend = target.weekday() >= 5
    if is_weekend:
        logger.warning(f"[L1] Weekend ({target}), all data stale. Proceeding.")
        return

    if target != today:
        logger.warning(f"[L1] Historical date {target}, all data is stale by definition. Proceeding.")
        return

    # 周一早间 bypass：P0 数据已写入（因 Good Friday 假期导致数据只到周四，is_stale=1）
    # 只要有至少 6 个 P0 指标数据存在，无论 is_stale 标记，均放行
    if today.weekday() == 0 and p0_non_stale < 6:
        conn = db.get_conn()
        c = conn.cursor()
        c.execute("""
            SELECT COUNT(DISTINCT series_id) FROM daily_indicators
            WHERE date=? AND series_id IN (
                SELECT series_id FROM daily_indicators WHERE date=? AND series_id NOT LIKE '%SPREAD'
            )
        """, (target_date_str, target_date_str))
        total_p0 = c.fetchone()[0]
        conn.close()
        if total_p0 >= 6:
            logger.info(f"[L1] Monday bypass: {total_p0} P0 indicators written (stale={p0_non_stale}). Proceeding.")
            return
        elif p0_non_stale > 0:
            logger.warning(f"[L1] Monday: {p0_non_stale} P0 non-stale available. Proceeding.")
            return

    assert p0_non_stale >= 6, f"P0 non-stale count {p0_non_stale} < 6"
    logger.info(f"[L1] PASS: {count} indicators, {p0_non_stale} P0 non-stale")
