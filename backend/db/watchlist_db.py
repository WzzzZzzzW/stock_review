"""Server-side watchlist persistence shared by the browser and background jobs."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "watchlist.db")


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                symbol     TEXT PRIMARY KEY,
                name       TEXT DEFAULT '',
                added_date TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()


def list_items() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT symbol, name, added_date FROM watchlist "
            "ORDER BY added_date DESC, symbol ASC"
        ).fetchall()
    return [
        {"code": row["symbol"], "name": row["name"] or "", "date": row["added_date"]}
        for row in rows
    ]


def upsert_item(symbol: str, name: str = "", added_date: str = "") -> dict:
    code = str(symbol).strip().zfill(6)
    if len(code) != 6 or not code.isdigit():
        raise ValueError("股票代码必须为6位数字")
    day = added_date or date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        conn.execute("""
            INSERT INTO watchlist(symbol, name, added_date, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                name = CASE WHEN excluded.name <> '' THEN excluded.name ELSE watchlist.name END,
                updated_at = excluded.updated_at
        """, (code, name.strip(), day, now))
        conn.commit()
    return {"code": code, "name": name.strip(), "date": day}


def merge_items(items: list[dict]) -> list[dict]:
    for item in items:
        try:
            upsert_item(
                item.get("code") or item.get("symbol") or "",
                item.get("name") or "",
                item.get("date") or "",
            )
        except ValueError:
            continue
    return list_items()


def delete_item(symbol: str) -> bool:
    with _conn() as conn:
        cursor = conn.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol.strip().zfill(6),))
        conn.commit()
    return cursor.rowcount > 0


init_db()

