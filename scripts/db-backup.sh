#!/bin/sh
# 数据库定时备份（PostgreSQL）。
#
# 由 docker compose 的 `db-backup` 服务周期调用：pg_dump 导出整库 → 打包为
# tar.gz 压缩包，并按份数只保留最近的若干个，避免磁盘被无限占用。
#
# 也可在宿主机直接运行（需本机有 pg_dump，且 PG* 环境变量指向目标库）：
#   PGHOST=127.0.0.1 PGUSER=eorzea PGPASSWORD=*** PGDATABASE=eorzea \
#     BACKUP_DIR=./data/backups BACKUP_INTERVAL_HOURS=6 BACKUP_KEEP=7 \
#     sh scripts/db-backup.sh
#
# 环境变量：
#   PGHOST / PGPORT / PGUSER / PGPASSWORD / PGDATABASE  目标数据库（PGPASSWORD 由编排注入）
#   BACKUP_DIR               压缩包输出目录（容器内默认 /backups）
#   BACKUP_INTERVAL_HOURS    备份间隔小时数（默认 6）
#   BACKUP_KEEP              保留最近几份（默认 7；<=0 表示不清理）
#   BACKUP_PREFIX            压缩包文件名前缀（默认 eorzea）
#   BACKUP_RUN_ONCE=1        只备份一次后退出（用于手动触发 / 定时任务）
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_INTERVAL_HOURS="${BACKUP_INTERVAL_HOURS:-6}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
BACKUP_PREFIX="${BACKUP_PREFIX:-eorzea}"

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-eorzea}"
PGDATABASE="${PGDATABASE:-eorzea}"
export PGHOST PGPORT PGUSER PGDATABASE

log() { echo "[db-backup] $(date '+%Y-%m-%d %H:%M:%S') $*"; }

backup_once() {
  ts="$(date +%Y%m%d-%H%M%S)"
  out="${BACKUP_DIR}/${BACKUP_PREFIX}-${ts}.tar.gz"
  tmp="$(mktemp -d)"
  log "开始备份 ${PGDATABASE}@${PGHOST}:${PGPORT} → ${out}"
  # --clean --if-exists 让 dump.sql 自带 DROP，可直接重放覆盖现有库。
  if ! pg_dump --no-owner --no-privileges --clean --if-exists -f "${tmp}/dump.sql"; then
    log "pg_dump 失败，跳过本次备份"
    rm -rf "${tmp}"
    return 1
  fi
  {
    echo "database=${PGDATABASE}"
    echo "host=${PGHOST}"
    echo "port=${PGPORT}"
    echo "created_at=${ts}"
    echo "pg_dump_version=$(pg_dump --version)"
  } > "${tmp}/manifest.txt"
  tar -czf "${out}" -C "${tmp}" dump.sql manifest.txt
  rm -rf "${tmp}"
  log "备份完成：${out}（$(wc -c < "${out}") 字节）"
}

prune() {
  [ "${BACKUP_KEEP}" -gt 0 ] 2>/dev/null || return 0
  # ls -1t：按修改时间由新到旧；删除第 BACKUP_KEEP+1 份及更早的。
  list="$(ls -1t "${BACKUP_DIR}/${BACKUP_PREFIX}"-*.tar.gz 2>/dev/null || true)"
  [ -n "${list}" ] || return 0
  printf '%s\n' "${list}" | tail -n "+$((BACKUP_KEEP + 1))" | while IFS= read -r old; do
    [ -n "${old}" ] || continue
    log "清理旧备份 ${old}"
    rm -f "${old}"
  done
}

mkdir -p "${BACKUP_DIR}"

if [ "${BACKUP_RUN_ONCE:-0}" = "1" ]; then
  backup_once
  prune
  exit 0
fi

while true; do
  backup_once || true
  prune || true
  log "下次备份在 ${BACKUP_INTERVAL_HOURS} 小时后"
  sleep "$((BACKUP_INTERVAL_HOURS * 3600))"
done
