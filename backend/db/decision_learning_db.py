"""Persistent decision ledger and bounded learning versions."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterator


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "decision_learning.db")


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
            CREATE TABLE IF NOT EXISTS decision_record (
                trade_date     TEXT PRIMARY KEY,
                created_at     TEXT NOT NULL,
                engine_version TEXT NOT NULL,
                source         TEXT NOT NULL,
                decision_data  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS decision_outcome (
                decision_date TEXT PRIMARY KEY,
                outcome_date  TEXT NOT NULL,
                evaluated_at  TEXT NOT NULL,
                outcome_data  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_decision_outcome_date
                ON decision_outcome(outcome_date DESC);

            CREATE TABLE IF NOT EXISTS learning_version (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                version      TEXT NOT NULL UNIQUE,
                created_at   TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                status       TEXT NOT NULL,
                weights_data TEXT NOT NULL,
                metrics_data TEXT NOT NULL,
                changes_data TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_learning_version_status
                ON learning_version(status, id DESC);
        """)
        conn.commit()


def _loads(value: str) -> dict:
    try:
        data = json.loads(value)
        return data if isinstance(data, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def save_decision(trade_date: str, payload: dict, engine_version: str, source: str = "live") -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO decision_record "
            "(trade_date, created_at, engine_version, source, decision_data) VALUES (?, ?, ?, ?, ?)",
            (
                trade_date,
                datetime.now().isoformat(),
                engine_version,
                source,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()


def get_decision(trade_date: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM decision_record WHERE trade_date = ?", (trade_date,)
        ).fetchone()
    return _decision_row(row) if row else None


def previous_decision(before_date: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM decision_record WHERE trade_date < ? "
            "ORDER BY trade_date DESC LIMIT 1",
            (before_date,),
        ).fetchone()
    return _decision_row(row) if row else None


def list_decisions(limit: int = 120) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM decision_record ORDER BY trade_date DESC LIMIT ?",
            (max(1, min(limit, 500)),),
        ).fetchall()
    return [_decision_row(row) for row in rows]


def save_outcome(decision_date: str, outcome_date: str, payload: dict) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO decision_outcome "
            "(decision_date, outcome_date, evaluated_at, outcome_data) VALUES (?, ?, ?, ?)",
            (
                decision_date,
                outcome_date,
                datetime.now().isoformat(),
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        conn.commit()


def get_outcome(decision_date: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM decision_outcome WHERE decision_date = ?", (decision_date,)
        ).fetchone()
    return _outcome_row(row) if row else None


def list_outcomes(limit: int = 240) -> list[dict]:
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM decision_outcome ORDER BY decision_date DESC LIMIT ?",
            (max(1, min(limit, 1000)),),
        ).fetchall()
    return [_outcome_row(row) for row in reversed(rows)]


def save_learning_version(
    version: str,
    sample_count: int,
    status: str,
    weights: dict,
    metrics: dict,
    changes: dict,
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO learning_version "
            "(version, created_at, sample_count, status, weights_data, metrics_data, changes_data) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                version,
                datetime.now().isoformat(),
                sample_count,
                status,
                json.dumps(weights, ensure_ascii=False),
                json.dumps(metrics, ensure_ascii=False),
                json.dumps(changes, ensure_ascii=False),
            ),
        )
        conn.commit()


def latest_effective_version() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM learning_version WHERE status = 'promoted' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _version_row(row) if row else None


def latest_learning_attempt() -> dict | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM learning_version ORDER BY id DESC LIMIT 1"
        ).fetchone()
    return _version_row(row) if row else None


def _decision_row(row: sqlite3.Row) -> dict:
    return {
        "trade_date": row["trade_date"],
        "created_at": row["created_at"],
        "engine_version": row["engine_version"],
        "source": row["source"],
        "decision": _loads(row["decision_data"]),
    }


def _outcome_row(row: sqlite3.Row) -> dict:
    return {
        "decision_date": row["decision_date"],
        "outcome_date": row["outcome_date"],
        "evaluated_at": row["evaluated_at"],
        "outcome": _loads(row["outcome_data"]),
    }


def _version_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "version": row["version"],
        "created_at": row["created_at"],
        "sample_count": row["sample_count"],
        "status": row["status"],
        "weights": _loads(row["weights_data"]),
        "metrics": _loads(row["metrics_data"]),
        "changes": _loads(row["changes_data"]),
    }


init_db()
