# 构建上下文为仓库根目录：
#   docker build -f backend/Dockerfile -t eorzea-backend .
#
# 基础镜像与软件源均可通过 --build-arg 覆盖（docker-compose.yml 已给出国内默认值）：
#   PYTHON_IMAGE   基础镜像（可指向国内镜像站，如 docker.m.daocloud.io/library/python:3.12-slim）
#   APT_MIRROR     Debian 软件源域名（默认清华，置空则用官方源）
#   PIP_INDEX_URL  pip 索引地址（默认清华，置空则用官方 PyPI）
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

ARG APT_MIRROR=mirrors.tuna.tsinghua.edu.cn
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# 先把 Debian 软件源换成国内镜像，再安装 curl（供容器健康检查使用）
RUN set -eux; \
    if [ -n "${APT_MIRROR}" ]; then \
        for f in /etc/apt/sources.list /etc/apt/sources.list.d/*.sources /etc/apt/sources.list.d/*.list; do \
            [ -f "$f" ] || continue; \
            sed -i "s|deb.debian.org|${APT_MIRROR}|g; s|security.debian.org|${APT_MIRROR}|g" "$f"; \
        done; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 共享配置层：后端通过 shared/schema/loader.py 读取配置
COPY shared ./shared

COPY backend/pyproject.toml ./backend/pyproject.toml
COPY backend/alembic.ini ./backend/alembic.ini
COPY backend/alembic ./backend/alembic
COPY backend/app ./backend/app
COPY backend/docker-entrypoint.sh ./backend/docker-entrypoint.sh

RUN chmod +x ./backend/docker-entrypoint.sh \
    && if [ -n "${PIP_INDEX_URL}" ]; then \
         pip install --index-url "${PIP_INDEX_URL}" -e ./backend; \
       else \
         pip install -e ./backend; \
       fi

WORKDIR /app/backend

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
    CMD curl -fsS "http://127.0.0.1:${BACKEND_PORT:-8000}/health" || exit 1

ENTRYPOINT ["./docker-entrypoint.sh"]
