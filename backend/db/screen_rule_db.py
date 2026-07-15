"""
选股规则库 —— 持久化用户自定义的选股规则。
每条规则 = 一组结构化筛选条件（+ 可选 universe 排除项 + 排序），命名、可收藏。
点开一条规则即按其条件实时筛选全市场股票。

两类来源：
  · source='user' —— 用户自己搭建/保存的规则
  · source='auto' —— 每日 AI 推送规则（读新闻+行业自动生成），与用户规则分区展示
两种筛选方式：
  · kind='numeric' —— 纯数值条件（用现成引擎跑全市场）
  · kind='theme'   —— 题材规则：先取某行业/题材成分股，再叠加数值条件
"""
import os
import json
import uuid
import sqlite3
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "screen_rules.db")


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS screen_rules (
                id          TEXT PRIMARY KEY,
                name        TEXT NOT NULL,
                conditions  TEXT NOT NULL DEFAULT '[]',
                logic       TEXT NOT NULL DEFAULT 'AND',
                universe    TEXT NOT NULL DEFAULT '{}',
                nl_source   TEXT DEFAULT '',
                sort_field  TEXT DEFAULT 'change_pct',
                sort_dir    TEXT DEFAULT 'desc',
                favorite    INTEGER DEFAULT 0,
                created_at  TEXT,
                updated_at  TEXT,
                sort_order  INTEGER DEFAULT 0
            )
        """)
        # ── 迁移：为老库补齐推送相关列 ──
        cols = {r["name"] for r in c.execute("PRAGMA table_info(screen_rules)").fetchall()}
        migrations = {
            "source":    "TEXT DEFAULT 'user'",      # user | auto
            "kind":      "TEXT DEFAULT 'numeric'",   # numeric | theme
            "theme":     "TEXT DEFAULT ''",          # 行业/题材名（kind=theme 时用）
            "why":       "TEXT DEFAULT ''",          # 推送规则的理由（数据/新闻依据）
            "auto_date": "TEXT DEFAULT ''",          # 推送批次日期 YYYY-MM-DD
        }
        for col, decl in migrations.items():
            if col not in cols:
                c.execute(f"ALTER TABLE screen_rules ADD COLUMN {col} {decl}")


def _row_to_dict(r: sqlite3.Row) -> dict:
    keys = r.keys()
    return {
        "id":         r["id"],
        "name":       r["name"],
        "conditions": json.loads(r["conditions"] or "[]"),
        "logic":      r["logic"] or "AND",
        "universe":   json.loads(r["universe"] or "{}"),
        "nl_source":  r["nl_source"] or "",
        "sort_field": r["sort_field"] or "change_pct",
        "sort_dir":   r["sort_dir"] or "desc",
        "favorite":   bool(r["favorite"]),
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "sort_order": r["sort_order"],
        "source":     (r["source"] if "source" in keys else "user") or "user",
        "kind":       (r["kind"] if "kind" in keys else "numeric") or "numeric",
        "theme":      (r["theme"] if "theme" in keys else "") or "",
        "why":        (r["why"] if "why" in keys else "") or "",
        "auto_date":  (r["auto_date"] if "auto_date" in keys else "") or "",
    }


def create_rule(name: str, conditions: list, logic: str = "AND",
                universe: dict | None = None, nl_source: str = "",
                sort_field: str = "change_pct", sort_dir: str = "desc",
                *, source: str = "user", kind: str = "numeric",
                theme: str = "", why: str = "", auto_date: str = "") -> str:
    rid = uuid.uuid4().hex[:12]
    now = datetime.now().isoformat()
    with _conn() as c:
        row = c.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM screen_rules").fetchone()
        order = row["n"]
        c.execute(
            """INSERT INTO screen_rules
               (id, name, conditions, logic, universe, nl_source, sort_field, sort_dir,
                favorite, created_at, updated_at, sort_order,
                source, kind, theme, why, auto_date)
               VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?)""",
            (rid, name,
             json.dumps(conditions, ensure_ascii=False),
             logic,
             json.dumps(universe or {}, ensure_ascii=False),
             nl_source, sort_field, sort_dir, now, now, order,
             source, kind, theme, why, auto_date),
        )
    return rid


def update_rule(rid: str, *, name: str, conditions: list, logic: str,
                universe: dict, nl_source: str, sort_field: str, sort_dir: str) -> None:
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute(
            """UPDATE screen_rules
               SET name=?, conditions=?, logic=?, universe=?, nl_source=?,
                   sort_field=?, sort_dir=?, updated_at=?
               WHERE id=?""",
            (name,
             json.dumps(conditions, ensure_ascii=False),
             logic,
             json.dumps(universe or {}, ensure_ascii=False),
             nl_source, sort_field, sort_dir, now, rid),
        )


def list_rules(source: str | None = None) -> list[dict]:
    """source=None 全部；'user'/'auto' 仅取该来源。推送规则按生成顺序，用户规则收藏置顶。"""
    with _conn() as c:
        if source:
            rows = c.execute(
                "SELECT * FROM screen_rules WHERE source=? "
                "ORDER BY favorite DESC, sort_order ASC, created_at ASC",
                (source,),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM screen_rules "
                "ORDER BY favorite DESC, sort_order ASC, created_at ASC"
            ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_rule(rid: str) -> dict | None:
    with _conn() as c:
        r = c.execute("SELECT * FROM screen_rules WHERE id=?", (rid,)).fetchone()
    return _row_to_dict(r) if r else None


def delete_rule(rid: str) -> None:
    with _conn() as c:
        c.execute("DELETE FROM screen_rules WHERE id=?", (rid,))


def toggle_favorite(rid: str) -> bool:
    with _conn() as c:
        r = c.execute("SELECT favorite FROM screen_rules WHERE id=?", (rid,)).fetchone()
        if not r:
            return False
        new_val = 0 if r["favorite"] else 1
        c.execute("UPDATE screen_rules SET favorite=? WHERE id=?", (new_val, rid))
    return bool(new_val)


# ── 推送规则专用 ───────────────────────────────────────────────────────────────

def replace_auto_rules(rules: list[dict], auto_date: str) -> int:
    """
    用新一批推送规则替换旧的（整批刷新）。
    rules: [{name, why, kind, theme, conditions, logic, universe, sort_field, sort_dir}, ...]
    返回插入条数。旧的 source='auto' 规则会被清空（用户想留就先「保存为我的」转成 user）。
    """
    now = datetime.now().isoformat()
    with _conn() as c:
        c.execute("DELETE FROM screen_rules WHERE source='auto'")
        base = c.execute("SELECT COALESCE(MAX(sort_order), 0) AS n FROM screen_rules").fetchone()["n"]
        n = 0
        for i, r in enumerate(rules, 1):
            rid = uuid.uuid4().hex[:12]
            c.execute(
                """INSERT INTO screen_rules
                   (id, name, conditions, logic, universe, nl_source, sort_field, sort_dir,
                    favorite, created_at, updated_at, sort_order,
                    source, kind, theme, why, auto_date)
                   VALUES (?,?,?,?,?,?,?,?,0,?,?,?,?,?,?,?,?)""",
                (rid, (r.get("name") or "推送规则")[:20],
                 json.dumps(r.get("conditions") or [], ensure_ascii=False),
                 "OR" if str(r.get("logic", "AND")).upper() == "OR" else "AND",
                 json.dumps(r.get("universe") or {}, ensure_ascii=False),
                 "", r.get("sort_field") or "change_pct", r.get("sort_dir") or "desc",
                 now, now, base + i,
                 "auto", r.get("kind") or "numeric",
                 r.get("theme") or "", r.get("why") or "", auto_date),
            )
            n += 1
    return n


def convert_to_user(rid: str) -> dict | None:
    """把一条推送规则「保存为我的」——改 source=user，使其不被每日刷新清掉。"""
    now = datetime.now().isoformat()
    with _conn() as c:
        r = c.execute("SELECT * FROM screen_rules WHERE id=?", (rid,)).fetchone()
        if not r:
            return None
        c.execute(
            "UPDATE screen_rules SET source='user', auto_date='', updated_at=? WHERE id=?",
            (now, rid),
        )
        r2 = c.execute("SELECT * FROM screen_rules WHERE id=?", (rid,)).fetchone()
    return _row_to_dict(r2)
