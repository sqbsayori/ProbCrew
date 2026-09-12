# ============================================================================
#  概率论伴学助手 · 原型镜像
# ----------------------------------------------------------------------------
#  构建（从 ProbCrew/ 根目录）：
#     docker build -f deployment/Dockerfile -t probstat-assistant:prototype .
#
#  运行：
#     docker run --rm -p 8000:8000 -e LLM_PROVIDER=mock probstat-assistant:prototype
# ============================================================================

FROM python:3.11-slim

# 中文字体不是必需的（分布图由前端 Canvas 自绘），但保留编码设置，
# 免得日志里的中文变成乱码。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# ---- 依赖单独一层，改代码时不必重装 ----
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---- 源码 ----
COPY . .

# 生成前端页面注册表（生成物虽然已提交，但这里再跑一次保证与目录一致）
RUN python scripts/gen_registry.py

# 目录准备：数据目录挂 volume，日志目录给权限
RUN mkdir -p backend/data

# 非 root 运行（原型阶段也建议，避免容器逃逸放大影响）
RUN useradd -m -u 10001 appuser && chown -R appuser:appuser /app
USER appuser

WORKDIR /app/backend
EXPOSE 8000

# 说明：
#   - 用单 worker。运行注册表（kernel/runs.py）是**进程内状态**，
#     多 worker 会导致 /api/hitl/{run_id}/resolve 找不到 run。
#     要上多 worker，必须先把运行状态外置到 Redis 或数据库。
#   - --proxy-headers 让后端能拿到 Nginx 传来的真实 IP 与 scheme。
CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
