#!/usr/bin/env bash
#
# 艾欧泽亚放置录 — 本地一键启动（不需要 Docker）
#
#   ./scripts/dev.sh            启动后端 + 前端（Ctrl-C 一起退出）
#   ./scripts/dev.sh --reset    先清空本地数据库再启动
#   ./scripts/dev.sh test       只跑测试（后端 pytest + 前端 vitest + 类型检查）
#   ./scripts/dev.sh backend    只启动后端
#   ./scripts/dev.sh frontend   只启动前端
#
# 端口与数据库配置来自仓库根目录的 .env.local（首次运行会自动从 .env.local.example 生成）。
# 本地默认使用 SQLite，无需安装任何数据库。

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

ENV_FILE="${ENV_FILE:-$ROOT_DIR/.env.local}"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
LOG_DIR="$ROOT_DIR/.dev-logs"

# 让每个后台任务自成进程组，退出时可以整组回收（uvicorn --reload / vite 都会派生子进程）
set -m

# ──────────────────────────── 输出工具 ────────────────────────────
if [ -t 1 ]; then
  C_RESET=$'\033[0m'; C_DIM=$'\033[2m'; C_RED=$'\033[31m'
  C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'
else
  C_RESET=''; C_DIM=''; C_RED=''; C_GREEN=''; C_YELLOW=''; C_CYAN=''
fi
info() { printf '%s▸ %s%s\n' "$C_CYAN" "$*" "$C_RESET"; }
ok()   { printf '%s✓ %s%s\n' "$C_GREEN" "$*" "$C_RESET"; }
warn() { printf '%s! %s%s\n' "$C_YELLOW" "$*" "$C_RESET"; }
die()  { printf '%s✗ %s%s\n' "$C_RED" "$*" "$C_RESET" >&2; exit 1; }

usage() {
  cat <<'EOF'

艾欧泽亚放置录 — 本地一键启动（不需要 Docker）

  ./scripts/dev.sh            启动后端 + 前端（Ctrl-C 一起退出）
  ./scripts/dev.sh --reset    先清空本地数据库再启动
  ./scripts/dev.sh backend    只启动后端
  ./scripts/dev.sh frontend   只启动前端
  ./scripts/dev.sh test       跑全部测试（后端 pytest + 前端 vitest + 类型检查）
  ./scripts/dev.sh help       显示本帮助

配置文件：仓库根目录的 .env.local（首次运行会自动从 .env.local.example 生成）
  可配置 BACKEND_PORT / FRONTEND_PORT / DATABASE_URL / JWT_SECRET 等。
  依赖默认走国内镜像（pip 用清华，npm 用 npmmirror），
  可用 PIP_INDEX_URL / NPM_REGISTRY 覆盖，改为官方源或其它镜像。
  本地默认使用 SQLite，无需安装数据库；若本机已有 PostgreSQL，
  把 DATABASE_URL 改成 postgresql+asyncpg://... 即可。

日志目录：.dev-logs/

EOF
}

# ──────────────────────────── 环境文件 ────────────────────────────
if [ ! -f "$ENV_FILE" ]; then
  cp "$ROOT_DIR/.env.local.example" "$ENV_FILE"
  ok "已生成 $ENV_FILE（本地默认使用 SQLite）"
fi

set -a
# shellcheck disable=SC1090
. "$ENV_FILE"
set +a

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
HOST="${HOST:-127.0.0.1}"
DATABASE_URL="${DATABASE_URL:-sqlite+aiosqlite:///./dev.db}"
JWT_SECRET="${JWT_SECRET:-dev-only-secret-change-me-0123456789abcdef}"
JWT_EXPIRE_HOURS="${JWT_EXPIRE_HOURS:-24}"
REPORT_TOLERANCE="${REPORT_TOLERANCE:-1.10}"
AUTO_CREATE_TABLES="${AUTO_CREATE_TABLES:-true}"

# 依赖下载源：默认走国内镜像，可在 .env.local 中覆盖（改为官方源或其它镜像）
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"
# pip / npm 都会自动读取这两个环境变量
if [ -n "$PIP_INDEX_URL" ]; then
  export PIP_INDEX_URL
fi
if [ -n "$NPM_REGISTRY" ]; then
  export npm_config_registry="$NPM_REGISTRY"
fi

# 后端允许的来源必须与前端实际访问地址一致，否则浏览器会被 CORS 拦截
export CORS_ORIGINS="http://localhost:${FRONTEND_PORT},http://127.0.0.1:${FRONTEND_PORT}"

# ──────────────────────────── Python 环境 ────────────────────────────
pick_python() {
  local candidate
  for candidate in python3.12 python3.11 python3; do
    if command -v "$candidate" >/dev/null 2>&1 \
      && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  return 1
}

