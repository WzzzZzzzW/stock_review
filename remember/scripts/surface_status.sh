#!/usr/bin/env bash
# SessionStart 钩子：新对话开场，把项目「当前状态 + 下一步 + 阅读顺序」推进上下文，
# 让任何新对话框/agent 立刻知道干到哪了，无缝接上。
set -euo pipefail

BRAIN="${REMEMBER_BRAIN_PATH:-/Users/wangzhe45/Desktop/股票分析/remember}"
DOC="$BRAIN/Projects/股票分析.md"
[ -f "$DOC" ] || exit 0

echo "股票分析项目记忆库已挂载（$BRAIN）。新对话接手请按此顺序读："
echo "  Projects/股票分析.md → Notes/产品愿景与交易哲学 → Notes/用户偏好与铁律 → Notes/功能模块全景"
echo ""
echo "── 当前进度（摘自 Projects/股票分析.md）──"
# 抽取 ## Status 到下一个 ## 之间的内容
awk '/^## Status/{f=1} f&&/^## /&&!/^## Status/{exit} f{print}' "$DOC"
echo ""
echo "── 给接手 AI 的常驻指令（活保险）──"
echo "1. 用户常忘记说「更新记忆」。你要主动判断：每当一段工作有了决策/结论/进度/踩坑，"
echo "   就把「为什么这么做、结论是什么、干到哪了」蒸馏进 Projects/股票分析.md 的 ## Status + ## Log，"
echo "   不要等用户开口。"
echo "2. 上下文将压缩或会话结束时，钩子会自动把原始 digest 落盘到 Journal/当天.md（死保险，绝不丢）。"
echo "   你接手时若发现 Journal 有「自动快照」段落但 Projects 还没更新，应据此补做蒸馏。"
echo "3. 流水账（Journal）记「动了什么」，蒸馏（Projects）记「为什么、结论是什么」。两者都要。"
echo ""
echo "（完整项目记忆见上述文件；可用 search_brain 搜索）"
exit 0
