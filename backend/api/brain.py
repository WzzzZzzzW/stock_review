"""
交易脑库 API
"""
import threading
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from db import brain_db
from services import brain_service
from services import brain_autoimport
from services.ocr_service import ocr_image_to_markdown

router = APIRouter(prefix="/api/brain", tags=["brain"])

# 后台提炼任务状态
_extract_lock = threading.Lock()
_extract_status: dict = {}   # source_id -> {status, rule_count, error}


# ── Models ────────────────────────────────────────────────────────────────────

class FeedIn(BaseModel):
    content: str
    source_type: str = "manual"   # manual / trade_review / article / book
    title: str = ""


class MatchIn(BaseModel):
    context: str   # 当前股票/市场情况描述


class ValidateIn(BaseModel):
    win: bool


class RevertValidateIn(BaseModel):
    win: bool                 # 要撤销的是「有效」(True) 还是「无效」(False)
    prev_confidence: float    # 点击前的置信度快照，用于精确还原


# ── 喂入内容 ──────────────────────────────────────────────────────────────────

@router.post("/feed")
def feed(body: FeedIn):
    """提交任意文本，后台异步提炼规则"""
    if len(body.content.strip()) < 20:
        raise HTTPException(400, "内容太短，至少20字")

    # 保存原文
    source_id = brain_db.save_source(body.content, body.source_type, body.title)

    # 后台异步提炼
    _extract_status[source_id] = {"status": "processing", "rule_count": 0, "error": ""}

    def _do_extract():
        try:
            rules = brain_service.extract_rules(body.content)
            ids = brain_db.save_rules(rules, source_id)
            brain_db.update_source_rule_count(source_id, len(ids))
            _extract_status[source_id] = {"status": "done", "rule_count": len(ids), "error": ""}
        except Exception as e:
            _extract_status[source_id] = {"status": "error", "rule_count": 0, "error": str(e)}

    threading.Thread(target=_do_extract, daemon=True).start()

    return {"source_id": source_id, "status": "processing"}


@router.get("/feed/status/{source_id}")
def feed_status(source_id: str):
    return _extract_status.get(source_id, {"status": "unknown", "rule_count": 0, "error": ""})


# ── 图片识别（OCR）入口 ─────────────────────────────────────────────────────

@router.post("/feed-image")
async def feed_image(
    file: UploadFile = File(...),
    title: str = Form(""),
    source_type: str = Form("article"),
    auto_extract: bool = Form(True),
):
    """
    上传图片（文章截图/聊天截图/书摘）→ OCR 识别 → 自动提炼规则入库。
    返回 {source_id, ocr_text}，前端可选展示OCR结果让用户编辑确认。

    auto_extract=True (默认): 直接走完整流程：OCR → 提炼 → 入库
    auto_extract=False: 只返回 OCR 文本，由前端再调 /feed 提交编辑后的内容
    """
    img_bytes = await file.read()

    try:
        ocr_text = ocr_image_to_markdown(img_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e))

    if len(ocr_text.strip()) < 20:
        raise HTTPException(400, f"OCR只识别到 {len(ocr_text)} 字符，内容太短")

    if not auto_extract:
        # 只返回 OCR 文本，不入库
        return {"ocr_text": ocr_text, "char_count": len(ocr_text)}

    # 直接走完整提炼流程
    source_id = brain_db.save_source(ocr_text, source_type, title or "图片识别")
    _extract_status[source_id] = {"status": "processing", "rule_count": 0, "error": ""}

    def _do_extract():
        try:
            rules = brain_service.extract_rules(ocr_text)
            ids = brain_db.save_rules(rules, source_id)
            brain_db.update_source_rule_count(source_id, len(ids))
            _extract_status[source_id] = {"status": "done", "rule_count": len(ids), "error": ""}
        except Exception as e:
            _extract_status[source_id] = {"status": "error", "rule_count": 0, "error": str(e)}

    threading.Thread(target=_do_extract, daemon=True).start()

    return {
        "source_id": source_id,
        "ocr_text": ocr_text,
        "char_count": len(ocr_text),
        "status": "processing",
    }


# ── 来源列表 ──────────────────────────────────────────────────────────────────

@router.get("/sources")
def get_sources():
    return {"sources": brain_db.list_sources()}


@router.get("/sources/{source_id}/rules")
def get_source_rules(source_id: str):
    """这条来源提炼出的具体规则（未删除），供前端展开查看。"""
    return {"rules": brain_db.list_rules_by_source(source_id)}


@router.delete("/sources/{source_id}")
def delete_source(source_id: str):
    brain_db.delete_source(source_id)
    return {"ok": True}


# ── 规则管理 ──────────────────────────────────────────────────────────────────

@router.get("/rules")
def get_rules(category: str = ""):
    rules = brain_db.list_rules(category)
    counts = brain_db.count_rules()
    return {"rules": rules, "counts": counts, "total": sum(counts.values())}


@router.delete("/rules/{rule_id}")
def delete_rule(rule_id: str):
    """软删除（可撤销）。误点后调用 /rules/{id}/restore 即可恢复。"""
    brain_db.delete_rule(rule_id)
    return {"ok": True}


