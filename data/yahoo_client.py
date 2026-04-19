"""
Yahoo Finance 数据客户端 - 获取股票、大宗商品、外汇数据
"""
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import yfinance as yf
    YF_AVAILABLE = True
except ImportError:
    YF_AVAILABLE = False


@dataclass
class StockMarketData:
    """美股市场数据"""
    # S&P 500
    sp500_price: Optional[float] = None
    sp500_pe: Optional[float] = None
    sp500_eps: Optional[float] = None
    sp500_change_pct: Optional[float] = None

    # Nasdaq
    nasdaq_price: Optional[float] = None
    nasdaq_change_pct: Optional[float] = None

    # 市场广度指标（如果可得）
    adv_dec_ratio: Optional[float] = None


@dataclass
class EnergyData:
    """能源数据"""
    wti_crude: Optional[float] = None      # WTI 原油 (美元/桶)
    wti_change_pct: Optional[float] = None
    brent_crude: Optional[float] = None    # 布伦特原油
    brent_change_pct: Optional[float] = None

    # 大宗商品指数
    commodity_index: Optional[float] = None


@dataclass
class ForexData:
    """外汇数据"""
    dollar_index: Optional[float] = None        # DXY 美元指数
    dollar_index_change_pct: Optional[float] = None

    # 主要货币对
    eur_usd: Optional[float] = None
    usd_jpy: Optional[float] = None
    gbp_usd: Optional[float] = None


@dataclass
class PreciousMetalsData:
    """贵金属数据"""
    gold: Optional[float] = None              # 黄金 (美元/盎司)
    gold_change_pct: Optional[float] = None
    silver: Optional[float] = None            # 白银
    silver_change_pct: Optional[float] = None
    gold_silver_ratio: Optional[float] = None  # 金银比


class YahooFinanceClient:
    """
    Yahoo Finance 数据获取客户端

    Yahoo Finance 提供全球股票、期货、外汇、加密货币等金融市场数据，
    数据相对实时且免费。
    """

    # Ticker 映射
    TICKERS = {
        # 股票指数
        "^GSPC": "S&P 500",
        "^DJI": "道琼斯",
        "^IXIC": "纳斯达克",

        # 能源
        "CL=F": "WTI原油期货",
        "BZ=F": "布伦特原油期货",

        # 外汇
        "DX=F": "美元指数",

        # 贵金属
        "GC=F": "黄金期货",
        "SI=F": "白银期货",
    }

    def __init__(self):
        if not YF_AVAILABLE:
            logger.warning("yfinance not available, install with: pip install yfinance")

    def _get_ticker_data(self, ticker: str, period: str = "5d") -> Optional[dict]:
        """获取单个 ticker 数据"""
        if not YF_AVAILABLE:
            return None

        try:
            t = yf.Ticker(ticker)
            info = t.info
            hist = t.history(period=period)

            result = {
                "info": info,
                "hist": hist,
            }

            # 计算价格变化
            if len(hist) >= 2:
                result["change_pct"] = ((hist["Close"].iloc[-1] - hist["Close"].iloc[-2]) / hist["Close"].iloc[-2]) * 100

            return result
        except Exception as e:
            logger.warning(f"Failed to get {ticker}: {e}")
            return None

    def get_stock_market(self) -> StockMarketData:
        """获取美股市场数据"""
        data = StockMarketData()

        # S&P 500
        sp500 = self._get_ticker_data("^GSPC")
        if sp500 and sp500["info"]:
            data.sp500_price = sp500["info"].get("regularMarketPrice")
            data.sp500_pe = sp500["info"].get("trailingPE")
            data.sp500_eps = sp500["info"].get("trailingEps")
            data.sp500_change_pct = sp500.get("change_pct")

        # Nasdaq
        nasdaq = self._get_ticker_data("^IXIC")
        if nasdaq and nasdaq["info"]:
            data.nasdaq_price = nasdaq["info"].get("regularMarketPrice")
            data.nasdaq_change_pct = nasdaq.get("change_pct")

        return data

    def get_energy(self) -> EnergyData:
        """获取能源数据"""
        data = EnergyData()

        # WTI 原油
        wti = self._get_ticker_data("CL=F")
        if wti and wti["info"]:
            data.wti_crude = wti["info"].get("regularMarketPrice")
            data.wti_change_pct = wti.get("change_pct")

        # 布伦特原油
        brent = self._get_ticker_data("BZ=F")
        if brent and brent["info"]:
            data.brent_crude = brent["info"].get("regularMarketPrice")
            data.brent_change_pct = brent.get("change_pct")

        return data

    def get_forex(self) -> ForexData:
        """获取外汇数据"""
        data = ForexData()

        # 美元指数
        dxy = self._get_ticker_data("DX=F")
        if dxy and dxy["info"]:
            data.dollar_index = dxy["info"].get("regularMarketPrice")
            data.dollar_index_change_pct = dxy.get("change_pct")

        return data

    def get_precious_metals(self) -> PreciousMetalsData:
        """获取贵金属数据"""
        data = PreciousMetalsData()

        # 黄金
        gold = self._get_ticker_data("GC=F")
        if gold and gold["info"]:
            data.gold = gold["info"].get("regularMarketPrice")
            data.gold_change_pct = gold.get("change_pct")

        # 白银
        silver = self._get_ticker_data("SI=F")
        if silver and silver["info"]:
            data.silver = silver["info"].get("regularMarketPrice")
            data.silver_change_pct = silver.get("change_pct")

        # 计算金银比
        if data.gold and data.silver and data.silver > 0:
            data.gold_silver_ratio = data.gold / data.silver

        return data

    def get_all_data(self) -> tuple[StockMarketData, EnergyData, ForexData, PreciousMetalsData]:
        """获取所有数据"""
        return (
            self.get_stock_market(),
            self.get_energy(),
            self.get_forex(),
            self.get_precious_metals(),
        )
