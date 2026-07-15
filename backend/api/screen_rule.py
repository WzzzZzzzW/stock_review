"""
选股规则库 API
GET    /api/screen-rule/fields           — 可筛选字段 + 运算符（供前端条件搭建）
GET    /api/screen-rule/rules            — 规则列表（收藏置顶）
POST   /api/screen-rule/rules            — 新建规则
PUT    /api/screen-rule/rules/{id}       — 编辑规则
DELETE /api/screen-rule/rules/{id}       — 删除规则
POST   /api/screen-rule/rules/{id}/favorite — 收藏/取消收藏
GET    /api/screen-rule/rules/{id}/run   — 按规则实时筛选股票
POST   /api/screen-rule/preview          — 临时条件预览（不保存）
POST   /api/screen-rule/parse-nl         — 一句话 → 结构化条件（AI）
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from db import screen_rule_db as db
from services import screen_service

router = APIRouter(prefix="/api/screen-rule", tags=["规则库"])

db.init_db()


# ── Models ────────────────────────────────────────────────────────────────────

class RuleIn(BaseModel):
    name: str
    conditions: list[dict] = []
    logic: str = "AND"
    universe: dict = {}
    nl_source: str = ""
    sort_field: str = "change_pct"
    sort_dir: str = "desc"


class PreviewIn(BaseModel):
    conditions: list[dict] = []
    logic: str = "AND"
    universe: dict = {}
    sort_field: str = "change_pct"
    sort_dir: str = "desc"
    limit: int = 300


class NlIn(BaseModel):
    text: str


class ImageIn(BaseModel):
    image: str   # data:image/...;base64,xxxx


# ── 字段元数据 ────────────────────────────────────────────────────────────────

@router.get("/fields")
def get_fields():
    return {
        "fields": screen_service.FIELDS,
        "operators": screen_service.OPERATORS,
        "patterns": screen_service.PATTERNS,
    }


# ── 规则 CRUD ─────────────────────────────────────────────────────────────────

@router.get("/rules")
def list_rules(source: str | None = None):
    """source=user 仅我的规则；source=auto 仅推送规则；不传则全部。"""
    src = source if source in ("user", "auto") else None
    return {"rules": db.list_rules(src)}


@router.post("/rules")
def create_rule(body: RuleIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "规则名不能为空")
    rid = db.create_rule(name, body.conditions, body.logic, body.universe,
                         body.nl_source, body.sort_field, body.sort_dir)
    return {"ok": True, "id": rid, "rule": db.get_rule(rid)}


@router.put("/rules/{rid}")
def update_rule(rid: str, body: RuleIn):
    if not db.get_rule(rid):
        raise HTTPException(404, "规则不存在")
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "规则名不能为空")
    db.update_rule(rid, name=name, conditions=body.conditions, logic=body.logic,
                   universe=body.universe, nl_source=body.nl_source,
                   sort_field=body.sort_field, sort_dir=body.sort_dir)
    return {"ok": True, "rule": db.get_rule(rid)}


@router.delete("/rules/{rid}")
def delete_rule(rid: str):
    db.delete_rule(rid)
    return {"ok": True}


@router.post("/rules/{rid}/favorite")
def toggle_favorite(rid: str):
    if not db.get_rule(rid):
        raise HTTPException(404, "规则不存在")
    fav = db.toggle_favorite(rid)
    return {"ok": True, "favorite": fav}


# ── 运行筛选 ──────────────────────────────────────────────────────────────────

@router.get("/rules/{rid}/run")
def run_rule(rid: str, limit: int = 300):
    rule = db.get_rule(rid)
    if not rule:
        raise HTTPException(404, "规则不存在")
    res = screen_service.run_screen(
        rule["conditions"], rule["logic"], rule["universe"],
        rule["sort_field"], rule["sort_dir"], limit,
        kind=rule.get("kind", "numeric"), theme=rule.get("theme", ""),
    )
    return JSONResponse({"rule": rule, **res})


@router.get("/detail/{symbol}")
def stock_detail(symbol: str):
    """结果表下拉懒加载：单只股票的行业 / 主营业务 / 最近表现。"""
    return screen_service.stock_detail(symbol)


class DetailBatchIn(BaseModel):
    symbols: list[str] = []


@router.post("/detail-batch")
def stock_detail_batch(body: DetailBatchIn):
    """筛选完成后批量预取下拉详情，点开即显示（一次 baostock 会话 + 并行主营业务）。"""
    return {"details": screen_service.stock_detail_batch(body.symbols)}


@router.post("/preview")
def preview(body: PreviewIn):
    res = screen_service.run_screen(
        body.conditions, body.logic, body.universe,
        body.sort_field, body.sort_dir, body.limit,
    )
    return JSONResponse(res)


# ── 每日推送规则 ──────────────────────────────────────────────────────────────

@router.get("/auto/status")
def auto_status():
    from services import rule_autogen
    return rule_autogen.get_status()


@router.post("/auto/generate")
def auto_generate():
    """手动触发一次推送生成（后台线程，立即返回）。"""
    import threading
    from services import rule_autogen
    if rule_autogen.get_status().get("running"):
        return {"ok": False, "message": "正在生成中，请稍候"}
    threading.Thread(target=rule_autogen.run_autogen, daemon=True).start()
    return {"ok": True, "message": "已开始生成推送规则，约 1 分钟后刷新查看"}


# ── 回测 ──────────────────────────────────────────────────────────────────────

@router.post("/rules/{rid}/backtest/start")
def backtest_start(rid: str, window_days: int = 120, hold_days: int = 5,
                   top_k: int = 10, benchmark: str = "上证综指"):
    """启动一次回测（后台线程，立即返回，前端轮询 /backtest/status）。"""
    if not db.get_rule(rid):
        raise HTTPException(404, "规则不存在")
    from services import backtest_service
    return backtest_service.start_backtest(rid, window_days, hold_days, top_k, benchmark)


@router.get("/rules/{rid}/backtest/status")
def backtest_status(rid: str):
    """查询回测进度/结果。state=idle|running|done|error。"""
    from services import backtest_service
    return backtest_service.get_status(rid)


@router.post("/rules/{rid}/save-as-mine")
def save_as_mine(rid: str):
    """把一条推送规则保存为「我的规则」，使其不被每日刷新清掉。"""
    rule = db.get_rule(rid)
    if not rule:
        raise HTTPException(404, "规则不存在")
    saved = db.convert_to_user(rid)
    return {"ok": True, "rule": saved}


# ── AI 解析 ───────────────────────────────────────────────────────────────────

@router.post("/parse-nl")
def parse_nl(body: NlIn):
    text = (body.text or "").strip()
    if len(text) < 2:
        raise HTTPException(400, "描述太短")
    try:
        parsed = screen_service.parse_nl(text)
        return {"ok": True, **parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/parse-image")
def parse_image(body: ImageIn):
    img = (body.image or "").strip()
    if not img.startswith("data:image/") or ";base64," not in img:
        raise HTTPException(400, "图片格式不正确")
    # 限制约 6MB（base64 后体积，避免超大图拖慢/超时）
    if len(img) > 8_000_000:
        raise HTTPException(400, "图片太大，请压缩或截取关键区域")
    try:
        parsed = screen_service.parse_image(img)
        return {"ok": True, **parsed}
    except Exception as e:
        return {"ok": False, "error": str(e)}
