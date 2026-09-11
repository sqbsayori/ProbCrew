#!/usr/bin/env bash
# ============================================================================
#  概率论伴学助手 · 多智能体原型演示包（Linux / macOS 启动脚本）
#
#  用法：
#      chmod +x start.sh && ./start.sh
#      或者： bash start.sh
# ============================================================================
set -euo pipefail

cd "$(dirname "$0")"

echo
echo "============================================================"
echo "  概率论伴学助手 · 多智能体原型演示包"
echo "============================================================"
echo

# ---- 1. 检查 Python ----
PY=""
for cand in python3 python; do
  if command -v "$cand" >/dev/null 2>&1; then PY="$cand"; break; fi
done

if [ -z "$PY" ]; then
  echo "[错误] 没有找到 Python。请先安装 Python 3.11+。"
  exit 1
fi
echo "[1/4] $($PY --version)  OK"

# ---- 2. 依赖 ----
if [ -f ".deps-installed" ]; then
  echo "[2/4] 依赖已安装，跳过"
else
  echo "[2/4] 首次运行，正在安装依赖（约 1-3 分钟）..."
  "$PY" -m pip install --disable-pip-version-check -q -r requirements.txt \
    || {
      echo
      echo "[错误] 依赖安装失败。可换国内镜像重试："
      echo "  $PY -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple"
      exit 1
    }
  touch .deps-installed
  echo "      依赖安装完成"
fi

# ---- 3. 注册表 ----
"$PY" scripts/gen_registry.py >/dev/null 2>&1 || true
echo "[3/4] 前端注册表已同步"

# ---- 4. 启动 ----
echo "[4/4] 正在启动服务..."
echo
echo "------------------------------------------------------------"
echo "  服务地址： http://127.0.0.1:8000"
echo
echo "  建议按顺序看这三处："
echo "    1) 原始动画 + 悬浮窗   http://127.0.0.1:8000/raw-live/"
echo "    2) 演示课程页 + 页宠   http://127.0.0.1:8000/course/"
echo "    3) 独立站点（9 页）    http://127.0.0.1:8000/"
echo
echo "  未配置 API Key 时自动用 Mock 模式，断网也能完整演示。"
echo "  关闭服务：按 Ctrl+C。"
echo "------------------------------------------------------------"
echo

cd backend
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
