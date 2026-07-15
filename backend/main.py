import threading
from datetime import datetime, date, timedelta
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.review import router as review_router
from api.news_impact import router as news_impact_router
from api.news_feed import router as news_feed_router
from api.news_feed_cn import router as news_feed_cn_router
from api.news_trending import router as news_trending_router
from api.stocks import router as stocks_router
from api.market import router as market_router
from api.industry import router as industry_router
from api.sector import router as sector_router
from api.lhb import router as lhb_router
from api.watchlist import router as watchlist_router
from api.daily_report  import router as daily_report_router
from api.prediction    import router as prediction_router
from api.portfolio import router as portfolio_router
from api.limitup_review import router as limitup_router, _do_generate
from api.market_review import router as market_review_router
from api.today_review import router as today_review_router, _do_generate as _do_generate_today_review
from api.trading_day import router as trading_day_router
from api.brain import router as brain_router
from api.office import router as office_router
from api.recommend import router as recommend_router
from api.screen_rule import router as screen_rule_router
from api.zhengxi import router as zhengxi_router

app = FastAPI(title="股票复盘工具", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(review_router)
app.include_router(news_impact_router)
app.include_router(news_feed_router)
app.include_router(news_feed_cn_router)
app.include_router(news_trending_router)
app.include_router(stocks_router)
app.include_router(market_router)
app.include_router(industry_router)
app.include_router(sector_router)
app.include_router(lhb_router)
app.include_router(watchlist_router)
app.include_router(daily_report_router)
app.include_router(prediction_router)
app.include_router(portfolio_router)
app.include_router(limitup_router)
app.include_router(market_review_router)
app.include_router(today_review_router)
app.include_router(trading_day_router)
app.include_router(brain_router)
app.include_router(office_router)
app.include_router(recommend_router)
app.include_router(screen_rule_router)
app.include_router(zhengxi_router)

# APScheduler: auto-generate limit-up review at 15:45 on weekdays
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        lambda: _do_generate(datetime.today().strftime("%Y-%m-%d")),
        CronTrigger(day_of_week="mon-fri", hour=15, minute=45, timezone="Asia/Shanghai"),
    )
    # 今日复盘总览：收盘后 16:05 自动生成，整合市场/持仓/自选/行业/国际形势。
    scheduler.add_job(
        lambda: _do_generate_today_review(datetime.today().strftime("%Y-%m-%d"), None),
        CronTrigger(day_of_week="mon-fri", hour=16, minute=5, timezone="Asia/Shanghai"),
    )

    # 不自动应用——用户登录后会在持仓页看到"发现 N 项待调整"，
    # 点击确认后才会调整。（避免买入日不准导致误调整）

    # 脑库每日自动导入：每天 18:30（收盘 + 研报更新后）抓取中国财经内容→提炼入库
    try:
        from services import brain_autoimport
        scheduler.add_job(
            lambda: brain_autoimport.run_auto_import(),
            CronTrigger(hour=18, minute=30, timezone="Asia/Shanghai"),
        )
    except Exception as e:
        print(f"[brain] 自动导入定时任务注册失败: {e}")

    # 规则库每日推送：每天 18:40（错开脑库 18:30）读新闻+行业→AI 生成推送规则
    try:
        from services import rule_autogen
        scheduler.add_job(
            lambda: rule_autogen.run_autogen(),
            CronTrigger(hour=18, minute=40, timezone="Asia/Shanghai"),
        )
    except Exception as e:
        print(f"[rule-autogen] 推送定时任务注册失败: {e}")

    # 今日推荐：盘中每 4 分钟自动重建一次，保证用户点开页面缓存始终新鲜
    # （与 _TODAY_TTL=300s 错开，4 分钟 < 5 分钟 TTL，覆盖到位）
    try:
        from api.recommend import warm_today_cache, warm_tomorrow_cache
        scheduler.add_job(
            lambda: warm_today_cache(force=True),
            CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/4",
                        timezone="Asia/Shanghai"),
        )
        # 明日预判：每天 15:35（收盘后 5min）+ 19:00（晚间研报更新后）各刷一次
        scheduler.add_job(
            lambda: warm_tomorrow_cache(force=True),
            CronTrigger(day_of_week="mon-fri", hour=15, minute=35, timezone="Asia/Shanghai"),
        )
        scheduler.add_job(
            lambda: warm_tomorrow_cache(force=True),
            CronTrigger(hour=19, minute=0, timezone="Asia/Shanghai"),
        )
    except Exception as e:
        print(f"[recommend] 盘中刷新定时任务注册失败: {e}")

    scheduler.start()
