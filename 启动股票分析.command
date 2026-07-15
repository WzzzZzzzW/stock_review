#!/bin/bash
# 双击此文件即可启动股票分析工具

# 切换到项目目录（.command 文件运行时工作目录是 $HOME，需要手动 cd）
cd "$(dirname "$0")"

# 检查 .env 文件
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env 2>/dev/null || true
  osascript -e 'display dialog "请先在 backend/.env 填入 API Key，然后重新双击启动" buttons {"好的"} default button 1'
  open backend/.env
  exit 1
fi

echo "=== 股票分析工具启动中 ==="

# 启动后端
cd backend
if [ ! -d ".venv" ]; then
  echo "首次运行，安装依赖（约1~2分钟）..."
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt -q
else
  source .venv/bin/activate
fi
uvicorn main:app --port 8000 &
BACKEND_PID=$!
cd ..

# 启动前端
cd frontend
if [ ! -d "node_modules" ]; then
  echo "首次运行，安装前端依赖..."
  npm install -q
fi
npm run dev &
FRONTEND_PID=$!
cd ..

# 等待后端就绪后自动打开浏览器
echo "等待服务启动..."
sleep 3
open http://localhost:5173

echo ""
echo "✅ 已启动！浏览器打开 http://localhost:5173"
echo "关闭此窗口即停止所有服务"
echo ""

trap "echo '正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" EXIT INT TERM
wait
