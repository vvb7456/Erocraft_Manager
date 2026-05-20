#!/usr/bin/env bash
# 部署后端 manager 服务
# 用法: deploy-backend.sh [tag]   默认 main
#
# 流程:
#   1. mysqldump 备份
#   2. 下载 + 解压到 releases/<tag>/
#   3. 软链 venv/.env/logs
#   4. pip install + alembic upgrade
#   5. 原子切换 current → 新 release
#   6. 重启 systemd（web + jobs）
#   7. 健康检查；失败则回滚
set -euo pipefail

TAG_INPUT="${1:-main}"
ROOT="${MANAGER_ROOT:-/opt/erocraft_manager}"
BACKUP_DIR="${BACKUP_DIR:-/backup}"
DB_CONTAINER="${DB_CONTAINER:-pterodactyl-database-1}"
DB_NAME="${DB_NAME:-panel}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5001/api/system/version}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

require_cmd curl jq tar docker systemctl

TAG=$(resolve_tag "$TAG_INPUT")
[[ -z "$TAG" || "$TAG" == "null" ]] && { echo "❌ 无法解析 tag: $TAG_INPUT" >&2; exit 1; }

PREV=$(readlink "$ROOT/current" 2>/dev/null | xargs -r basename || true)
echo "→ backend: 部署 $TAG（当前 ${PREV:-<none>}）"

# ---- 1. 数据库备份 ----
mkdir -p "$BACKUP_DIR"
BACKUP="$BACKUP_DIR/$DB_NAME-$(date +%Y%m%d-%H%M%S).sql.gz"
docker exec "$DB_CONTAINER" mysqldump -u root --single-transaction --routines "$DB_NAME" | gzip > "$BACKUP"
echo "  数据库已备份: $BACKUP"

# ---- 2. 下载 + 解压 ----
mkdir -p "$ROOT/releases/$TAG"
if [[ -n "$(ls -A "$ROOT/releases/$TAG" 2>/dev/null)" ]]; then
  echo "  $TAG 已存在，跳过下载"
else
  TMP=$(mktemp)
  trap 'rm -f "$TMP"' EXIT
  gh_download "^manager-backend-.*\\.tar\\.gz$" "$TAG" "$TMP"
  tar -xzf "$TMP" --strip-components=1 -C "$ROOT/releases/$TAG"
  rm -f "$TMP"
  trap - EXIT
fi

# ---- 3. 软链共享资源 ----
ln -sfn "$ROOT/venv" "$ROOT/releases/$TAG/venv"
ln -sfn "$ROOT/.env" "$ROOT/releases/$TAG/.env"
ln -sfn "$ROOT/logs" "$ROOT/releases/$TAG/logs"

# ---- 4. 依赖 + 迁移 ----
"$ROOT/venv/bin/pip" install -q -r "$ROOT/releases/$TAG/requirements.txt"
( cd "$ROOT/releases/$TAG" && "$ROOT/venv/bin/alembic" -c alembic.ini upgrade head )

# ---- 5. 原子切换 + 6. 重启 ----
atomic_switch "$ROOT/releases" "$TAG" "$ROOT/current"
systemctl restart erocraft-manager-web erocraft-manager-jobs

# ---- 7. 健康检查 ----
for _ in $(seq 1 10); do
  sleep 2
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "✓ backend $TAG 已激活（健康检查通过）"
    prune_old "$ROOT/releases"
    exit 0
  fi
done

# ---- 失败回滚 ----
echo "❌ 健康检查超时" >&2
if [[ -n "$PREV" && -d "$ROOT/releases/$PREV" ]]; then
  echo "→ 回滚到 $PREV" >&2
  atomic_switch "$ROOT/releases" "$PREV" "$ROOT/current"
  ( cd "$ROOT/releases/$PREV" && "$ROOT/venv/bin/alembic" -c alembic.ini downgrade -1 ) \
    || echo "⚠ alembic 回滚失败，需手工处理" >&2
  systemctl restart erocraft-manager-web erocraft-manager-jobs
  echo "→ 已回滚到 $PREV（请人工排查 $TAG 的问题）" >&2
fi
exit 1
