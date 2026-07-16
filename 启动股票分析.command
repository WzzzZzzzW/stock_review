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

if curl -fsS --max-time 2 http://127.0.0.1:8002/health >/dev/null 2>&1; then
  echo "✅ 后台服务已在运行，正在打开页面"
  open http://127.0.0.1:8002
  exit 0
fi

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
nohup uvicorn main:app --host 127.0.0.1 --port 8002 \
  > /tmp/stock-review-backend.log 2>&1 < /dev/null &
BACKEND_PID=$!
disown "$BACKEND_PID"
cd ..

# 等待后端就绪后自动打开浏览器
echo "等待服务启动..."
for _ in {1..20}; do
  if curl -fsS --max-time 2 http://127.0.0.1:8002/health >/dev/null 2>&1; then
    open http://127.0.0.1:8002
    echo ""
    echo "✅ 已启动！后台将持续采集，关闭此窗口不影响运行"
    exit 0
  fi
  sleep 1
done

echo ""
echo "❌ 启动失败，请查看 /tmp/stock-review-backend.log"
exit 1
