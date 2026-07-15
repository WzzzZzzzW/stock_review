"""
今日市场复盘历史数据库
每日多维度复盘数据永久保存，允许重新生成覆盖（INSERT OR REPLACE）。
结构与 limitup_db.py 一致，方便日历翻阅历史。
"""
import sqlite3, json, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "market_review.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS market_daily (
                trade_date      TEXT PRIMARY KEY,   -- YYYY-MM-DD
                generated_at    TEXT NOT NULL,
                up_count        INTEGER DEFAULT 0,  -- 上涨家数
                down_count      INTEGER DEFAULT 0,  -- 下跌家数
                zt_count        INTEGER DEFAULT 0,  -- 涨停数
                sentiment_score INTEGER DEFAULT 0,  -- 情绪温度 0-100
                data            TEXT NOT NULL        -- full JSON
            )
        """)
        conn.commit()


def save_daily(trade_date: str, payload: dict):
    """保存当日复盘数据，已存在则覆盖（允许重新生成）"""
    breadth = payload.get("breadth", {}) or {}
    sentiment = payload.get("sentiment", {}) or {}
    limit_stats = payload.get("limit_stats", {}) or {}
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO market_daily
                (trade_date, generated_at, up_count, down_count, zt_count, sentiment_score, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            trade_date,
            datetime.now().isoformat(),
            int(breadth.get("up", 0) or 0),
            int(breadth.get("down", 0) or 0),
            int(limit_stats.get("zt_count", 0) or 0),
            int(sentiment.get("score", 0) or 0),
            json.dumps(payload, ensure_ascii=False),
        ))
        conn.commit()


def get_daily(trade_date: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT data FROM market_daily WHERE trade_date = ?", (trade_date,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def list_dates() -> list[dict]:
    """返回所有有记录的日期及关键指标，降序"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT trade_date, up_count, down_count, zt_count, sentiment_score, generated_at "
            "FROM market_daily ORDER BY trade_date DESC"
        ).fetchall()
    return [
        {
            "date": r[0],
            "up_count": r[1],
            "down_count": r[2],
            "zt_count": r[3],
            "sentiment_score": r[4],
            "generated_at": r[5],
        }
        for r in rows
    ]


def get_latest_date() -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT trade_date FROM market_daily ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None