except ImportError:
    pass  # apscheduler not installed, auto-schedule disabled


# ── 启动时自动补齐最近 5 个交易日的涨停板复盘 ─────────────────────────────────

def _recent_trading_days(n: int = 5) -> list[str]:
    """
    返回最近 n 个交易日 (YYYY-MM-DD)，倒序。
    跳过周末。今天若未到 15:00 收盘则不算。
    """
    days: list[str] = []
    today = date.today()
    now_hour = datetime.now().hour
    d = today
    while len(days) < n:
        if d.weekday() < 5:   # mon-fri
            # 今天且尚未收盘 → 跳过（数据还不全）
            if d == today and now_hour < 15:
                pass
            else:
                days.append(d.isoformat())
        d -= timedelta(days=1)
    return days


def _backfill_limitup_on_startup():
    """启动时检测最近交易日是否缺数据，缺的话后台串行补齐"""
    try:
        from db.limitup_db import list_dates
        existing = {x["date"] for x in list_dates()}
        # 覆盖最近 15 个交易日（约 3 周），保证日历范围内的数据都齐
        targets = _recent_trading_days(15)
        missing = [d for d in targets if d not in existing]
        if not missing:
            print("[backfill] 最近 5 个交易日数据齐全，无需补齐")
            return
        # 按时间顺序补（旧的先补，新的最后）
        missing.sort()
        print(f"[backfill] 检测到 {len(missing)} 个交易日待补齐: {missing}")
        for d in missing:
            print(f"[backfill] 开始生成 {d}...")
            try:
                _do_generate(d)
                print(f"[backfill] ✅ {d} 完成")
            except Exception as e:
                print(f"[backfill] ❌ {d} 失败: {e}")
    except Exception as e:
        print(f"[backfill] 整体失败: {e}")


def _brain_autoimport_catchup_on_startup():
    """
    启动时若「今天还没成功自动导入过」，就后台补跑一次。
    场景：18:30 定时跑时电脑/程序没开 → 错过 → 用户一开软件就自动补齐当天没消化的财经内容。
    去重表(brain_imported)保证补跑只会吃进尚未导入的新内容，不会重复。
    """
    try:
        import json as _json
        from services import brain_autoimport
        from db import brain_db

        raw = brain_db.get_meta("autoimport_last_run", "")
        last = None
        try:
            last = _json.loads(raw) if raw else None
        except Exception:
            last = None

        today = date.today().isoformat()
        last_date = (last.get("at", "")[:10] if last else "")
        if last and last.get("ok") and last_date == today:
            print(f"[brain] 今日({today})已自动导入，跳过启动补跑")
            return

        print(f"[brain] 今日({today})尚未自动导入（上次={last_date or '无'}），启动补跑中…")
        summary = brain_autoimport.run_auto_import()
        print(f"[brain] 启动补跑完成：{summary.get('message', '')}")
    except Exception as e:
        print(f"[brain] 启动补跑失败: {e}")


