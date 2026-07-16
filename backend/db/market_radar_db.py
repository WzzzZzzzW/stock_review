"""Intraday market radar snapshots and meaningful state-change events."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from typing import Iterator


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "market_radar.db")


@contextmanager
def _conn() -> Iterator[sqlite3.Connection]:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS market_radar_snapshot (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT NOT NULL,
                captured_at TEXT NOT NULL,
                phase       TEXT NOT NULL,
                market_data TEXT NOT NULL,
                sector_data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_radar_snapshot_date_time
                ON market_radar_snapshot(trade_date, captured_at DESC);

            CREATE TABLE IF NOT EXISTS market_radar_event (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_date  TEXT NOT NULL,
                event_key   TEXT NOT NULL,
                occurred_at TEXT NOT NULL,
                severity    TEXT NOT NULL,
                category    TEXT NOT NULL,
                title       TEXT NOT NULL,
                detail      TEXT NOT NULL,
                entity      TEXT DEFAULT '',
                UNIQUE(trade_date, event_key)
            );
            CREATE INDEX IF NOT EXISTS idx_radar_event_date_time
                ON market_radar_event(trade_date, occurred_at DESC);
        """)
        conn.commit()


def latest_snapshot(trade_date: str | None = None) -> dict | None:
    day = trade_date or date.today().isoformat()
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM market_radar_snapshot WHERE trade_date = ? "
            "ORDER BY captured_at DESC LIMIT 1",
            (day,),
        ).fetchone()
    return _snapshot_row(row) if row else None


def comparison_snapshot(trade_date: str | None = None, minutes_ago: int = 5) -> dict | None:
    day = trade_date or date.today().isoformat()
    cutoff = (datetime.now() - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM market_radar_snapshot WHERE trade_date = ? AND captured_at <= ? "
            "ORDER BY captured_at DESC LIMIT 1",
            (day, cutoff),
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT * FROM market_radar_snapshot WHERE trade_date = ? "
                "ORDER BY captured_at ASC LIMIT 1",
                (day,),
            ).fetchone()
    return _snapshot_row(row) if row else None


def latest_any_snapshot(before_date: str | None = None) -> dict | None:
    with _conn() as conn:
        if before_date:
            row = conn.execute(
                "SELECT * FROM market_radar_snapshot WHERE trade_date < ? "
                "ORDER BY trade_date DESC, captured_at DESC LIMIT 1",
                (before_date,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM market_radar_snapshot ORDER BY captured_at DESC LIMIT 1"
            ).fetchone()
    return _snapshot_row(row) if row else None


def list_snapshots(trade_date: str | None = None) -> list[dict]:
    day = trade_date or date.today().isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM market_radar_snapshot WHERE trade_date = ? ORDER BY captured_at ASC",
            (day,),
        ).fetchall()
    return [_snapshot_row(row) for row in rows]


def save_snapshot(phase: str, market: dict, sectors: list[dict], min_interval_seconds: int = 150) -> dict:
    day = date.today().isoformat()
    now = datetime.now()
    current = latest_snapshot(day)
    if current:
        try:
            age = (now - datetime.fromisoformat(current["captured_at"])).total_seconds()
            if age < min_interval_seconds:
                return current
        except ValueError:
            pass
    payload = {
        "trade_date": day,
        "captured_at": now.isoformat(timespec="seconds"),
        "phase": phase,
        "market": market,
        "sectors": sectors,
    }
    with _conn() as conn:
        conn.execute(
            "INSERT INTO market_radar_snapshot(trade_date, captured_at, phase, market_data, sector_data) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                day,
                payload["captured_at"],
                phase,
                json.dumps(market, ensure_ascii=False),
                json.dumps(sectors, ensure_ascii=False),
            ),
        )
        # This is an operational time series, not the permanent post-market archive.
        cutoff = (now.date() - timedelta(days=20)).isoformat()
        conn.execute("DELETE FROM market_radar_snapshot WHERE trade_date < ?", (cutoff,))
        conn.execute("DELETE FROM market_radar_event WHERE trade_date < ?", (cutoff,))
        conn.commit()
    return payload


def save_events(events: list[dict], trade_date: str | None = None) -> None:
    if not events:
        return
    day = trade_date or date.today().isoformat()
    now = datetime.now().isoformat(timespec="seconds")
    with _conn() as conn:
        for event in events:
            conn.execute(
                "INSERT OR IGNORE INTO market_radar_event "
                "(trade_date, event_key, occurred_at, severity, category, title, detail, entity) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    day,
                    str(event.get("key") or ""),
                    str(event.get("occurred_at") or now),
                    str(event.get("severity") or "info"),
                    str(event.get("category") or "market"),
                    str(event.get("title") or "市场变化"),
                    str(event.get("detail") or ""),
                    str(event.get("entity") or ""),
                ),
            )
        conn.commit()


def list_events(trade_date: str | None = None, limit: int = 12) -> list[dict]:
    day = trade_date or date.today().isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT event_key, occurred_at, severity, category, title, detail, entity "
            "FROM market_radar_event WHERE trade_date = ? "
            "ORDER BY occurred_at DESC LIMIT ?",
            (day, max(1, min(limit, 50))),
        ).fetchall()
    return [dict(row) for row in rows]


def _snapshot_row(row: sqlite3.Row) -> dict:
    return {
        "trade_date": row["trade_date"],
        "captured_at": row["captured_at"],
        "phase": row["phase"],
        "market": json.loads(row["market_data"]),
        "sectors": json.loads(row["sector_data"]),
    }


init_db()
