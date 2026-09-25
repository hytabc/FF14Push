#!/bin/sh
# 后端容器入口：等待数据库 → 执行迁移 → 启动 API
set -e

PORT="${BACKEND_PORT:-8000}"
MAX_ATTEMPTS=30

echo "[entrypoint] 等待数据库就绪…"
attempt=0
until python - <<'PY' 2>/dev/null
import asyncio, os, sys
from sqlalchemy.ext.asyncio import create_async_engine

async def main() -> None:
    engine = create_async_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)
    try:
        async with engine.connect():
            pass
    finally:
        await engine.dispose()

asyncio.run(main())
PY
do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge "$MAX_ATTEMPTS" ]; then
    echo "[entrypoint] 数据库连接超时（${MAX_ATTEMPTS} 次尝试）" >&2
    exit 1
  fi
  echo "[entrypoint] 尚未就绪（${attempt}/${MAX_ATTEMPTS}）…"
  sleep 2
done

echo "[entrypoint] 执行数据库迁移"
alembic upgrade head

echo "[entrypoint] 启动 API：0.0.0.0:${PORT}（workers=${UVICORN_WORKERS:-2}）"
# --ws-per-message-deflate：WebSocket 按消息压缩（coop / worldboss / chat 的 JSON 快照重复度高，
# 压缩比通常 5-10×）。uvicorn 默认已开启，这里显式固定，避免库默认值变化导致带宽回退。
# access log 默认关闭：高频挂机请求下每请求一行日志本身就是可观的 CPU/IO 开销，
# 需要排障时用 UVICORN_ACCESS_LOG=1 打开。
ACCESS_LOG_FLAG="--no-access-log"
if [ "${UVICORN_ACCESS_LOG:-0}" = "1" ]; then
  ACCESS_LOG_FLAG="--access-log"
fi
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers "${UVICORN_WORKERS:-2}" \
  "${ACCESS_LOG_FLAG}" \
  --ws-per-message-deflate \
  --proxy-headers \
  --forwarded-allow-ips "*"
