"""
今日复盘历史数据库
每天保存一份「今日」总复盘，供日历回看。
"""
import json
import os
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "today_review.db")


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS today_review (
                trade_date      TEXT PRIMARY KEY,
                generated_at    TEXT NOT NULL,
                sentiment_score INTEGER DEFAULT 0,
                position_count  INTEGER DEFAULT 0,
                watch_count     INTEGER DEFAULT 0,
                data            TEXT NOT NULL
            )
        """)
        conn.commit()


def save_daily(trade_date: str, payload: dict):
    market = payload.get("market", {}) or {}
    sentiment = market.get("sentiment", {}) or {}
    portfolio = payload.get("portfolio", {}) or {}
    watchlist = payload.get("watchlist", {}) or {}
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO today_review
                (trade_date, generated_at, sentiment_score, position_count, watch_count, data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            trade_date,
            datetime.now().isoformat(),
            int(sentiment.get("score", 0) or 0),
            int(portfolio.get("summary", {}).get("position_count", 0) or 0),
            int(watchlist.get("summary", {}).get("count", 0) or 0),
            json.dumps(payload, ensure_ascii=False),
        ))
        conn.commit()


def get_daily(trade_date: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT data FROM today_review WHERE trade_date = ?", (trade_date,)
        ).fetchone()
    return json.loads(row[0]) if row else None


def list_dates() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT trade_date, sentiment_score, position_count, watch_count, generated_at "
            "FROM today_review ORDER BY trade_date DESC"
        ).fetchall()
    return [
        {
            "date": r[0],
            "sentiment_score": r[1],
            "position_count": r[2],
            "watch_count": r[3],
            "generated_at": r[4],
        }
        for r in rows
    ]


def get_latest_date() -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT trade_date FROM today_review ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None
