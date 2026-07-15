"""
交易脑库 — SQLite 持久化
"""
import sqlite3
import uuid
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "brain.db"


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS brain_sources (
            id          TEXT PRIMARY KEY,
            content     TEXT NOT NULL,
            source_type TEXT DEFAULT 'manual',
            title       TEXT DEFAULT '',
            created_at  TEXT NOT NULL,
            rule_count  INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS brain_rules (
            id            TEXT PRIMARY KEY,
            source_id     TEXT,
            category      TEXT NOT NULL,
            rule          TEXT NOT NULL,
            conditions    TEXT DEFAULT '[]',
            tags          TEXT DEFAULT '[]',
            time_frame    TEXT DEFAULT '',
            confidence    REAL DEFAULT 0.6,
            times_matched INTEGER DEFAULT 0,
            validated_win INTEGER DEFAULT 0,
            validated_loss INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL,
            FOREIGN KEY (source_id) REFERENCES brain_sources(id)
        );

        CREATE TABLE IF NOT EXISTS brain_playbook (
            id              TEXT PRIMARY KEY,
            category        TEXT NOT NULL,
            title           TEXT NOT NULL,
            content         TEXT NOT NULL,
            rule_ids        TEXT DEFAULT '[]',
            generated_at    TEXT NOT NULL
        );

        -- 自动导入去重表：记录已经消化过的内容指纹，避免重复入库
        CREATE TABLE IF NOT EXISTS brain_imported (
            uid         TEXT PRIMARY KEY,
            title       TEXT DEFAULT '',
            source      TEXT DEFAULT '',
            created_at  TEXT NOT NULL
        );

        -- 通用键值表：存自动导入最近一次运行摘要等
        CREATE TABLE IF NOT EXISTS brain_meta (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)

        # 迁移：软删除列。老库没有 deleted_at 则补上（空串=未删除，非空=删除时间）。
        # 软删除让「误点删除」可撤销，且删除的规则不再参与推荐匹配。
        cols = [r[1] for r in c.execute("PRAGMA table_info(brain_rules)").fetchall()]
        if "deleted_at" not in cols:
            c.execute("ALTER TABLE brain_rules ADD COLUMN deleted_at TEXT DEFAULT ''")

        # 迁移：政策/消息时间线。event_date=发布时间，effective_date=落地/生效时间。
        # 让规则带上「这条政策何时发布、何时落地」，匹配卡片可直接展示时间感。
        # 空串=新闻里未明确写明（不臆造）。
        if "event_date" not in cols:
            c.execute("ALTER TABLE brain_rules ADD COLUMN event_date TEXT DEFAULT ''")
        if "effective_date" not in cols:
            c.execute("ALTER TABLE brain_rules ADD COLUMN effective_date TEXT DEFAULT ''")


# ── Sources ───────────────────────────────────────────────────────────────────

def save_source(content: str, source_type: str = "manual", title: str = "") -> str:
    sid = str(uuid.uuid4())
    with _conn() as c:
        c.execute(
            "INSERT INTO brain_sources VALUES (?,?,?,?,?,?)",
            (sid, content, source_type, title, datetime.now().isoformat(), 0)
        )
    return sid


def update_source_rule_count(source_id: str, count: int):
    with _conn() as c:
        c.execute("UPDATE brain_sources SET rule_count=? WHERE id=?", (count, source_id))


def list_sources(limit: int = 50) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM brain_sources ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def delete_source(source_id: str):
    with _conn() as c:
        c.execute("DELETE FROM brain_rules WHERE source_id=?", (source_id,))
        c.execute("DELETE FROM brain_sources WHERE id=?", (source_id,))


# ── Rules ─────────────────────────────────────────────────────────────────────

def save_rules(rules: list[dict], source_id: str) -> list[str]:
    ids = []
    with _conn() as c:
        for r in rules:
            rid = str(uuid.uuid4())
            c.execute(
                # 具名列插入：表里多了 deleted_at/event_date/effective_date（默认空串），按位置插会列数对不上
                "INSERT INTO brain_rules "
                "(id, source_id, category, rule, conditions, tags, time_frame, "
                " confidence, times_matched, validated_win, validated_loss, created_at, "
                " event_date, effective_date) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    rid, source_id,
                    r.get("category", "other"),
                    r.get("rule", ""),
                    json.dumps(r.get("conditions", []), ensure_ascii=False),
                    json.dumps(r.get("tags", []), ensure_ascii=False),
                    r.get("time_frame", ""),
                    float(r.get("confidence", 0.6)),
                    0, 0, 0,
                    datetime.now().isoformat(),
                    str(r.get("event_date", "") or "")[:20],
                    str(r.get("effective_date", "") or "")[:20],
                )
            )
            ids.append(rid)
    return ids


