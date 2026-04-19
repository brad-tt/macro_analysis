"""
宏观指标计算与分析
"""
from dataclasses import dataclass
from typing import Optional

from .fred_client import BondYieldData, MarketSentimentData
from .yahoo_client import StockMarketData, EnergyData, ForexData, PreciousMetalsData


@dataclass
class MacroIndicators:
    """综合宏观指标"""
    # 美债
    yield_curve_slope: Optional[float] = None  # 10Y-2Y 利差
    yield_curve_status: Optional[str] = None   # 正常/平坦/倒挂
    bond_alert: Optional[str] = None           # 预警信息

    # 美股
    equity_valuation: Optional[str] = None      # 估值水平描述
    equity_alert: Optional[str] = None

    # 能源
    energy_alert: Optional[str] = None

    # 外汇
    dollar_trend: Optional[str] = None

    # 贵金属
    gold_alert: Optional[str] = None

    # 综合信号
    risk_signal: Optional[str] = None           # 风险偏好信号


class MacroIndicatorCalculator:
    """
    宏观指标计算器

    基于市场数据计算衍生指标，提供历史分位和预警信号。
    """

    # 历史分位参考值 (用于判断当前水平)
    PE_HISTORICAL_MEAN = 21.0
    PE_HISTORICAL_LOW = 15.0
    PE_HISTORICAL_HIGH = 25.0

    VIX_LOW = 15
    VIX_MEDIUM = 20
    VIX_HIGH = 30

    GOLD_HISTORICAL_RANGES = {
        "low": 1700,
        "medium": 1900,
        "high": 2100,
    }

    def __init__(self):
        pass

    def calculate(self,
                 bond: BondYieldData,
                 sentiment: MarketSentimentData,
                 stock: StockMarketData,
                 energy: EnergyData,
                 forex: ForexData,
                 metals: PreciousMetalsData) -> MacroIndicators:
        """计算综合宏观指标"""
        indicators = MacroIndicators()

        # === 美债分析 ===
        if bond.spread_10y_2y is not None:
            indicators.yield_curve_slope = bond.spread_10y_2y
            if bond.spread_10y_2y > 0.5:
                indicators.yield_curve_status = "正常（陡峭）"
            elif bond.spread_10y_2y > -0.25:
                indicators.yield_curve_status = "平坦化"
            else:
                indicators.yield_curve_status = "倒挂 ⚠️"
                indicators.bond_alert = "收益率曲线倒挂，经济衰退风险上升"

        # 美债预警
        if bond.change_10y and abs(bond.change_10y) > 10:
            indicators.bond_alert = f"10Y美债收益率单日变化 {bond.change_10y:+.0f}bp，注意风险"

        # === 美股分析 ===
        if stock.sp500_pe is not None:
            if stock.sp500_pe < self.PE_HISTORICAL_LOW:
                indicators.equity_valuation = "偏低"
            elif stock.sp500_pe > self.PE_HISTORICAL_HIGH:
                indicators.equity_valuation = "偏高 ⚠️"
            else:
                indicators.equity_valuation = "合理区间"

        if stock.sp500_change_pct and abs(stock.sp500_change_pct) > 2:
            indicators.equity_alert = f"S&P 500 单日 {'大涨' if stock.sp500_change_pct > 0 else '大跌'} {stock.sp500_change_pct:.1f}%"

        # === 市场情绪 ===
        if sentiment.vix is not None:
            if sentiment.vix < self.VIX_LOW:
                indicators.risk_signal = "极度乐观 😰"  # 低 VIX = 过度乐观
            elif sentiment.vix < self.VIX_MEDIUM:
                indicators.risk_signal = "中性"
            elif sentiment.vix < self.VIX_HIGH:
                indicators.risk_signal = "谨慎 😟"
            else:
                indicators.risk_signal = "恐慌 😱"

        # === 能源分析 ===
        if energy.wti_crude is not None:
            if energy.wti_crude < 60:
                indicators.energy_alert = "原油偏低，能源板块承压"
            elif energy.wti_crude > 90:
                indicators.energy_alert = "原油偏高，通胀压力上升 ⚠️"

        # === 外汇分析 ===
        if forex.dollar_index is not None:
            if forex.dollar_index > 104:
                indicators.dollar_trend = "强势美元"
            elif forex.dollar_index < 100:
                indicators.dollar_trend = "弱势美元"
            else:
                indicators.dollar_trend = "美元中性"

        # === 贵金属分析 ===
        if metals.gold is not None:
            if metals.gold > 2100:
                indicators.gold_alert = "黄金创新高，避险情绪浓厚"
            elif metals.gold > 1900:
                indicators.gold_alert = "黄金处于高位"
            else:
                indicators.gold_alert = "黄金相对平稳"

        return indicators

    def format_for_prompt(self,
                         bond: BondYieldData,
                         sentiment: MarketSentimentData,
                         stock: StockMarketData,
                         energy: EnergyData,
                         forex: ForexData,
                         metals: PreciousMetalsData,
                         indicators: MacroIndicators) -> str:
        """格式化数据用于 Claude 分析提示词"""
        lines = []

        lines.append("## 今日宏观数据")
        lines.append("")

        # 美债
        lines.append("### 美债收益率")
        if bond.ten_year:
            lines.append(f"- 10Y: {bond.ten_year:.2f}%")
        if bond.two_year:
            lines.append(f"- 2Y: {bond.two_year:.2f}%")
        if bond.spread_10y_2y is not None:
            lines.append(f"- 10Y-2Y利差: {bond.spread_10y_2y:.2f}% ({indicators.yield_curve_status or 'N/A'})")
        if bond.change_10y:
            lines.append(f"- 10Y单日变化: {bond.change_10y:+.0f}bp")
        lines.append("")

        # 美股
        lines.append("### 美股")
        if stock.sp500_price:
            lines.append(f"- S&P 500: {stock.sp500_price:.2f}")
        if stock.sp500_pe:
            lines.append(f"- P/E: {stock.sp500_pe:.1f} ({indicators.equity_valuation or 'N/A'})")
        if stock.sp500_change_pct is not None:
            lines.append(f"- 涨跌幅: {stock.sp500_change_pct:+.2f}%")
        lines.append("")

        # 能源
        lines.append("### 能源")
        if energy.wti_crude:
            lines.append(f"- WTI原油: ${energy.wti_crude:.2f}/桶")
        if energy.wti_change_pct is not None:
            lines.append(f"- WTI变化: {energy.wti_change_pct:+.2f}%")
        lines.append("")

        # 外汇
        lines.append("### 外汇")
        if forex.dollar_index:
            lines.append(f"- 美元指数: {forex.dollar_index:.2f} ({indicators.dollar_trend or 'N/A'})")
        lines.append("")

        # 贵金属
        lines.append("### 贵金属")
        if metals.gold:
            lines.append(f"- 黄金: ${metals.gold:.2f}/盎司")
        if metals.gold_change_pct is not None:
            lines.append(f"- 黄金变化: {metals.gold_change_pct:+.2f}%")
        if metals.gold_silver_ratio:
            lines.append(f"- 金银比: {metals.gold_silver_ratio:.2f}")
        lines.append("")

        # 市场情绪
        if sentiment.vix is not None:
            lines.append("### 市场情绪")
            lines.append(f"- VIX: {sentiment.vix:.2f} ({indicators.risk_signal or 'N/A'})")
            if sentiment.ted_spread:
                lines.append(f"- TED利差: {sentiment.ted_spread:.2f}")
            lines.append("")

        # 预警
        alerts = [a for a in [
            indicators.bond_alert,
            indicators.equity_alert,
            indicators.energy_alert,
            indicators.gold_alert,
        ] if a]

        if alerts:
            lines.append("### 预警信号")
            for alert in alerts:
                lines.append(f"- ⚠️ {alert}")
            lines.append("")

        return "\n".join(lines)
