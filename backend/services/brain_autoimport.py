"""
脑库每日自动导入 —— 编排层

流程：
  1. 从 cn_brain_fetcher 聚合中国财经内容
  2. 用 brain_imported 去重（跨天）
  3. 按 bucket(news/policy/research) 分组，打包成"摘要文档"
     —— 单条快讯喂 AI 会产出垃圾规则，打包成日摘要才能提炼出题材/资金/宏观级规则
  4. 每个文档 → brain_db.save_source(source_type='auto_xxx') + brain_service.extract_rules
  5. 标记所有消化过的 uid，写入运行摘要

成本：每次最多 ~6 次 deepseek-flash 调用，约 ¥0.01 量级。
"""
import json
import threading
from datetime import datetime

from data import cn_brain_fetcher
from data.cn_brain_fetcher import DEFAULT_RSS_FEEDS
from db import brain_db
from services import brain_service

# 每个 bucket 的分块大小（多少条内容打包进一个摘要文档）
_CHUNK_SIZE = {
    "news": 14,
    "policy": 8,
    "research": 24,
    "article": 6,    # 深度长文较长，每篇少打包几条
}
# 每次运行每个 bucket 最多生成几个文档（成本/质量护栏）
_MAX_DOCS_PER_BUCKET = {
    "news": 3,
    "policy": 1,
    "research": 2,
    "article": 3,
}

_RSS_META_KEY = "rss_feeds"


# ── RSS 源列表管理（存 brain_db meta，缺省回退到内置默认）──────────────────────

def get_rss_feeds() -> list[dict]:
    raw = brain_db.get_meta(_RSS_META_KEY, "")
    if not raw:
        return list(DEFAULT_RSS_FEEDS)
    try:
        feeds = json.loads(raw)
        return feeds if isinstance(feeds, list) else list(DEFAULT_RSS_FEEDS)
    except Exception:
        return list(DEFAULT_RSS_FEEDS)