def list_rules(category: str = "", limit: int = 200) -> list[dict]:
    with _conn() as c:
        if category:
            rows = c.execute(
                "SELECT * FROM brain_rules WHERE category=? AND (deleted_at IS NULL OR deleted_at='') "
                "ORDER BY confidence DESC, created_at DESC LIMIT ?",
                (category, limit)
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM brain_rules WHERE (deleted_at IS NULL OR deleted_at='') "
                "ORDER BY confidence DESC, created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["conditions"] = json.loads(d["conditions"])
        d["tags"] = json.loads(d["tags"])
        result.append(d)
    return result


def list_rules_by_source(source_id: str) -> list[dict]:
    """某条来源提炼出的（未删除）规则，按置信度倒序。"""
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM brain_rules WHERE source_id=? AND (deleted_at IS NULL OR deleted_at='') "
            "ORDER BY confidence DESC, created_at DESC",
            (source_id,)
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["conditions"] = json.loads(d["conditions"])
        d["tags"] = json.loads(d["tags"])
        result.append(d)
    return result


def get_rule(rule_id: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM brain_rules WHERE id=?", (rule_id,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["conditions"] = json.loads(d["conditions"])
    d["tags"] = json.loads(d["tags"])
    return d


def update_confidence(rule_id: str, delta: float):
    with _conn() as c:
        c.execute(
            "UPDATE brain_rules SET confidence = MIN(1.0, MAX(0.1, confidence + ?)) WHERE id=?",
            (delta, rule_id)
        )


def validate_rule(rule_id: str, win: bool):
    col = "validated_win" if win else "validated_loss"
    with _conn() as c:
        c.execute(f"UPDATE brain_rules SET {col}={col}+1 WHERE id=?", (rule_id,))
        # 赢加置信度，输减置信度
        delta = 0.05 if win else -0.08
        c.execute(
            "UPDATE brain_rules SET confidence=MIN(1.0,MAX(0.1,confidence+?)) WHERE id=?",
            (delta, rule_id)
        )


def increment_matched(rule_id: str):
    with _conn() as c:
        c.execute("UPDATE brain_rules SET times_matched=times_matched+1 WHERE id=?", (rule_id,))


def delete_rule(rule_id: str):
    """软删除：标记 deleted_at，列表/匹配里不再出现，但可 restore_rule 撤销。"""
    with _conn() as c:
        c.execute(
            "UPDATE brain_rules SET deleted_at=? WHERE id=?",
            (datetime.now().isoformat(), rule_id)
        )


def restore_rule(rule_id: str):
    """撤销删除：清掉 deleted_at 标记。"""
    with _conn() as c:
        c.execute("UPDATE brain_rules SET deleted_at='' WHERE id=?", (rule_id,))


def revert_validate(rule_id: str, win: bool, prev_confidence: float):
    """
    撤销一次「有效/无效」标记：把对应计数器减回去，并把置信度还原成点击前的精确值。
    不能简单地反向加减 delta——置信度有 0.1/1.0 夹断，边界会算歪，所以直接还原快照值。
    """
    col = "validated_win" if win else "validated_loss"
    with _conn() as c:
        c.execute(
            f"UPDATE brain_rules SET {col}=MAX(0,{col}-1), "
            "confidence=MIN(1.0,MAX(0.1,?)) WHERE id=?",
            (prev_confidence, rule_id)
        )


def unvalidate_rule(rule_id: str, win: bool):
    """
    点卡片上的「验证 N✓ M✗」计数撤回一次：对应计数器 -1，置信度做与 validate_rule
    相反的调整（win 撤回 -0.05，loss 撤回 +0.08）。
    与 revert_validate 的区别：这是「事后随时点计数」的入口，没有点击前快照，
    所以按 delta 反向；计数已是 0 时不做任何改动。
    """
    col = "validated_win" if win else "validated_loss"
    delta = -0.05 if win else 0.08      # validate 时 win+0.05 / loss-0.08，撤回取反
    with _conn() as c:
        cur = c.execute(f"SELECT {col} FROM brain_rules WHERE id=?", (rule_id,)).fetchone()
        if not cur or cur[0] <= 0:
            return
        c.execute(
            f"UPDATE brain_rules SET {col}=MAX(0,{col}-1), "
            "confidence=MIN(1.0,MAX(0.1,confidence+?)) WHERE id=?",
            (delta, rule_id)
        )


def count_rules() -> dict:
    with _conn() as c:
        rows = c.execute(
            "SELECT category, COUNT(*) as n FROM brain_rules "
            "WHERE (deleted_at IS NULL OR deleted_at='') GROUP BY category"
        ).fetchall()
    return {r["category"]: r["n"] for r in rows}


# ── 自动导入去重 ──────────────────────────────────────────────────────────────

def filter_unseen(uids: list[str]) -> set[str]:
    """返回这批 uid 中尚未导入过的集合"""
    if not uids:
        return set()
    with _conn() as c:
        placeholders = ",".join("?" * len(uids))
        rows = c.execute(
            f"SELECT uid FROM brain_imported WHERE uid IN ({placeholders})", uids
        ).fetchall()
    seen = {r["uid"] for r in rows}
    return {u for u in uids if u not in seen}


def mark_imported(items: list[dict]):
    """批量记录已导入的内容指纹。items: [{uid, title, source}]"""
    if not items:
        return
    now = datetime.now().isoformat()
    with _conn() as c:
        c.executemany(
            "INSERT OR IGNORE INTO brain_imported (uid, title, source, created_at) VALUES (?,?,?,?)",
            [(it["uid"], it.get("title", "")[:120], it.get("source", ""), now) for it in items],
        )


def count_imported() -> int:
    with _conn() as c:
        row = c.execute("SELECT COUNT(*) AS n FROM brain_imported").fetchone()
    return row["n"] if row else 0


# ── 通用键值（meta）────────────────────────────────────────────────────────────

def set_meta(key: str, value: str):
    with _conn() as c:
        c.execute(
            "INSERT INTO brain_meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def get_meta(key: str, default: str = "") -> str:
    with _conn() as c:
        row = c.execute("SELECT value FROM brain_meta WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


# ── Playbook ──────────────────────────────────────────────────────────────────

def save_playbook(items: list[dict]):
    with _conn() as c:
        c.execute("DELETE FROM brain_playbook")
        for item in items:
            c.execute(
                "INSERT INTO brain_playbook VALUES (?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    item.get("category", ""),
                    item.get("title", ""),
                    item.get("content", ""),
                    json.dumps(item.get("rule_ids", []), ensure_ascii=False),
                    datetime.now().isoformat(),
                )
            )


def get_playbook() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM brain_playbook ORDER BY category"
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["rule_ids"] = json.loads(d["rule_ids"])
        result.append(d)
    return result


init_db()
