"""
L1.2 定性数据采集
采集 FOMC讲话、经济日历、宏观新闻、COT持仓等定性数据
"""
import logging
import re
import json
from datetime import date, timedelta
from bs4 import BeautifulSoup
import requests

import db

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
}

# ─────────────────────────────────────────────
# 1. Fed Speech Tracker
# ─────────────────────────────────────────────
def fetch_fed_speeches(target_date_str):
    """
    爬取近7日美联储官员公开讲话，提取关键词并判断鹰/鸽立场
    source: https://www.federalreserve.gov/newsevents/speeches.htm
    """
    hawkish_keywords = [
        "further tightening", "restrictive", "higher for longer",
        "inflation concern", "vigilant", "remain restrictive",
        "need to see more progress on inflation"
    ]
    dovish_keywords = [
        "patient", "monitoring", "labor market cooling", "disinflation",
        "supportive", "accommodative", "remain patient",
        "not yet confident", "easing", "cut rates"
    ]

    speeches = []
    try:
        resp = requests.get(
            "https://www.federalreserve.gov/newsevents/speeches.htm",
            headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 找speech列表项
        items = soup.select(".row .speech") or soup.select("article.speech")
        if not items:
            items = soup.select("div.event-list div")

        target = date.fromisoformat(target_date_str)
        cutoff = (target - timedelta(days=7)).isoformat()

        for item in items[:20]:
            try:
                # 日期
                date_el = item.select_one(".time") or item.select_one("time") or item.select_one("span.date")
                if not date_el:
                    continue
                date_str = date_el.get_text(strip=True)
                # 解析日期（格式如 "Apr. 14, 2026" 或 "04/14/2026"）
                try:
                    from datetime import datetime
                    d = datetime.strptime(date_str.replace(".", ""), "%b %d, %Y").date()
                    d_str = d.isoformat()
                except:
                    try:
                        d = datetime.strptime(date_str, "%m/%d/%Y").date()
                        d_str = d.isoformat()
                    except:
                        continue

                if d_str < cutoff:
                    continue

                # 标题
                title_el = item.select_one("h4") or item.select_one("h3") or item.select_one("a")
                title = title_el.get_text(strip=True) if title_el else ""

                # 链接
                link_el = item.select_one("a")
                link = "https://www.federalreserve.gov" + link_el["href"] if link_el and link_el.get("href") else ""

                # 抓全文/摘要（只抓第一页，节省时间）
                key_phrases = []
                if link:
                    try:
                        detail = requests.get(link, headers=HEADERS, timeout=10)
                        soup2 = BeautifulSoup(detail.text, "html.parser")
                        text = soup2.get_text(separator=" ")
                        text_lower = text.lower()
                        for kw in hawkish_keywords:
                            if kw.lower() in text_lower:
                                key_phrases.append(kw)
                        for kw in dovish_keywords:
                            if kw.lower() in text_lower:
                                key_phrases.append(kw)
                    except:
                        pass

                # 判断鹰/鸽
                hawkish_count = sum(1 for p in key_phrases if p in hawkish_keywords)
                dovish_count = sum(1 for p in key_phrases if p in dovish_keywords)
                if hawkish_count > dovish_count:
                    label = "hawkish"
                elif dovish_count > hawkish_count:
                    label = "dovish"
                else:
                    label = "neutral"

                speeches.append({
                    "speaker_name": title.split(" on ")[0].split(" – ")[0].strip() if " on " in title or " – " in title else title,
                    "speech_date": d_str,
                    "title": title,
                    "key_phrases": key_phrases[:5],
                    "hawkish_dovish_label": label
                })
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"[L1-Qual] fed_speech_tracker failed: {e}")

    return speeches[:5]


