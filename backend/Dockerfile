# 构建上下文为仓库根目录：
#   docker build -f backend/Dockerfile -t eorzea-backend .
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# curl 供容器健康检查使用
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 共享配置层：后端通过 shared/schema/loader.py 读取配置
COPY shared ./shared

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/alembic.ini ./backend/alembic.ini
COPY backend/alembic ./backend/alembic
COPY backend/app ./backend/app
COPY backend/docker-entrypoint.sh ./backend/docker-entrypoint.sh

RUN chmod +x ./backend/docker-entrypoint.sh \
    && pip install -e ./backend

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${BACKEND_PORT:-8000}/health" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
