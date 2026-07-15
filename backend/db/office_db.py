"""
AI办公室 — 聊天历史持久化
"""
import sqlite3
import uuid
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "office.db"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS office_chats (
            id          TEXT PRIMARY KEY,
            mode        TEXT NOT NULL,    -- 'single' or 'conference'
            agent_ids   TEXT NOT NULL,    -- JSON 数组
            title       TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS office_messages (
            id          TEXT PRIMARY KEY,
            chat_id     TEXT NOT NULL,
            role        TEXT NOT NULL,    -- 'user' or 'assistant'
            agent_id    TEXT DEFAULT '',  -- 当role=assistant时记录哪个agent
            content     TEXT NOT NULL,
            is_synthesis INTEGER DEFAULT 0,
            created_at  TEXT NOT NULL,
            FOREIGN KEY (chat_id) REFERENCES office_chats(id)
        );

        CREATE INDEX IF NOT EXISTS idx_msg_chat ON office_messages(chat_id);
        """)


def create_chat(mode: str, agent_ids: list[str], title: str = "") -> str:
    cid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO office_chats VALUES (?,?,?,?,?,?)",
            (cid, mode, json.dumps(agent_ids), title, now, now)
        )
    return cid


def list_chats(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT c.*, (SELECT COUNT(*) FROM office_messages WHERE chat_id=c.id) as msg_count
               FROM office_chats c ORDER BY updated_at DESC LIMIT ?""", (limit,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["agent_ids"] = json.loads(d["agent_ids"])
        result.append(d)
    return result


def get_chat(chat_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM office_chats WHERE id=?", (chat_id,)).fetchone()
        if not row:
            return None
        msgs = c.execute(
            "SELECT * FROM office_messages WHERE chat_id=? ORDER BY created_at ASC", (chat_id,)
        ).fetchall()
    d = dict(row)
    d["agent_ids"] = json.loads(d["agent_ids"])
    d["messages"] = [dict(m) for m in msgs]
    return d


def add_message(chat_id: str, role: str, content: str, agent_id: str = "", is_synthesis: bool = False) -> str:
    mid = str(uuid.uuid4())
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            "INSERT INTO office_messages VALUES (?,?,?,?,?,?,?)",
            (mid, chat_id, role, agent_id, content, 1 if is_synthesis else 0, now)
        )
        c.execute("UPDATE office_chats SET updated_at=? WHERE id=?", (now, chat_id))
    return mid


def update_chat_title(chat_id: str, title: str):
    with _conn() as c:
        c.execute("UPDATE office_chats SET title=? WHERE id=?", (title, chat_id))


def delete_chat(chat_id: str):
    with _conn() as c:
        c.execute("DELETE FROM office_messages WHERE chat_id=?", (chat_id,))
        c.execute("DELETE FROM office_chats WHERE id=?", (chat_id,))


init_db()