def _rule_autogen_catchup_on_startup():
    """
    启动时若「今天还没生成过推送规则」，就后台补跑一次。
    场景：18:40 定时跑时电脑/程序没开 → 错过 → 用户一开软件就自动补上今日推送。
    整批替换语义保证补跑只会刷新成今天的，不会重复堆积。
    """
    try:
        from services import rule_autogen
        if rule_autogen.generated_today():
            print("[rule-autogen] 今日已生成推送规则，跳过启动补跑")
            return
        print("[rule-autogen] 今日尚未生成推送规则，启动补跑中…")
        summary = rule_autogen.run_autogen()
        print(f"[rule-autogen] 启动补跑完成：{summary.get('message', '')}")
    except Exception as e:
        print(f"[rule-autogen] 启动补跑失败: {e}")


def _today_review_catchup_on_startup():
    """
    交易日 15:10 后启动时补齐当日日档案。
    自选股由服务端持久化，后台任务与前端看到的是同一份自选池。
    """
    try:
        from db.today_review_db import list_dates as tr_list_dates
        from services.market_clock import get_market_status
        existing = {x["date"] for x in tr_list_dates()}
        market_status = get_market_status()
        if not market_status["can_generate_postmarket"]:
            print("[today-review] 当前未到交易日15:10，跳过启动补齐")
            return
        target = market_status["today"]
        if target in existing:
            print(f"[today-review] {target} 已有数据，无需补齐")
            return
        print(f"[today-review] 启动补齐 {target} 今日复盘...")
        _do_generate_today_review(target, None)
        print(f"[today-review] ✅ {target} 完成")
    except Exception as e:
        print(f"[today-review] 启动补齐失败: {e}")


@app.on_event("startup")
def _on_startup():
    # 启动后台串行补齐，避免阻塞 uvicorn 启动
    def delayed():
        import time
        time.sleep(5)
        _backfill_limitup_on_startup()
        _today_review_catchup_on_startup()
        # 涨停补齐后再补脑库自动导入（错峰，避免同时占满 AI/网络）
        _brain_autoimport_catchup_on_startup()
        # 最后补今日规则推送（错峰，避免同时占满 AI/网络）
        _rule_autogen_catchup_on_startup()
        # 今日推荐缓存预热：用户打开"今日"页时缓存已就绪，不再等 10-15s
        try:
            from api.recommend import warm_today_cache, warm_tomorrow_cache
            from services.market_clock import get_market_status
            phase = get_market_status()["phase"]
            if phase == "intraday":
                print("[recommend] 启动预热盘中机会...")
                warm_today_cache(force=True)
                print("[recommend] 盘中机会缓存就绪")
            else:
                print("[recommend] 启动预热下一交易日计划...")
                warm_tomorrow_cache(force=True)
                print("[recommend] 下一交易日计划缓存就绪")
        except Exception as e:
            print(f"[recommend] 启动预热失败: {e}")
        # 行业映射使用同一个 baostock 单例，放到技术指标和推荐预热之后，
        # 避免全市场映射超时把个股多维指标一起拖入熔断。
        try:
            from data.stock_data import get_industry_map
            get_industry_map(block=True)
        except Exception:
            pass
    threading.Thread(target=delayed, daemon=True).start()


@app.get("/health")
def health():
    out: dict = {"status": "ok"}
    try:
        from services.ai_client import current_model, web_search_status
        out["ai"] = {
            "provider": "volcengine_ark",
            "model": current_model(),
            "web_search": web_search_status(),
        }
    except Exception:
        pass
    try:
        from data.stock_data import get_baostock_health
        out["baostock"] = get_baostock_health()
    except Exception:
        pass
    return out


# ── 托管前端静态文件 ─────────────────────────────────────────────────────────────
# 单服务打包：后端一个进程同时提供 API 和页面，目标机器无需 Node / Vite。
# 必须放在所有 include_router 与 /health 之后——API 路由先匹配，其余路径交给前端。
from pathlib import Path
from fastapi.staticfiles import StaticFiles

_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _DIST.exists():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="frontend")
    print(f"[static] 已托管前端页面：{_DIST}")
else:
    print(f"[static] 未找到前端构建产物 {_DIST}，仅提供 API（开发模式请另开 vite dev）")
