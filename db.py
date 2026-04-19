import sqlite3
import json
import os
from config.settings import DB_PATH

def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_indicators (
            date        TEXT NOT NULL,
            series_id   TEXT NOT NULL,
            value       REAL,
            source      TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            is_stale    INTEGER DEFAULT 0,
            PRIMARY KEY (date, series_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_signals (
            date            TEXT PRIMARY KEY,
            payload         TEXT NOT NULL,
            created_at      TEXT NOT NULL
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS daily_reports (
            date        TEXT PRIMARY KEY,
            content     TEXT NOT NULL,
            sent_at     TEXT,
            send_status TEXT DEFAULT 'pending'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS qualitative_context (
            date        TEXT NOT NULL,
            source_id   TEXT NOT NULL,
            content     TEXT NOT NULL,
            fetched_at  TEXT NOT NULL,
            PRIMARY KEY (date, source_id)
        )
    """)
    conn.commit()
    conn.close()

def upsert_indicator(date, series_id, value, source, is_stale=0):
    conn = get_conn()
    c = conn.cursor()
    from datetime import datetime
    fetched_at = datetime.now().isoformat()
    c.execute("""
        INSERT INTO daily_indicators (date, series_id, value, source, fetched_at, is_stale)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(date, series_id) DO UPDATE SET
            value=excluded.value, source=excluded.source,
            fetched_at=excluded.fetched_at, is_stale=excluded.is_stale
    """, (date, series_id, value, source, fetched_at, is_stale))
    conn.commit()
    conn.close()

def upsert_signal(date, payload):
    conn = get_conn()
    c = conn.cursor()
    from datetime import datetime
    created_at = datetime.now().isoformat()
    c.execute("""
        INSERT INTO daily_signals (date, payload, created_at)
        VALUES (?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET payload=excluded.payload, created_at=excluded.created_at
    """, (date, json.dumps(payload), created_at))
    conn.commit()
    conn.close()

def upsert_qualitative(date, source_id, content):
    conn = get_conn()
    c = conn.cursor()
    from datetime import datetime
    fetched_at = datetime.now().isoformat()
    c.execute("""
        INSERT INTO qualitative_context (date, source_id, content, fetched_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date, source_id) DO UPDATE SET
            content=excluded.content, fetched_at=excluded.fetched_at
    """, (date, source_id, json.dumps(content, ensure_ascii=False), fetched_at))
    conn.commit()
    conn.close()

def get_qualitative(date, source_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM qualitative_context WHERE date=? AND source_id=?", (date, source_id))
    row = c.fetchone()
    conn.close()
    return json.loads(dict(row)["content"]) if row else None

def get_latest_qualitative(source_id, last_n_days=7):
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT * FROM qualitative_context
        WHERE source_id=? AND date >= date('now', '-{last_n_days} days')
        ORDER BY date DESC
    """, (source_id,))
    rows = c.fetchall()
    conn.close()
    return [json.loads(r["content"]) for r in rows]

def get_weekly_change(date_str):
    """计算每周变化：当日值 vs 7天前（跳过周末/假日自动回溯）"""
    from datetime import date, timedelta
    target = date.fromisoformat(date_str)
    week_ago = (target - timedelta(days=7)).isoformat()
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT date, series_id, value FROM daily_indicators WHERE date=? OR date=?",
              (date_str, week_ago))
    rows = c.fetchall()
    conn.close()
    by_series = {}
    for r in rows:
        by_series.setdefault(r["series_id"], {})[r["date"]] = r["value"]
    weekly = {}
    for series_id, values in by_series.items():
        today_val = values.get(date_str)
        week_val = values.get(week_ago)
        if today_val is not None and week_val is not None and week_val != 0:
            weekly[f"{series_id}_7d_delta"] = round(today_val - week_val, 4)
    return weekly

def update_report(date, content, sent_at=None, send_status='pending'):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        INSERT INTO daily_reports (date, content, sent_at, send_status)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(date) DO UPDATE SET
            content=excluded.content, sent_at=excluded.sent_at, send_status=excluded.send_status
    """, (date, content, sent_at, send_status))
    conn.commit()
    conn.close()

def get_indicator(date, series_id):
    """查询指定日期数据，自动回溯到最近有效交易日（跳过周末/假日）"""
    from datetime import date as date_type, timedelta
    conn = get_conn()
    c = conn.cursor()
    # 先查指定日期
    c.execute("SELECT * FROM daily_indicators WHERE date=? AND series_id=?", (date, series_id))
    row = c.fetchone()
    if row:
        conn.close()
        return dict(row)
    # 回溯：最多查7天
    target = date_type.fromisoformat(date)
    for days_back in range(1, 8):
        prev = (target - timedelta(days=days_back)).isoformat()
        c.execute("SELECT * FROM daily_indicators WHERE date=? AND series_id=?", (prev, series_id))
        row = c.fetchone()
        if row:
            conn.close()
            return dict(row)
    conn.close()
    return None

def get_latest_indicator_before(series_id, date, limit=1):
    conn = get_conn()
    c = conn.cursor()
    c.execute("""
        SELECT * FROM daily_indicators
        WHERE series_id=? AND date < ?
        ORDER BY date DESC LIMIT ?
    """, (series_id, date, limit))
    rows = c.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_indicators_by_date(date):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM daily_indicators WHERE date=?", (date,))
    rows = c.fetchall()
    conn.close()
    return {r["series_id"]: dict(r) for r in rows}

def get_signal(date):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM daily_signals WHERE date=?", (date,))
    row = c.fetchone()
    conn.close()
    if row:
        return dict(row), json.loads(row["payload"])
    return None, None

def count_indicators(date):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM daily_indicators WHERE date=?", (date,))
    cnt = c.fetchone()["cnt"]
    conn.close()
    return cnt

def count_p0_non_stale(date):
    from config.indicators import INDICATORS_MANIFEST
    p0_ids = [i["id"] for i in INDICATORS_MANIFEST if i["priority"] == "P0"]
    placeholders = ",".join(["?"] * len(p0_ids))
    conn = get_conn()
    c = conn.cursor()
    c.execute(f"""
        SELECT COUNT(*) as cnt FROM daily_indicators
        WHERE date=? AND series_id IN ({placeholders}) AND is_stale=0
    """, [date] + p0_ids)
    cnt = c.fetchone()["cnt"]
    conn.close()
    return cnt
