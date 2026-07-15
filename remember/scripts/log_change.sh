#!/usr/bin/env bash
# PostToolUse 钩子：把每次文件改动记成一行流水账，追加到 Journal/当天.md
# stdin 是 Claude Code 传入的 JSON（含 tool_name / tool_input.file_path）
set -euo pipefail

BRAIN="${REMEMBER_BRAIN_PATH:-/Users/wangzhe45/Desktop/股票分析/remember}"
JDIR="$BRAIN/Journal"
mkdir -p "$JDIR"

payload="$(cat || true)"
[ -z "$payload" ] && exit 0

tool="$(printf '%s' "$payload" | jq -r '.tool_name // empty' 2>/dev/null || true)"
fp="$(printf '%s' "$payload" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)"
[ -z "$tool" ] && exit 0
[ -z "$fp" ] && exit 0

# 只记项目相关改动，过滤掉记忆库自身的写入（避免自我刷屏）
case "$fp" in
  "$BRAIN"/*) exit 0 ;;
esac

day="$(date +%F)"
ts="$(date +%H:%M)"
jfile="$JDIR/$day.md"

# 相对项目根的短路径
rel="${fp#/Users/wangzhe45/Desktop/股票分析/}"

if [ ! -f "$jfile" ]; then
  printf '# %s 操作流水\n\n> 自动记录（PostToolUse）。每行 = 一次文件改动。\n> 思路/决策/进度请用 `remember:remember` 或说「更新记忆」由 AI 蒸馏补充。\n\n' "$day" > "$jfile"
fi

printf -- '- %s  `%s`  %s\n' "$ts" "$tool" "$rel" >> "$jfile"
exit 0
