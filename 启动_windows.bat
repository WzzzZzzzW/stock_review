@echo off
chcp 65001 >nul
title 股票分析

rem ── 切到脚本所在目录下的 backend ──
cd /d "%~dp0backend"

rem ── 检查 Python ──
where python >nul 2>nul
if errorlevel 1 (
  echo [X] 没找到 Python。请先到 https://www.python.org/downloads/ 安装 Python 3.12，
  echo     安装时务必勾选 "Add python.exe to PATH"，装完重启此脚本。
  pause
  exit /b 1
)

rem ── 检查密钥文件 ──
if not exist ".env" (
  echo [!] 缺少 backend\.env，请把原电脑的 backend\.env 拷过来（里面是 API Key），再重新双击启动。
  pause
  exit /b 1
)

rem ── 首次运行：建虚拟环境 + 装依赖 ──
if not exist ".venv" (
  echo ============================================
  echo  首次运行：正在创建虚拟环境并安装依赖
  echo  这一步要联网下载，约 3~8 分钟，请耐心等待…
  echo ============================================
  python -m venv .venv
  call ".venv\Scripts\activate.bat"
  python -m pip install --upgrade pip
  pip install -r requirements.txt
  if errorlevel 1 (
    echo [X] 依赖安装失败，请把上面的红色报错截图发给我。
    pause
    exit /b 1
  )
) else (
  call ".venv\Scripts\activate.bat"
)

rem ── 启动：5 秒后自动打开浏览器，uvicorn 在本窗口前台运行 ──
echo.
echo  ✅ 启动中… 稍等浏览器会自动打开 http://localhost:8002
echo  （关闭本窗口即停止程序）
echo.
start "" /min cmd /c "timeout /t 5 >nul & explorer http://localhost:8002"
python -m uvicorn main:app --host 127.0.0.1 --port 8002

pause
