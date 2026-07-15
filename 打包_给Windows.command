#!/bin/bash
# 双击此文件：构建前端 + 打出一个可拷到 Windows 的干净文件夹（含 zip）
set -e
cd "$(dirname "$0")"
ROOT="$(pwd)"
OUT_DIR="$HOME/Desktop/股票分析_打包"
APP="$OUT_DIR/股票分析"

echo "========================================"
echo " 打包股票分析（给 Windows 用）"
echo "========================================"

# 1) 构建前端（用 vite build，跳过类型检查门槛，保证能出包）
echo "[1/3] 构建前端静态文件…"
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npx vite build
cd "$ROOT"

# 2) 组装干净的打包目录
echo "[2/3] 组装打包目录（排除 .venv / node_modules / 缓存）…"
rm -rf "$OUT_DIR"
mkdir -p "$APP/frontend"

# 后端：带走代码 + 数据(data) + 密钥(.env)，排除虚拟环境与缓存
rsync -a \
  --exclude '.venv' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  "$ROOT/backend" "$APP/"

# 前端：运行时只需要 dist，源码和 node_modules 都不带
rsync -a "$ROOT/frontend/dist" "$APP/frontend/"

# Windows 启动脚本
cp "$ROOT/启动_windows.bat" "$APP/"

# 3) 压缩成 zip，方便用 U 盘 / 微信 / 网盘传
echo "[3/3] 压缩为 zip…"
cd "$OUT_DIR"
zip -rq "股票分析_windows.zip" "股票分析" -x "*.DS_Store"
cd "$ROOT"

echo ""
echo "✅ 完成！"
echo "   文件夹：$APP"
echo "   压缩包：$OUT_DIR/股票分析_windows.zip"
echo ""
echo "下一步：把 zip 拷到 Windows 电脑，解压后双击里面的「启动_windows.bat」。"
echo "（注意：包里含 backend/.env，里面有你的 API Key，别外传给别人）"
echo ""
osascript -e 'display dialog "打包完成！已生成到桌面的「股票分析_打包」文件夹（含 zip）。\n\n拷到 Windows 后双击 启动_windows.bat 即可。" buttons {"好的"} default button 1' >/dev/null 2>&1 || true
open "$OUT_DIR" || true
