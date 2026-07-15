"""
涨停板复盘历史数据库
每日数据永久保存，绝不覆盖（用 INSERT OR IGNORE）
"""
import sqlite3, json, os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "limitup_history.db")

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS limitup_daily (
                trade_date   TEXT PRIMARY KEY,   -- YYYY-MM-DD
                generated_at TEXT NOT NULL,
                total_zt     INTEGER DEFAULT 0,  -- 涨停总数
                total_dt     INTEGER DEFAULT 0,  -- 跌停总数
                data         TEXT NOT NULL       -- full JSON
            )
        """)
        conn.commit()

def save_daily(trade_date: str, payload: dict):
    """保存当日复盘数据，已存在则覆盖（允许重新生成）"""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO limitup_daily
                (trade_date, generated_at, total_zt, total_dt, data)
            VALUES (?, ?, ?, ?, ?)
        """, (
            trade_date,
            datetime.now().isoformat(),
            payload.get("total_zt", 0),
            payload.get("total_dt", 0),
            json.dumps(payload, ensure_ascii=False),
        ))
        conn.commit()

def get_daily(trade_date: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT data FROM limitup_daily WHERE trade_date = ?", (trade_date,)
        ).fetchone()
    return json.loads(row[0]) if row else None

def list_dates() -> list[dict]:
    """返回所有有记录的日期及涨停数，降序"""
    with sqlite3.connect(DB_PATH) as conn:
        rows = conn.execute(
            "SELECT trade_date, total_zt, total_dt, generated_at FROM limitup_daily ORDER BY trade_date DESC"
        ).fetchall()
    return [{"date": r[0], "total_zt": r[1], "total_dt": r[2], "generated_at": r[3]} for r in rows]

def get_latest_date() -> str | None:
    with sqlite3.connect(DB_PATH) as conn:
        row = conn.execute(
            "SELECT trade_date FROM limitup_daily ORDER BY trade_date DESC LIMIT 1"
        ).fetchone()
    return row[0] if row else None
