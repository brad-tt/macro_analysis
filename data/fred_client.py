"""
FRED 数据客户端 - 获取美债收益率、市场情绪指标
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from fredapi import Fred
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False


@dataclass
class BondYieldData:
    """美债收益率数据"""
    # 各期限收益率 (%)
    two_year: Optional[float] = None
    five_year: Optional[float] = None
    ten_year: Optional[float] = None
    thirty_year: Optional[float] = None

    # 利差 (%)
    spread_10y_2y: Optional[float] = None  # 10Y-2Y
    spread_10y_5y: Optional[float] = None  # 10Y-5Y
    spread_30y_5y: Optional[float] = None  # 30Y-5Y

    # 前一日变化 (bp)
    change_10y: Optional[float] = None


@dataclass
class MarketSentimentData:
    """市场情绪数据"""
    vix: Optional[float] = None
    ted_spread: Optional[float] = None


class FredClient:
    """
    FRED 数据获取客户端

    FRED (Federal Reserve Economic Data) 是圣路易斯联储提供的免费经济数据库，
    提供美债收益率、市场情绪等关键宏观指标。

    无 API Key 可访问部分数据，有 API Key 可访问更多序列并提高请求限制。
    """

    # FRED 系列 ID
    SERIES_IDS = {
        # 国债收益率
        "DGS2": "2年期国债收益率",
        "DGS5": "5年期国债收益率",
        "DGS10": "10年期国债收益率",
        "DGS30": "30年期国债收益率",
        "T10Y2Y": "10Y-2Y利差",

        # 市场情绪
        "VIXCLS": "VIX恐慌指数",
        "TEDRATE": "TED利差",
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
        self.client = Fred(api_key=api_key) if api_key and FRED_AVAILABLE else None

    def get_bond_yield(self, days: int = 1) -> BondYieldData:
        """
        获取美债收益率数据

        Args:
            days: 获取最近 N 天的数据用于计算变化

        Returns:
            BondYieldData 对象
        """
        data = BondYieldData()

        if not self.client:
            logger.warning("FRED client not initialized, skipping bond yield data")
            return data

        try:
            # 获取各期限收益率
            for series_id, name in [("DGS2", "2Y"), ("DGS5", "5Y"), ("DGS10", "10Y"), ("DGS30", "30Y")]:
                try:
                    series = self.client.get_series(series_id)
                    if series is not None and len(series) > 0:
                        setattr(data, f"{name.lower().replace('y', '_year').replace('2_', 'two_').replace('5_', 'five_').replace('10_', 'ten_').replace('30_', 'thirty_')}", series.iloc[-1])
                except Exception as e:
                    logger.warning(f"Failed to get {series_id}: {e}")

            # 获取利差
            try:
                spread = self.client.get_series("T10Y2Y")
                if spread is not None and len(spread) > 0:
                    data.spread_10y_2y = spread.iloc[-1]
            except Exception as e:
                logger.warning(f"Failed to get T10Y2Y: {e}")

            # 计算利差
            if data.ten_year and data.two_year:
                data.spread_10y_2y = data.ten_year - data.two_year
            if data.ten_year and data.five_year:
                data.spread_10y_5y = data.ten_year - data.five_year
            if data.thirty_year and data.five_year:
                data.spread_30y_5y = data.thirty_year - data.five_year

            # 计算 10Y 变化
            if len(series) >= 2:
                data.change_10y = (series.iloc[-1] - series.iloc[-2]) * 100  # 转换为 bp

        except Exception as e:
            logger.error(f"Error fetching bond yield data: {e}")

        return data

    def get_market_sentiment(self) -> MarketSentimentData:
        """获取市场情绪数据"""
        data = MarketSentimentData()

        if not self.client:
            logger.warning("FRED client not initialized, skipping sentiment data")
            return data

        try:
            # VIX
            try:
                vix = self.client.get_series("VIXCLS")
                if vix is not None and len(vix) > 0:
                    data.vix = vix.iloc[-1]
            except Exception as e:
                logger.warning(f"Failed to get VIX: {e}")

            # TED 利差
            try:
                ted = self.client.get_series("TEDRATE")
                if ted is not None and len(ted) > 0:
                    data.ted_spread = ted.iloc[-1]
            except Exception as e:
                logger.warning(f"Failed to get TEDRATE: {e}")

        except Exception as e:
            logger.error(f"Error fetching sentiment data: {e}")

        return data

    def get_all_data(self) -> tuple[BondYieldData, MarketSentimentData]:
        """获取所有数据"""
        return self.get_bond_yield(), self.get_market_sentiment()