def set_rss_feeds(feeds: list[dict]):
    clean = []
    seen = set()
    for f in feeds:
        url = (f.get("url") or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        clean.append({"url": url, "name": (f.get("name") or url).strip()})
    brain_db.set_meta(_RSS_META_KEY, json.dumps(clean, ensure_ascii=False))
    return clean


def add_rss_feed(url: str, name: str = "") -> list[dict]:
    feeds = get_rss_feeds()
    feeds.append({"url": url.strip(), "name": (name or url).strip()})
    return set_rss_feeds(feeds)


def remove_rss_feed(url: str) -> list[dict]:
    feeds = [f for f in get_rss_feeds() if f.get("url") != url.strip()]
    return set_rss_feeds(feeds)

_lock = threading.Lock()
_status: dict = {"running": False, "progress": ""}


def get_status() -> dict:
    """当前运行状态 + 最近一次运行摘要"""
    last = brain_db.get_meta("autoimport_last_run", "")
    try:
        last_run = json.loads(last) if last else None
    except Exception:
        last_run = None
    return {**_status, "last_run": last_run, "total_imported": brain_db.count_imported()}


def _build_doc(bucket: str, chunk: list[dict]) -> str:
    """把一批条目拼成一篇供 AI 提炼的文档"""
    label = cn_brain_fetcher.BUCKET_LABEL.get(bucket, bucket)
    lines = [f"以下是今日多条{label}，请从中提炼可复用的交易经验/题材逻辑/资金与情绪信号：\n"]
    for i, it in enumerate(chunk, 1):
        title = it.get("title", "").strip()
        content = it.get("content", "").strip()
        src = it.get("source", "")
        pub = (it.get("published", "") or "").strip()
        body = content if content else title
        # 带上发布日期，供 AI 提炼 event_date（政策/消息时间线）
        date_tag = f" [发布:{pub[:30]}]" if pub else ""
        # 控制单条长度，避免 token 浪费
        lines.append(f"{i}. [{src}]{date_tag} {title}\n   {body[:200]}")
    return "\n".join(lines)


def run_auto_import(include_research: bool = True) -> dict:
    """
    执行一次自动导入。返回运行摘要 dict。
    线程安全：并发调用时第二个直接返回 busy。
    """
    if not _lock.acquire(blocking=False):
        return {"ok": False, "message": "正在导入中，请稍候", **get_status()}

    try:
        _status.update(running=True, progress="正在采集中国财经内容...")

        # 1. 聚合（含用户配置的 RSS 源）
        rss_feeds = get_rss_feeds()
        all_items = cn_brain_fetcher.fetch_brain_items(
            include_research=include_research, rss_feeds=rss_feeds
        )

        # 2. 去重
        uids = [it["uid"] for it in all_items]
        unseen = brain_db.filter_unseen(uids)
        new_items = [it for it in all_items if it["uid"] in unseen]

        summary = {
            "ok": True,
            "at": datetime.now().isoformat(timespec="seconds"),
            "fetched": len(all_items),
            "new_items": len(new_items),
            "docs_created": 0,
            "rules_added": 0,
            "by_bucket": {},
            "message": "",
        }

        if not new_items:
            summary["message"] = "没有新内容，全部已导入过"
            _status.update(progress=summary["message"])
            brain_db.set_meta("autoimport_last_run", json.dumps(summary, ensure_ascii=False))
            return summary

        # 3. 按 bucket 分组
        buckets: dict[str, list[dict]] = {}
        for it in new_items:
            buckets.setdefault(it["bucket"], []).append(it)

        consumed: list[dict] = []
        today = datetime.now().strftime("%m-%d")

        # 4. 每个 bucket → 分块 → 文档 → 提炼
        for bucket, items in buckets.items():
            label = cn_brain_fetcher.BUCKET_LABEL.get(bucket, bucket)
            size = _CHUNK_SIZE.get(bucket, 12)
            max_docs = _MAX_DOCS_PER_BUCKET.get(bucket, 2)
            chunks = [items[i:i + size] for i in range(0, len(items), size)][:max_docs]

            b_docs = 0
            b_rules = 0
            b_items = 0
            for idx, chunk in enumerate(chunks, 1):
                _status.update(progress=f"提炼 {label} 第 {idx}/{len(chunks)} 篇...")
                doc = _build_doc(bucket, chunk)
                title = f"🤖 自动导入·{label}·{today} #{idx}"
                source_id = brain_db.save_source(doc, source_type=f"auto_{bucket}", title=title)
                try:
                    rules = brain_service.extract_rules(doc)
                except Exception:
                    rules = []
                ids = brain_db.save_rules(rules, source_id)
                brain_db.update_source_rule_count(source_id, len(ids))

                b_docs += 1
                b_rules += len(ids)
                b_items += len(chunk)
                consumed.extend(chunk)

            summary["by_bucket"][bucket] = {"label": label, "docs": b_docs, "rules": b_rules, "items": b_items}
            summary["docs_created"] += b_docs
            summary["rules_added"] += b_rules

        # 5. 标记已导入（含未成块丢弃的也标记，避免下次反复处理同样内容）
        brain_db.mark_imported(new_items)

        parts = [f"{v['label']}{v['rules']}条规则" for v in summary["by_bucket"].values()]
        summary["message"] = f"导入完成：{summary['docs_created']} 篇 / 共 {summary['rules_added']} 条规则" + (
            "（" + "、".join(parts) + "）" if parts else "")
        _status.update(progress=summary["message"])
        brain_db.set_meta("autoimport_last_run", json.dumps(summary, ensure_ascii=False))
        return summary

    except Exception as e:
        msg = f"自动导入失败：{e}"
        _status.update(progress=msg)
        fail = {"ok": False, "at": datetime.now().isoformat(timespec="seconds"), "message": msg}
        brain_db.set_meta("autoimport_last_run", json.dumps(fail, ensure_ascii=False))
        return fail
    finally:
        _status.update(running=False)
        _lock.release()
