"""
统一 AI 客户端工厂 —— 带「模型故障转移」(failover chain)

本模块维护一条聊天模型链：当前模型报「余额/限额不足/欠费/过期」类错误时，
自动切到链上的下一个模型，**业务代码零改动**（全后端都通过
make_client().chat.completions.create(...) 调用，这里拦截做转移）。

设计要点：
- 只有「额度/余额」类错误才换模型；429 限流、5xx、400 参数错等直接抛出，不浪费整条链。
- 当前生效模型的下标持久化到 data/ai_model_state.json，重启不丢；**每天重置回链首**
  重新探一遍（赠送额度可能按周期刷新，或用户已充值/换了 key）。
- 视觉模型（GLM-4V）走单独的 make_vision_client()，免费、不受影响，不参与转移。

切换/调整：直接改 MODEL_CHAIN 的顺序或成员即可（成员必须是当前 key 有权限的模型，
否则会 4xx 而非额度错，导致整链中断）。
"""
import json
import threading
from datetime import date
from pathlib import Path

from openai import OpenAI
from config import settings

# ── 故障转移模型链（从前到后依次降级）────────────────────────────────────────
MODEL_CHAIN = [
    "deepseek-v4-pro",   # DS V4 Pro，当前默认聊天/分析模型
]

# 兼容旧引用：很多文件 `from ai_client import CHAT_MODEL` 再传 model=CHAT_MODEL，
# 实际生效模型由 FailoverClient 动态决定（会忽略调用方传入的 model）。
CHAT_MODEL = MODEL_CHAIN[0]

# 视觉模型：智谱 GLM-4V-Flash（免费、支持图片，用于截图识别），不参与转移。
VISION_MODEL = "glm-4v-flash"

_CHAT_BASE_URL = "https://api.deepseek.com/v1"
_STATE_PATH = Path(__file__).parent.parent / "data" / "ai_model_state.json"

# 触发「换下一个模型」的错误特征（额度/余额/欠费/过期）。其余错误一律抛出。
_QUOTA_HINTS = (
    "insufficient", "balance", "arrear", "quota", "exhaust",
    "expired", "limit exceeded", "余额", "额度", "欠费", "已用完",
)

_state_lock = threading.Lock()
_cur = {"idx": None, "date": None}        # 进程内缓存
_raw_client: OpenAI | None = None


def _raw() -> OpenAI:
    """底层聊天模型客户端（单例）。"""
    global _raw_client
    if _raw_client is None:
        _raw_client = OpenAI(api_key=settings.deepseek_api_key, base_url=_CHAT_BASE_URL)
    return _raw_client


def _is_quota_error(e: Exception) -> bool:
    if getattr(e, "status_code", None) == 402:
        return True
    msg = str(e).lower()
    return any(h in msg for h in _QUOTA_HINTS)


def _current_start() -> int:
    """当前应从链上第几个模型开始（跨天重置回 0 重新探）。"""
    today = date.today().isoformat()
    with _state_lock:
        if _cur["idx"] is None or _cur["date"] != today:
            idx = 0
            try:
                s = json.loads(_STATE_PATH.read_text(encoding="utf-8"))
                if s.get("date") == today:
                    idx = int(s.get("idx", 0))
            except Exception:
                pass
            if not (0 <= idx < len(MODEL_CHAIN)):
                idx = 0
            _cur["idx"], _cur["date"] = idx, today
        return _cur["idx"]


def _commit(idx: int):
    """记住「现在可用的是第 idx 个模型」，后续调用直接从它开始。"""
    today = date.today().isoformat()
    with _state_lock:
        _cur["idx"], _cur["date"] = idx, today
    try:
        _STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _STATE_PATH.write_text(
            json.dumps({"idx": idx, "date": today, "model": MODEL_CHAIN[idx]},
                       ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def current_model() -> str:
    """当前生效模型（供 /health、调试用）。"""
    return MODEL_CHAIN[_current_start()]


# ── 带故障转移的客户端（鸭子类型，仅实现本项目用到的 chat.completions.create）──
class _Completions:
    def create(self, **kwargs):
        kwargs.pop("model", None)              # 模型由链路决定，忽略调用方传入
        start = _current_start()
        last_err: Exception | None = None
        for i in range(start, len(MODEL_CHAIN)):
            model = MODEL_CHAIN[i]
            try:
                resp = _raw().chat.completions.create(model=model, **kwargs)
                if i != start:
                    _commit(i)                 # 切换成功，固化到新模型
                return resp
            except Exception as e:             # noqa: BLE001
                if _is_quota_error(e):
                    last_err = e
                    continue                   # 该模型额度没了，试下一个
                raise                          # 非额度错（限流/参数/网络）→ 照常抛出
        raise last_err or RuntimeError("所有 AI 模型额度均不可用，请检查百炼额度或更换 key")


class _Chat:
    def __init__(self):
        self.completions = _Completions()


class FailoverClient:
    def __init__(self):
        self.chat = _Chat()


def make_client() -> FailoverClient:
    return FailoverClient()


def make_vision_client() -> OpenAI:
    """智谱视觉模型客户端（图片 → 文本理解）。免费，不参与故障转移。"""
    return OpenAI(
        api_key=settings.glm_api_key,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )
