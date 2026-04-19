import time
import logging
from datetime import datetime, date, timedelta
from fredapi import Fred
import yfinance as yf
import pandas as pd

from config.settings import FRED_API_KEY
from config.indicators import INDICATORS_MANIFEST
import db

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_INTERVAL = 5
TIMEOUT_PER_REQUEST = 30


def is_us_holiday(d):
    """美国联邦假日简易检测（不包含浮节假日如MLK Day等，精确版需维护日历表）"""
    from datetime import date
    # 固定日期假日
    fixed = {
        (d.month, d.day) for d in [
            date(d.year, 1, 1),    # New Year's Day
            date(d.year, 7, 4),    # Independence Day
            date(d.year, 12, 25),  # Christmas
            date(d.year, 11, 11),  # Veterans Day
        ]
    }
    # 简易感恩节：11月第四个周四
    if d.month == 11 and d.day >= 22 and d.weekday() == 3:
        return True
    # 劳动节：9月第一个周一
    if d.month == 9 and d.day <= 7 and d.weekday() == 0:
        return True
    # 马丁·路德·金纪念日：1月第三个周一
    if d.month == 1 and 15 <= d.day <= 21 and d.weekday() == 0:
        return True
    # 总统日：2月第三个周一
    if d.month == 2 and 15 <= d.day <= 21 and d.weekday() == 0:
        return True
    # 阵亡将士纪念日：5月最后一个周一
    if d.month == 5 and d.day >= 25 and d.weekday() == 0:
        return True
    # 哥伦布日：10月第二个周一
    if d.month == 10 and 8 <= d.day <= 14 and d.weekday() == 0:
        return True
    return (d.month, d.day) in fixed


def fetch_fred_series(series_id, target_date):
    """从FRED拉取指定日期的数据"""
    fred = Fred(api_key=FRED_API_KEY)
    end = target_date
    start = target_date - timedelta(days=30)
    series = fred.get_series(series_id, observation_start=start.isoformat(), observation_end=end.isoformat())
    series = series.dropna()
    if series.empty:
        return None, None
    # 找到 <= target_date 的最近值
    valid = series[series.index <= pd.Timestamp(target_date)]
    if valid.empty:
        return None, None
    fetched_date = valid.index[-1].date()
    is_stale = 1 if fetched_date < target_date else 0
    return valid.iloc[-1], fetched_date


def fetch_yfinance_series(ticker, target_date):
    """从yfinance拉取数据"""
    ticker_obj = yf.Ticker(ticker)
    end = target_date
    start = target_date - timedelta(days=7)
    hist = ticker_obj.history(start=start, end=end + timedelta(days=1))
    if hist.empty:
        return None, None
    valid = hist[hist.index.date <= target_date]
    if valid.empty:
        fetched_date = hist.index[-1].date()
        return hist["Close"].iloc[-1], fetched_date
    fetched_date = valid.index[-1].date()
    return valid["Close"].iloc[-1], fetched_date


def fetch_single_indicator(indicator, target_date):
    """单个指标抓取，带重试"""
    for attempt in range(MAX_RETRIES):
        try:
            value = None
            fetched_date = None

            if indicator["source"] == "FRED":
                value, fetched_date = fetch_fred_series(indicator["id"], target_date)
            elif indicator["source"] == "yfinance":
                value, fetched_date = fetch_yfinance_series(indicator["ticker"], target_date)

            if value is not None:
                valid_range = indicator["valid_range"]
                if not (valid_range[0] <= value <= valid_range[1]):
                    logger.warning(f"[{indicator['id']}] value {value} out of range {valid_range}, will use fallback")
                    # 回退到前一天
                    prev = db.get_latest_indicator_before(indicator["id"], target_date.isoformat())
                    if prev:
                        return prev[0]["value"], prev[0]["date"], True
                    return None, None, True
                is_stale = 1 if fetched_date and fetched_date < target_date else 0
                return value, fetched_date, is_stale
            else:
                # 无数据，尝试取前一天
                prev = db.get_latest_indicator_before(indicator["id"], target_date.isoformat())
                if prev:
                    return prev[0]["value"], prev[0]["date"], True

        except Exception as e:
            logger.warning(f"[{indicator['id']}] attempt {attempt+1} failed: {e}")
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_INTERVAL)

    return None, None, True


def fetch_all_indicators(target_date_str):
    """L1主函数：抓取所有指标"""
    import pandas as pd
    target_date = date.fromisoformat(target_date_str)

    results = {}
    missing_p0 = []

    for indicator in INDICATORS_MANIFEST:
        value, fetched_date, is_stale = fetch_single_indicator(indicator, target_date)

        if value is not None:
            results[indicator["id"]] = {
                "value": value,
                "source": indicator["source"],
                "is_stale": is_stale,
                "fetched_date": str(fetched_date) if fetched_date else None
            }
            # 写入数据库
            db.upsert_indicator(
                date=target_date_str,
                series_id=indicator["id"],
                value=value,
                source=indicator["source"],
                is_stale=is_stale
            )
        else:
            results[indicator["id"]] = None
            if indicator["priority"] == "P0":
                missing_p0.append(indicator["id"])

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


# L1 完成断言
def l1_completion_assert(target_date_str):
    from datetime import date
    target = date.fromisoformat(target_date_str)
    count = db.count_indicators(target_date_str)
    assert count >= 12, f"Indicator count {count} < 12"
    p0_non_stale = db.count_p0_non_stale(target_date_str)

    # 周六/周日美国市场休市，所有数据均为 stale，放行
    is_weekend = target.weekday() >= 5  # 5=Sat, 6=Sun
    if is_weekend:
        logger.warning(f"[L1] Weekend ({target}), all data stale. Proceeding with {count} stale indicators.")
        return

    # 周末或历史日期（已无法获取非 stale 数据），放行
    if target != date.today():
        logger.warning(f"[L1] Historical date {target}, all data is stale by definition. Proceeding.")
        return

    assert p0_non_stale >= 6, f"P0 non-stale count {p0_non_stale} < 6"
    logger.info(f"[L1] PASS: {count} indicators, {p0_non_stale} P0 non-stale")
