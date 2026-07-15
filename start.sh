#!/bin/bash
set -e

echo "=== 股票复盘工具启动 ==="

# 检查 .env 文件
if [ ! -f backend/.env ]; then
  cp backend/.env.example backend/.env
  echo "[!] 请先在 backend/.env 填入 ANTHROPIC_API_KEY，然后重新运行"
  exit 1
fi

# 启动后端
echo "[1/2] 启动后端 (FastAPI)..."
cd backend
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  source .venv/bin/activate
  pip install -r requirements.txt -q
else
  source .venv/bin/activate
fi
uvicorn main:app --reload --port 8002 &
BACKEND_PID=$!
cd ..

# 启动前端
echo "[2/2] 启动前端 (Vite)..."
cd frontend
if [ ! -d "node_modules" ]; then
  npm install
fi
npm run dev &
FRONTEND_PID=$!
cd ..

echo ""
echo "后端: http://localhost:8002"
echo "前端: http://localhost:5173"
echo ""
echo "按 Ctrl+C 停止所有服务"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
wait
