#!/usr/bin/env bash
# PreCompact / SessionEnd 钩子：上下文压缩或会话结束前，自动把本次对话的 digest
# （用户原话 + 助手关键回复 + 原始记录路径）落盘到 Journal/当天.md，确保绝不丢数据。
# stdin = Claude Code 传入 JSON（含 transcript_path / session_id / trigger）。
set -euo pipefail

BRAIN="${REMEMBER_BRAIN_PATH:-/Users/wangzhe45/Desktop/股票分析/remember}"
JDIR="$BRAIN/Journal"
mkdir -p "$JDIR"

payload="$(cat || true)"
[ -z "$payload" ] && exit 0

tpath="$(printf '%s' "$payload" | jq -r '.transcript_path // empty' 2>/dev/null || true)"
trigger="$(printf '%s' "$payload" | jq -r '.trigger // .hook_event_name // "snapshot"' 2>/dev/null || echo snapshot)"
[ -z "$tpath" ] && exit 0
[ -f "$tpath" ] || exit 0

day="$(date +%F)"; ts="$(date +%H:%M)"
jfile="$JDIR/$day.md"
[ -f "$jfile" ] || printf '# %s 操作流水\n\n' "$day" > "$jfile"

python3 - "$tpath" "$jfile" "$ts" "$trigger" <<'PY'
import json, sys
tpath, jfile, ts, trigger = sys.argv[1:5]
users=[]; assists=[]
with open(tpath, encoding="utf-8", errors="ignore") as fh:
    for line in fh:
        try: o=json.loads(line)
        except: continue
        t=o.get("type"); m=o.get("message",{}) or {}
        ct=m.get("content")
        if isinstance(ct,list):
            ct=" ".join(x.get("text","") for x in ct if isinstance(x,dict) and x.get("type")=="text")
        if not isinstance(ct,str): continue
        ct=ct.strip().replace("\n"," ")
        if not ct or ct.startswith("<") or "tool_use_id" in ct: continue
        if t=="user": users.append(ct[:200])
        elif t=="assistant" and len(ct)>40: assists.append(ct[:160])
# 去重保序
def dedup(xs):
    seen=set(); out=[]
    for x in xs:
        k=x[:60]
        if k in seen: continue
        seen.add(k); out.append(x)
    return out
users=dedup(users)[-12:]; assists=dedup(assists)[-6:]
with open(jfile,"a",encoding="utf-8") as w:
    w.write(f"\n## [{ts}] 上下文{('压缩' if 'compact' in trigger.lower() else '结束')}前快照（自动·{trigger}）\n")
    w.write(f"> 原始完整记录：`{tpath}`\n\n")
    w.write("**本段我的诉求/原话：**\n")
    for u in users: w.write(f"- {u}\n")
    if assists:
        w.write("\n**助手关键结论：**\n")
        for a in assists: w.write(f"- {a}\n")
    w.write("\n> ⚠️ 这是机械 digest。下个对话接手时，AI 应据此+原始记录把"
            "**决策/结论/进度**蒸馏进 Projects/股票分析.md 与本 Journal。\n")
print("snapshot appended")
PY
exit 0
