@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo ============================================================
echo   概率论伴学助手 · 多智能体原型演示包
echo ============================================================
echo.

REM ---- 1. 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 没有找到 Python。
  echo        请先安装 Python 3.11 或更高版本：https://www.python.org/downloads/
  echo        安装时务必勾选 "Add Python to PATH"。
  echo.
  pause
  exit /b 1
)

for /f "tokens=2" %%v in ('python --version 2^>^&1') do set PYVER=%%v
echo [1/4] Python %PYVER%  OK

REM ---- 2. 安装依赖（只在首次运行时做，之后靠标记文件跳过）----
if exist ".deps-installed" (
  echo [2/4] 依赖已安装，跳过
) else (
  echo [2/4] 首次运行，正在安装依赖（约 1-3 分钟，请耐心等待）...
  python -m pip install --disable-pip-version-check -q -r requirements.txt
  if errorlevel 1 (
    echo.
    echo [错误] 依赖安装失败。常见原因：
    echo        - 网络问题：可换国内镜像重试
    echo          python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    echo        - pip 版本过旧：python -m pip install --upgrade pip
    echo.
    pause
    exit /b 1
  )
  echo ok> .deps-installed
  echo       依赖安装完成
)

REM ---- 3. 同步前端页面注册表 ----
python scripts\gen_registry.py >nul 2>&1
echo [3/4] 前端注册表已同步

REM ---- 4. 启动服务并打开浏览器 ----
echo [4/4] 正在启动服务...
echo.
echo ------------------------------------------------------------
echo   服务地址： http://127.0.0.1:8000
echo.
echo   建议按顺序看这三处：
echo     1) 原始动画 + 悬浮窗   http://127.0.0.1:8000/raw-live/
echo     2) 演示课程页 + 页宠   http://127.0.0.1:8000/course/
echo     3) 独立站点（9 页）    http://127.0.0.1:8000/
echo.
echo   未配置 API Key 时自动用 Mock 模式，断网也能完整演示。
echo   想接真实模型：把 .env.example 复制成 .env，填入 DEEPSEEK_API_KEY
echo.
echo   关闭服务：在本窗口按 Ctrl+C，或直接关掉窗口。
echo ------------------------------------------------------------
echo.

REM 等 3 秒后打开浏览器（此时服务基本已就绪）
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8000/course/"

cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

echo.
echo 服务已停止。
pause