@router.post("/rules/{rule_id}/restore")
def restore_rule(rule_id: str):
    """撤销删除：恢复被软删除的规则。"""
    brain_db.restore_rule(rule_id)
    return {"ok": True}


@router.post("/rules/{rule_id}/validate")
def validate_rule(rule_id: str, body: ValidateIn):
    """验证规则有效性（交易结果反馈）"""
    brain_db.validate_rule(rule_id, body.win)
    return {"ok": True}


@router.post("/rules/{rule_id}/revert-validate")
def revert_validate(rule_id: str, body: RevertValidateIn):
    """撤销一次「有效/无效」标记：计数器减回去 + 置信度还原成点击前的值。"""
    brain_db.revert_validate(rule_id, body.win, body.prev_confidence)
    return {"ok": True}


@router.post("/rules/{rule_id}/unvalidate")
def unvalidate_rule(rule_id: str, body: ValidateIn):
    """点卡片上的验证计数撤回一次「有效/无效」：计数器-1 + 置信度反向调整。"""
    brain_db.unvalidate_rule(rule_id, body.win)
    return {"ok": True}


# ── 匹配规则 ──────────────────────────────────────────────────────────────────

@router.post("/match")
def match_rules(body: MatchIn):
    """根据当前情况从脑库匹配相关规则"""
    all_rules = brain_db.list_rules()
    if not all_rules:
        return {"matches": []}

    matches = brain_service.match_rules(all_rules, body.context)

    # 增加匹配次数 + 补充规则详情
    enriched = []
    rule_map = {r["id"]: r for r in all_rules}
    for m in matches:
        rid = m.get("rule_id", "")
        if rid in rule_map:
            brain_db.increment_matched(rid)
            enriched.append({**rule_map[rid], "relevance": m.get("relevance", 0), "reason": m.get("reason", "")})

    return {"matches": enriched}


# ── Playbook ──────────────────────────────────────────────────────────────────

@router.get("/playbook")
def get_playbook():
    return {"playbook": brain_db.get_playbook()}


_playbook_lock = threading.Lock()
_playbook_status = {"status": "idle"}

@router.post("/playbook/regenerate")
def regenerate_playbook():
    """后台重新生成Playbook"""
    def _do():
        global _playbook_status
        _playbook_status = {"status": "processing"}
        try:
            rules = brain_db.list_rules()
            items = brain_service.generate_playbook(rules)
            brain_db.save_playbook(items)
            _playbook_status = {"status": "done", "count": len(items)}
        except Exception as e:
            _playbook_status = {"status": "error", "error": str(e)}

    threading.Thread(target=_do, daemon=True).start()
    return {"status": "processing"}


@router.get("/playbook/status")
def playbook_status():
    return _playbook_status


# ── 每日自动导入 ──────────────────────────────────────────────────────────────

@router.post("/auto-import/run")
def auto_import_run(include_research: bool = True):
    """手动触发一次自动导入（后台线程运行，立即返回当前状态）"""
    status = brain_autoimport.get_status()
    if status.get("running"):
        return {"ok": False, "message": "正在导入中，请稍候", "status": status}

    def _do():
        brain_autoimport.run_auto_import(include_research=include_research)

    threading.Thread(target=_do, daemon=True).start()
    return {"ok": True, "message": "已开始自动导入", "status": brain_autoimport.get_status()}


@router.get("/auto-import/status")
def auto_import_status():
    """查询自动导入运行状态 + 最近一次结果"""
    return brain_autoimport.get_status()


# ── RSS 源管理 ────────────────────────────────────────────────────────────────

class RssFeedIn(BaseModel):
    url: str
    name: str = ""


@router.get("/auto-import/feeds")
def list_feeds():
    """当前 RSS 源 + 内置默认源"""
    return {
        "feeds": brain_autoimport.get_rss_feeds(),
        "defaults": brain_autoimport.DEFAULT_RSS_FEEDS,
    }


@router.post("/auto-import/feeds")
def add_feed(body: RssFeedIn):
    """新增一个 RSS 源；添加前实测能否拉到内容"""
    url = body.url.strip()
    if not url.startswith("http"):
        raise HTTPException(400, "请输入合法的 http(s) 链接")

    # 实测校验
    from data.cn_brain_fetcher import _fetch_rss_items
    probe = _fetch_rss_items([{"url": url, "name": body.name or url}])
    if not probe:
        raise HTTPException(400, "这个源拉不到内容（可能是非 RSS、需要代理、或已失效）")

    feeds = brain_autoimport.add_rss_feed(url, body.name)
    return {"ok": True, "fetched": len(probe), "feeds": feeds}


@router.delete("/auto-import/feeds")
def delete_feed(url: str):
    """按 url 删除一个 RSS 源"""
    feeds = brain_autoimport.remove_rss_feed(url)
    return {"ok": True, "feeds": feeds}


# ── 统计 ──────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats():
    counts = brain_db.count_rules()
    sources = brain_db.list_sources()
    playbook = brain_db.get_playbook()
    return {
        "rule_counts": counts,
        "total_rules": sum(counts.values()),
        "total_sources": len(sources),
        "has_playbook": len(playbook) > 0,
        "playbook_categories": len(playbook),
    }
