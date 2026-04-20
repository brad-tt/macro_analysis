# Macro Analysis Pipeline v3

全球宏观经济分析与美股资产配置自动化系统。

每日静默抓取数据，每周推送 PDF 深度报告，事件触发实时预警。

## 功能架构

```
每日 05:30 (工作日)  ← 静默运行
  └── L1: fetch (OpenBB + akshare)
        └── L2: analysis → 数据入库，不推送

每周一 06:00         ← 深度推送
  └── L3_DEEP: 深度报告（PDF格式）
        └── Playwright Chromium 渲染，页码支持

事件触发              ← 条件满足时随时
  └── L3_ALERT: 组装触发条件和 delta
        └── 推送简短预警
```

## 五维信号体系

| 传导链 | 核心指标 | 信号逻辑 |
|---|---|---|
| 联储政策 | DGS2, DFII10, DXY | TIPS 5日变化 + DXY-实际利率相关性 |
| 收益率曲线 | DGS2, DGS10, DGS3MO | 2-10利差倒挂天数 + 12m衰退概率 |
| 美元 | DXY, USDCNY, CN10Y | EM压力 + 中美利差 + 人民币压力标志 |
| 能源 | WTI, CPIAUCSL | 油价-CPI滞后相关性 + 滞胀标志 |
| 黄金 | GOLD, DFII10 | 实际利率相关性 + 驱动分类 |

## 数据源（v3）

- **OpenBB ODP** — 美债收益率、DXY、WTI、VIX、信用利差、黄金、SPX、Brent、EURUSD、CPI 等
- **akshare** — USDCNY、CN10Y（中国10年国债收益率）
- **tradingeconomics.com** — ISM Manufacturing PMI（2020年后FRED停止更新，改用此源）
- **定性数据** — Fed官员讲话、FOMC声明、经济日历、宏观新闻（RSS）、COT持仓

## 项目结构

```
macro_analysis/
├── config/
│   ├── indicators.py    # 指标清单（17个指标，OpenBB映射）
│   ├── thresholds.py     # 魔法数字集中管理（v3.1新增）
│   └── settings.py      # 环境变量
├── analysis/
│   ├── __init__.py       # L2主函数 + NARRATIVE_CONTEXT_BUILDER
│   ├── yield_curve.py    # 收益率曲线分析
│   ├── fed_policy.py     # 联储政策分析
│   ├── dxy.py           # 美元分析（含CN利差节点）
│   ├── energy.py        # 能源分析
│   ├── gold.py          # 黄金分析
│   ├── cycle.py         # 宏观周期状态机
│   └── utils.py         # pivot cache + rolling_correlation（v3.1优化）
├── fetch.py              # L1 定量数据抓取（并发优化）
├── fetch_qualitative.py  # L1.2 定性数据采集（新闻日期过滤）
├── pipeline.py           # 三模式入口（daily/weekly/alert）
├── scheduler.py          # 定时调度器 + MCP Server管理
├── push_deep.py         # L3_DEEP 深度报告（PDF格式）
├── push_alert.py         # L3_ALERT 事件预警
├── db.py                 # 数据库操作（含pivot cache支持）
├── macro_data.db         # SQLite 数据库
├── requirements.txt
└── .env.example
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 填入以下值：
# FRED_API_KEY       → https://fred.stlouisfed.org/docs/api/api_key.html
# ANTHROPIC_API_KEY  → MiniMax API Key（支持 Anthropic 兼容端点）
# TELEGRAM_BOT_TOKEN → Telegram Bot Token（@BotFather 获取）
# TELEGRAM_CHAT_ID   → 你的 Telegram Chat ID
```

### 3. 初始化数据库

```bash
python3 -c "import db; db.init_db()"
```

### 4. 运行

```bash
# 每日静默（不推送）
python3 pipeline.py daily

# 每周深度报告（PDF推送）
python3 pipeline.py weekly

# 事件预警检查
python3 pipeline.py alert

# 启动调度器（三任务自动运行）
python3 scheduler.py
```

## 数据库表结构

| 表名 | 说明 |
|---|---|
| `daily_indicators` | 每日指标数值 |
| `daily_signals` | L2 分析结果（JSON） |
| `daily_reports` | 已发送报告历史 |
| `qualitative_context` | 定性数据（Fed讲话、新闻、ISM PMI等） |

## 调度任务

| 任务 | 时间 | 说明 |
|---|---|---|
| `daily_silent` | 每周一~五 05:30 | L1 + L2，不推送 |
| `weekly_deep` | 每周一 06:00 | L1 + L2 + L3_DEEP（PDF） |
| `event_alert` | 每周一~五 06:05 | 条件触发则发 L3_ALERT |

## 预警触发条件

满足任意一条即触发 L3_ALERT：

- 新增异常信号
- 任一信号评分单日变化 ≥ 2
- 综合评分穿越阈值（-3 或 +5）
- 10Y美债单日变化 > 15bp
- WTI 油价单日涨跌幅 > 4%
- DXY 单日变化 > 1.5
- 黄金单日涨跌幅 > 2.5%
- VIX > 30

## 免责声明

本系统仅供个人宏观研究参考，不构成投资建议。