ensure_backend() {
  if [ ! -d "$BACKEND_DIR/.venv" ]; then
    local py
    py="$(pick_python)" || die "未找到 Python 3.11+，请先安装（macOS: brew install python@3.12）"
    info "创建虚拟环境（$py）"
    "$py" -m venv "$BACKEND_DIR/.venv"
  fi

  local stamp="$BACKEND_DIR/.venv/.deps-stamp"
  local fingerprint
  fingerprint="$(shasum "$BACKEND_DIR/pyproject.toml" | cut -d' ' -f1)"
  if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$fingerprint" ]; then
    info "安装后端依赖（首次或依赖有变更，可能需要一分钟）"
    "$BACKEND_DIR/.venv/bin/pip" install -q --upgrade pip
    "$BACKEND_DIR/.venv/bin/pip" install -q -e "$BACKEND_DIR[dev]"
    printf '%s' "$fingerprint" > "$stamp"
    ok "后端依赖就绪"
  fi
}

ensure_frontend() {
  if [ ! -d "$ROOT_DIR/node_modules" ] || [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    info "安装前端依赖"
    (cd "$ROOT_DIR" && npm install --no-fund --no-audit)
    ok "前端依赖就绪"
  fi
}

# ──────────────────────────── 端口检查 ────────────────────────────
port_in_use() {
  command -v lsof >/dev/null 2>&1 || return 1
  lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1
}

require_free_port() {
  local port="$1" name="$2"
  if port_in_use "$port"; then
    die "$name 端口 $port 已被占用。请修改 $ENV_FILE 中的端口，或先停止占用进程：
    lsof -nP -iTCP:$port -sTCP:LISTEN"
  fi
}

# ──────────────────────────── 数据库 ────────────────────────────
reset_database() {
  case "$DATABASE_URL" in
    *sqlite*)
      local db_file
      db_file="$(printf '%s' "$DATABASE_URL" | sed -E 's#.*:///##; s#^\./##')"
      case "$db_file" in
        /*) ;;
        *) db_file="$BACKEND_DIR/$db_file" ;;
      esac
      rm -f "$db_file"
      ok "已删除本地 SQLite 数据库：$db_file"
      ;;
    *)
      warn "DATABASE_URL 非 SQLite（$DATABASE_URL），--reset 不会清空远程数据库，已跳过"
      ;;
  esac
}

# ──────────────────────────── 进程管理 ────────────────────────────
PIDS=()
CLEANED=0
SHUTTING_DOWN=0

cleanup() {
  [ "$CLEANED" -eq 1 ] && return 0
  CLEANED=1

  # 没有启动过任何服务时保持安静
  [ "${#PIDS[@]}" -eq 0 ] && return 0

  printf '\n'
  info "正在停止服务…"

  local pid
  for pid in "${PIDS[@]:-}"; do
    [ -n "${pid:-}" ] || continue
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
  done

  # 最多等待 5 秒优雅退出
  local waited=0 alive
  while [ "$waited" -lt 10 ]; do
    alive=0
    for pid in "${PIDS[@]:-}"; do
      [ -n "${pid:-}" ] || continue
      kill -0 "$pid" 2>/dev/null && alive=1
    done
    [ "$alive" -eq 0 ] && break
    sleep 0.5
    waited=$((waited + 1))
  done

  # 仍未退出则整组强杀
  for pid in "${PIDS[@]:-}"; do
    [ -n "${pid:-}" ] || continue
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
    fi
  done

  ok "已停止全部服务"
}

on_exit() {
  SHUTTING_DOWN=1
  cleanup
}

on_signal() {
  SHUTTING_DOWN=1
  cleanup
  exit 0
}

trap on_exit EXIT
trap on_signal INT TERM HUP

wait_for_backend() {
  local url="http://${HOST}:${BACKEND_PORT}/health"
  local i
  for i in $(seq 1 60); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      ok "后端就绪：$url"
      return 0
    fi
    sleep 0.5
  done
  warn "后端未在 30 秒内就绪，请查看日志：$LOG_DIR/backend.log"
  return 1
}

# ──────────────────────────── 启动 ────────────────────────────
start_backend() {
  ensure_backend
  require_free_port "$BACKEND_PORT" "后端"
  mkdir -p "$LOG_DIR"

  info "启动后端 (FastAPI) → http://${HOST}:${BACKEND_PORT}"
  (
    cd "$BACKEND_DIR"
    exec env \
      DATABASE_URL="$DATABASE_URL" \
      JWT_SECRET="$JWT_SECRET" \
      JWT_EXPIRE_HOURS="$JWT_EXPIRE_HOURS" \
      CORS_ORIGINS="$CORS_ORIGINS" \
      REPORT_TOLERANCE="$REPORT_TOLERANCE" \
      AUTO_CREATE_TABLES="$AUTO_CREATE_TABLES" \
      .venv/bin/uvicorn app.main:app --host "$HOST" --port "$BACKEND_PORT" --reload
  ) >"$LOG_DIR/backend.log" 2>&1 &
  PIDS+=("$!")
  wait_for_backend
  (
    cd "$BACKEND_DIR"
    exec env DATABASE_URL="$DATABASE_URL" JWT_SECRET="$JWT_SECRET" .venv/bin/python -m app.coop_worker
  ) >"$LOG_DIR/coop-worker.log" 2>&1 &
  PIDS+=("$!")
  info "启动世界BOSS 推进进程 (worldboss-worker)"
  (
    cd "$BACKEND_DIR"
    exec env DATABASE_URL="$DATABASE_URL" JWT_SECRET="$JWT_SECRET" .venv/bin/python -m app.worldboss_worker
  ) >"$LOG_DIR/worldboss-worker.log" 2>&1 &
  PIDS+=("$!")
}

start_frontend() {
  ensure_frontend
  require_free_port "$FRONTEND_PORT" "前端"
  mkdir -p "$LOG_DIR"

  local vite_bin="$ROOT_DIR/node_modules/.bin/vite"
  info "启动前端 (Vite)  → http://localhost:${FRONTEND_PORT}"
  (
    cd "$FRONTEND_DIR"
    export VITE_API_BASE="http://${HOST}:${BACKEND_PORT}/api/v1"
    if [ -x "$vite_bin" ]; then
      exec "$vite_bin" --host --port "$FRONTEND_PORT" --strictPort
    else
      exec npx --no-install vite --host --port "$FRONTEND_PORT" --strictPort
    fi
  ) >"$LOG_DIR/frontend.log" 2>&1 &
  PIDS+=("$!")
}

wait_forever() {
  printf '\n'
  printf '%s──────────────────────────────────────────────%s\n' "$C_DIM" "$C_RESET"
  printf '  游戏入口    %shttp://localhost:%s%s\n' "$C_CYAN" "$FRONTEND_PORT" "$C_RESET"
  printf '  接口文档    %shttp://%s:%s/docs%s\n' "$C_DIM" "$HOST" "$BACKEND_PORT" "$C_RESET"
  printf '  后端日志    %s%s/backend.log%s\n' "$C_DIM" "$LOG_DIR" "$C_RESET"
  printf '  前端日志    %s%s/frontend.log%s\n' "$C_DIM" "$LOG_DIR" "$C_RESET"
  printf '%s──────────────────────────────────────────────%s\n' "$C_DIM" "$C_RESET"
  printf '  按 Ctrl-C 停止全部服务\n\n'

  local pid
  while true; do
    for pid in "${PIDS[@]}"; do
      if ! kill -0 "$pid" 2>/dev/null; then
        # 主动退出（Ctrl-C / SIGTERM）时不报错
        [ "$SHUTTING_DOWN" -eq 1 ] && exit 0
        die "有服务异常退出，请查看 $LOG_DIR 下的日志"
      fi
    done
    sleep 1
  done
}

run_tests() {
  ensure_backend
  ensure_frontend
  printf '\n%s── 后端测试 ──%s\n' "$C_CYAN" "$C_RESET"
  (cd "$BACKEND_DIR" && .venv/bin/python -m pytest tests/ -q)
  printf '\n%s── 前端测试 ──%s\n' "$C_CYAN" "$C_RESET"
  (cd "$FRONTEND_DIR" && npx --no-install vitest run)
  printf '\n%s── 前端类型检查 ──%s\n' "$C_CYAN" "$C_RESET"
  (cd "$FRONTEND_DIR" && npx --no-install vue-tsc --noEmit && echo "类型检查通过")
  printf '\n'
  ok "全部检查通过"
}

# ──────────────────────────── 入口 ────────────────────────────
MODE="${1:-all}"
case "$MODE" in
  --reset)
    reset_database
    start_backend
    wait_for_backend || true
    start_frontend
    wait_forever
    ;;
  all)
    start_backend
    wait_for_backend || true
    start_frontend
    wait_forever
    ;;
  backend)
    start_backend
    wait_for_backend || true
    wait_forever
    ;;
  frontend)
    start_frontend
    wait_forever
    ;;
  test)
    run_tests
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    die "未知参数：$MODE（可用：all / --reset / backend / frontend / test / help）"
    ;;
esac
