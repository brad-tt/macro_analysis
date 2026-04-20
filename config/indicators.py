# v3 Indicators Manifest — OpenBB ODP 主接口
# 采集策略：P0/P1 走 OpenBB；CN 两个数据点走 akshare
# 注意：DGS10/DGS2/DGS3MO 由 _fetch_treasury_rates() 统一处理，无需 openbb_call

INDICATORS_MANIFEST = [
    # ── 美债收益率：_fetch_treasury_rates() 统一处理 ───────────────
    # openbb_call 仅供参考，实际通过 _fetch_treasury_rates() 一次性提取
    {"id": "DGS10",   "name": "10年期美债收益率",      "source": "openbb", "priority": "P0",
     "unit": "percent",  "valid_range": [0, 15],
     "openbb_call": "obb.fixedincome.government.treasury_rates()", "treasury_col": "year_10"},
    {"id": "DGS2",    "name": "2年期美债收益率",      "source": "openbb", "priority": "P0",
     "unit": "percent",  "valid_range": [0, 15],
     "openbb_call": "obb.fixedincome.government.treasury_rates()", "treasury_col": "year_2"},
    {"id": "DGS3MO",  "name": "3个月美债收益率",      "source": "openbb", "priority": "P0",
     "unit": "percent",  "valid_range": [0, 15],
     "openbb_call": "obb.fixedincome.government.treasury_rates()", "treasury_col": "month_3"},

    # ── FRED via OpenBB ───────────────────────────────────────────
    {"id": "DFII10",  "name": "10年期TIPS实际利率",  "source": "openbb", "priority": "P0",
     "unit": "percent",  "valid_range": [-5, 10],
     "openbb_call": "obb.economy.fred_series(symbol='DFII10', provider='fred')"},
    {"id": "T10YIE",  "name": "10年期盈亏平衡通胀预期","source":"openbb", "priority": "P0",
     "unit": "percent",  "valid_range": [0, 8],
     "openbb_call": "obb.economy.fred_series(symbol='T10YIE', provider='fred')"},
    {"id": "VIXCLS",  "name": "VIX恐慌指数",          "source": "openbb", "priority": "P0",
     "unit": "index",    "valid_range": [5, 100],
     "openbb_call": "obb.economy.fred_series(symbol='VIXCLS', provider='fred')"},
    # DXY: yfinance ticker DX-Y.NYB 已失效，改用 FRED DTWEXBGS
    {"id": "DXY",     "name": "美元指数（广义）",     "source": "openbb", "priority": "P0",
     "unit": "index",    "valid_range": [70, 130],
     "openbb_call": "obb.economy.fred_series(symbol='DTWEXBGS', provider='fred')"},
    {"id": "WTI",     "name": "WTI原油现货价",        "source": "openbb", "priority": "P0",
     "unit": "usd_per_barrel", "valid_range": [10, 200],
     "openbb_call": "obb.economy.fred_series(symbol='DCOILWTICO', provider='fred')"},
    # GOLD: FRED 系列失效，改用 yfinance 黄金期货 GC=F
    {"id": "GOLD",    "name": "伦敦金现货",           "source": "openbb", "priority": "P0",
     "unit": "usd_per_troy_oz", "valid_range": [500, 5000],
     "openbb_call": "obb.equity.price.historical(symbol='GC=F', provider='yfinance')"},

    # ── 通胀（FRED via OpenBB）─────────────────────────────────────
    # CPI: 用 FRED 指数值（330左右），energy.py 用 index 计算 YoY
    {"id": "CPIAUCSL","name": "CPI指数值（月度）",    "source": "openbb", "priority": "P1",
     "unit": "index",   "valid_range": [200, 400],  "frequency": "monthly",
     "openbb_call": "obb.economy.fred_series(symbol='CPIAUCSL', provider='fred')"},

    # ── 信用利差（FRED via OpenBB）───────────────────────────────
    {"id": "IG_SPREAD","name":"IG投资级信用利差",    "source": "openbb", "priority": "P1",
     "unit": "percent",  "valid_range": [0, 10],
     "openbb_call": "obb.economy.fred_series(symbol='BAMLC0A0CM', provider='fred')"},
    {"id": "HY_SPREAD","name":"HY高收益信用利差",    "source": "openbb", "priority": "P1",
     "unit": "percent",  "valid_range": [0, 30],
     "openbb_call": "obb.economy.fred_series(symbol='BAMLH0A0HYM2', provider='fred')"},

    # ── 美股 / 大宗商品（yfinance via OpenBB）───────────────────
    {"id": "SPX",     "name": "标普500指数",           "source": "openbb", "priority": "P1",
     "unit": "index",    "valid_range": [500, 10000],
     "openbb_call": "obb.equity.price.historical(symbol='^GSPC', provider='yfinance')"},
    {"id": "BRENT",   "name": "Brent原油期货",         "source": "openbb", "priority": "P1",
     "unit": "usd_per_barrel", "valid_range": [10, 200],
     "openbb_call": "obb.equity.price.historical(symbol='BZ=F', provider='yfinance')"},
    {"id": "EURUSD",  "name": "欧元兑美元",           "source": "openbb", "priority": "P1",
     "unit": "exchange_rate", "valid_range": [0.8, 1.6],
     "openbb_call": "obb.currency.price.historical(symbol='EURUSD=X', provider='yfinance')"},

    # ── 中国市场数据（akshare 专属）─────────────────────────────
    {"id": "USDCNY",  "name": "美元兑人民币",         "source": "akshare", "priority": "CN",
     "unit": "exchange_rate", "valid_range": [6.0, 8.5],
     "akshare_call": "ak.currency_boc_sina()"},
    {"id": "CN10Y",   "name": "中国10年期国债收益率", "source": "akshare", "priority": "CN",
     "unit": "percent",  "valid_range": [1.0, 6.0],
     "akshare_call": "ak.bond_zh_us_rate(start_date='20200101')", "cn10y_col": "中国国债收益率10年"},
]
