"""
推荐历史数据库
─────────────────────────────────────────────────────────────────────────────
每次"今日推荐 / 明日预判"真正重算（缓存未命中）时，把当批 Top 推荐股快照入库。
同一 (trade_date, mode, symbol) 只保留一行：
  - first_seen / last_seen / appear_count：当天它在多少次重算里出现、首末时间
  - peak_score：当天峰值评分
  - 其余字段 + snapshot(JSON)：保存最近一次完整快照（评分/理由/催化剂/价格/规则命中）
这样既能回看"那天为什么推荐它"，又不会被 5 分钟一次的重算灌成几十行。
"""
import sqlite3
import json
import os
from datetime import datetime, date, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "recommend_history.db")


def _conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    return sqlite3.connect(DB_PATH)


def init_db():
    with _conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS recommend_history (
                trade_date    TEXT NOT NULL,        -- YYYY-MM-DD
                mode          TEXT NOT NULL,         -- today / tomorrow
                symbol        TEXT NOT NULL,
                name          TEXT NOT NULL,
                first_seen    TEXT NOT NULL,         -- ISO datetime（当天首次入选）
                last_seen     TEXT NOT NULL,         -- ISO datetime（当天最近一次入选）
                appear_count  INTEGER DEFAULT 1,     -- 当天出现在多少次重算里
                peak_score    REAL DEFAULT 0,        -- 当天峰值评分
                score         REAL DEFAULT 0,        -- 最近一次评分
                price         REAL DEFAULT 0,        -- 最近一次价格
                pct_change    REAL DEFAULT 0,
                catalyst_type TEXT DEFAULT '',
                strength      TEXT DEFAULT '',
                sector        TEXT DEFAULT '',
                news_time     TEXT DEFAULT '',
                snapshot      TEXT NOT NULL,          -- 完整候选股 JSON
                PRIMARY KEY (trade_date, mode, symbol)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_symbol ON recommend_history(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_name   ON recommend_history(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rec_date   ON recommend_history(trade_date)")
        conn.commit()


def save_batch(trade_date: str, mode: str, stocks: list[dict]) -> int:
    """把一批推荐股 upsert 入库。已存在则累加出现次数、刷新最近快照、保留峰值评分。"""
    if not stocks:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    saved = 0
    with _conn() as conn:
        for s in stocks:
            symbol = str(s.get("symbol", "")).strip()
            name = str(s.get("name", "")).strip()
            if not symbol:
                continue
            score = float(s.get("score", 0) or 0)
            conn.execute("""
                INSERT INTO recommend_history
                    (trade_date, mode, symbol, name, first_seen, last_seen,
                     appear_count, peak_score, score, price, pct_change,
                     catalyst_type, strength, sector, news_time, snapshot)
                VALUES (?,?,?,?,?,?,1,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(trade_date, mode, symbol) DO UPDATE SET
                    last_seen     = excluded.last_seen,
                    appear_count  = appear_count + 1,
                    peak_score    = MAX(peak_score, excluded.peak_score),
                    score         = excluded.score,
                    price         = excluded.price,
                    pct_change    = excluded.pct_change,
                    catalyst_type = excluded.catalyst_type,
                    strength      = excluded.strength,
                    sector        = excluded.sector,
                    news_time     = excluded.news_time,
                    snapshot      = excluded.snapshot,
                    name          = excluded.name
            """, (
                trade_date, mode, symbol, name, now, now,
                score, score,                       # peak_score, score
                float(s.get("price", 0) or 0),
                float(s.get("pct_change", 0) or 0),
                str(s.get("catalyst_type", "")),
                str(s.get("strength", "")),
                str(s.get("sector", "")),
                str(s.get("news_time", "")),
                json.dumps(s, ensure_ascii=False),
            ))
            saved += 1
        conn.commit()
    return saved


_COLS = ["trade_date", "mode", "symbol", "name", "first_seen", "last_seen",
         "appear_count", "peak_score", "score", "price", "pct_change",
         "catalyst_type", "strength", "sector", "news_time", "snapshot"]


def _row_to_dict(row) -> dict:
    d = dict(zip(_COLS, row))
    try:
        snap = json.loads(d.pop("snapshot") or "{}")
    except Exception:
        snap = {}
    # 把快照里的理由/策略/规则命中带出来直接给前端用
    d["reasons"] = snap.get("reasons", [])
    d["strategy"] = snap.get("strategy", "")
    d["rule_hits"] = snap.get("rule_hits", [])
    d["tags"] = snap.get("tags", [])
    return d


def list_history(symbol: str = "", mode: str = "", days: int = 30, limit: int = 300) -> list[dict]:
    """查询历史。symbol 对名称/代码模糊匹配；days 限定最近天数；按日期倒序、当天按峰值降序。"""
    where, args = [], []
    if symbol:
        where.append("(symbol LIKE ? OR name LIKE ?)")
        args += [f"%{symbol}%", f"%{symbol}%"]
    if mode:
        where.append("mode = ?")
        args.append(mode)
    if days and days > 0:
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        where.append("trade_date >= ?")
        args.append(cutoff)

    sql = f"SELECT {', '.join(_COLS)} FROM recommend_history"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY trade_date DESC, peak_score DESC LIMIT ?"
    args.append(limit)

    with _conn() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_dict(r) for r in rows]


def list_dates(days: int = 60) -> list[dict]:
    """每个交易日的推荐股数量（历史时间线用）"""
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with _conn() as conn:
        rows = conn.execute(
            "SELECT trade_date, COUNT(*) FROM recommend_history "
            "WHERE trade_date >= ? GROUP BY trade_date ORDER BY trade_date DESC",
            (cutoff,),
        ).fetchall()
    return [{"date": r[0], "count": r[1]} for r in rows]


def stats() -> dict:
    with _conn() as conn:
        total = conn.execute("SELECT COUNT(*) FROM recommend_history").fetchone()[0]
        days = conn.execute("SELECT COUNT(DISTINCT trade_date) FROM recommend_history").fetchone()[0]
    return {"total_records": total, "total_days": days}


init_db()