# ─────────────────────────────────────────────
# 2. FOMC Statement Delta
# ─────────────────────────────────────────────
def fetch_fomc_statement_delta(target_date_str):
    """
    爬取最新两条 FOMC 声明，对比用词变化
    source: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
    """
    try:
        resp = requests.get(
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
            headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # 找最近两次 FOMC 声明
        links = []
        for a in soup.select("a[href*='fomcminutes']")[:4]:
            href = a.get("href", "")
            text = a.get_text(strip=True)
            if "statement" in href.lower() or "policy" in href.lower():
                links.append(("https://www.federalreserve.gov" + href, text))
        links = links[:2]

        statements = []
        for url, label in links:
            try:
                r = requests.get(url, headers=HEADERS, timeout=10)
                soup2 = BeautifulSoup(r.text, "html.parser")
                # 提取段落文本
                paragraphs = soup2.select("p") or soup2.select("div.section")
                content = " ".join(p.get_text(strip=True) for p in paragraphs[:10])
                date_match = re.search(r"\w+ \d{1,2},? \d{4}", label)
                stmt_date = date_match.group(0) if date_match else label
                statements.append({"date_label": stmt_date, "url": url, "content": content[:500]})
            except:
                continue

        if len(statements) >= 2:
            # 简化版：对比关键词变化
            s1, s2 = statements[0]["content"], statements[1]["content"]
            removed, added = [], []
            words1 = set(re.findall(r"\b\w{5,}\b", s1.lower()))
            words2 = set(re.findall(r"\b\w{5,}\b", s2.lower()))
            # 简单对比：s2新增的词
            for w in words2 - words1:
                if w in ["slowing", "weakening", "elevated", "restrictive", "patient"]:
                    added.append(w)
            return {
                "statement_date": statements[0]["date_label"],
                "changed_phrases": {"added": added, "removed": list(words1 - words2)[:5]},
                "rate_decision": "held"  # 简化，实际需解析
            }

    except Exception as e:
        logger.warning(f"[L1-Qual] fomc_statement_delta failed: {e}")

    return None


# ─────────────────────────────────────────────
# 3. Economic Calendar 7d
# ─────────────────────────────────────────────
def fetch_economic_calendar(target_date_str):
    """
    抓取未来7日重要经济数据发布日历（high importance only）
    数据源：手动维护的关键发布日期映射
    """
    # FRED calendar API 访问受限，改用已知日程
    # 每月固定发布日（美国市场）
    HIGH_IMPORTANCE_EVENTS = {
        # 月度数据
        "CPI":    {"name": "CPI 通胀数据", "typical_day": "10-14", "frequency": "monthly"},
        "PCE":    {"name": "PCE 核心通胀", "typical_day": "25-30", "frequency": "monthly"},
        "NFP":    {"name": "非农就业报告", "typical_day": "1-7", "frequency": "monthly"},
        "ISM":    {"name": "ISM 制造业PMI", "typical_day": "1-3", "frequency": "monthly"},
        "GDP":    {"name": "GDP 初值", "typical_day": "25-30", "frequency": "quarterly"},
        "Retail": {"name": "零售销售", "typical_day": "14-17", "frequency": "monthly"},
    }

    # 尝试从 FRED calendar 页面抓取
    events = []
    try:
        resp = requests.get(
            "https://fred.stlouisfed.org/release/calendar",
            headers=HEADERS, timeout=15
        )
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            rows = soup.select("table.calendar tr")
            target = date.fromisoformat(target_date_str)
            cutoff = (target + timedelta(days=7)).isoformat()
            for row in rows:
                cells = row.select("td")
                if len(cells) < 3:
                    continue
                date_text = cells[0].get_text(strip=True)
                event_name = cells[1].get_text(strip=True)
                importance = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                if importance.upper() in ("HIGH", "3", "***"):
                    events.append({
                        "event_name": event_name,
                        "scheduled_date": date_text,
                        "importance_level": "high"
                    })
    except Exception as e:
        logger.warning(f"[L1-Qual] economic_calendar failed: {e}")

    return events[:10]


# ─────────────────────────────────────────────
# 4. News Macro Headlines
# ─────────────────────────────────────────────
def fetch_news_headlines(target_date_str):
    """
    解析 Yahoo Finance / Dow Jones / MarketWatch / CNBC RSS，筛选宏观相关新闻标题
    """
    RSS_URLS = [
        ("Yahoo Finance", "https://finance.yahoo.com/news/rss"),
        ("Dow Jones", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
        ("MarketWatch", "https://feeds.marketwatch.com/marketwatch/topstories/"),
        ("CNBC", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ]

    FILTER_KEYWORDS = [
        "fed", "federal reserve", "fomc",
        "inflation", "cpi", "pce",
        "oil", "opec", "crude",
        "china", "tariff", "trade war",
        "recession", "gdp",
        "dollar", "dxy", "yuan",
        "gold", "haven"
    ]

    headlines = []
    for source_name, url in RSS_URLS:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=10)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "xml")
            items = soup.select("item") or soup.select("entry")
            for item in items[:20]:
                title = item.select_one("title")
                if not title:
                    continue
                title_text = title.get_text(strip=True)
                pub = item.select_one("pubDate") or item.select_one("published")
                pub_text = pub.get_text(strip=True) if pub else ""

                matched = any(kw in title_text.lower() for kw in FILTER_KEYWORDS)
                if matched:
                    headlines.append({
                        "headline": title_text,
                        "source": source_name,
                        "published_at": pub_text
                    })
        except Exception as e:
            logger.warning(f"[L1-Qual] news_headlines ({source_name}) failed: {e}")

    return headlines[:10]


# ─────────────────────────────────────────────
# 5. COT Market Positioning
# ─────────────────────────────────────────────
def fetch_cot_positioning(target_date_str):
    """
    爬取 CFTC COT 每周持仓报告（每周五发布）
    source: https://www.cftc.gov/dea/futures/deacmesf.htm
    """
    instruments = [
        ("Gold", "GC"),
        ("WTI Crude", "CL"),
        ("USD Index", "DX"),
    ]

    results = []
    try:
        resp = requests.get(
            "https://www.cftc.gov/dea/futures/deacmesf.htm",
            headers=HEADERS, timeout=20
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        tables = soup.select("table")

        for table in tables:
            rows = table.select("tr")
            for row in rows:
                cells = row.select("td")
                if len(cells) < 5:
                    continue
                code = cells[0].get_text(strip=True)
                market = cells[1].get_text(strip=True)
                net_pos = cells[-1].get_text(strip=True) if cells else ""

                matched = any(inst in market or inst in code for inst, _ in instruments)
                if matched and net_pos.lstrip("-").isdigit():
                    results.append({
                        "instrument": market,
                        "report_date": date.today().isoformat(),
                        "net_speculative_position": int(net_pos),
                        "change_from_prior_week": 0  # 简化：需两次数据对比
                    })
    except Exception as e:
        logger.warning(f"[L1-Qual] cot_positioning failed: {e}")

    return results[:5]


# ─────────────────────────────────────────────
# 6. ISM Manufacturing PMI
# ─────────────────────────────────────────────
def fetch_ism_pmi(target_date_str=None):
    """
    从 tradingeconomics.com 抓取最新 ISM 制造业 PMI
    （2020年后 ISM 已停止向 FRED 提供数据，改用此源）
    """
    import re
    try:
        resp = requests.get(
            "https://tradingeconomics.com/united-states/manufacturing-pmi",
            headers=HEADERS, timeout=15
        )
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        all_text = soup.get_text()

        # 页面结构：'ISM Manufacturing PMI52.7052.40pointsMar 2026'
        match = re.search(r'ISM Manufacturing PMI(\d+\.\d+)(\d+\.\d+)points([A-Za-z]+)\s*(\d{4})', all_text)
        if match:
            current = float(match.group(1))
            previous = float(match.group(2))
            month_str = match.group(3)
            year = int(match.group(4))
            return {
                "value": current,
                "previous": previous,
                "month": month_str,
                "year": year,
            }

        # 备选：找 td 表格
        for td in soup.find_all('td'):
            text = td.get_text(strip=True)
            if re.match(r'^\d+\.\d+$', text) and 40 <= float(text) <= 70:
                parent = td.find_parent('tr')
                if parent and 'ISM' in parent.get_text():
                    row_text = re.findall(r'(\d+\.\d+)', parent.get_text())
                    if len(row_text) >= 2:
                        return {
                            "value": float(row_text[0]),
                            "previous": float(row_text[1]),
                            "month": month_str if 'month_str' in dir() else date.today().strftime("%b"),
                            "year": date.today().year,
                        }
    except Exception as e:
        logger.warning(f"[L1-Qual] ism_pmi failed: {e}")

    return None


# ─────────────────────────────────────────────
# 汇总入口
# ─────────────────────────────────────────────
def fetch_all_qualitative(target_date_str):
    """L1.2 定性数据采集主函数"""
    sources = [
        ("fed_speech_tracker",    fetch_fed_speeches),
        ("fomc_statement_delta", fetch_fomc_statement_delta),
        ("economic_calendar_7d", fetch_economic_calendar),
        ("news_macro_headlines",  fetch_news_headlines),
        ("market_positioning",   fetch_cot_positioning),
        ("ism_pmi",              fetch_ism_pmi),   # 独立爬虫，非 FRED/OpenBB
    ]

    results = {}
    for source_id, fetcher in sources:
        try:
            data = fetcher(target_date_str)
            if data:
                db.upsert_qualitative(target_date_str, source_id, data)
                results[source_id] = data
                logger.info(f"[L1-Qual] {source_id}: {len(data) if isinstance(data, list) else 1} items")
            else:
                logger.warning(f"[L1-Qual] {source_id}: no data")
        except Exception as e:
            logger.warning(f"[L1-Qual] {source_id} failed: {e}")

    return results
