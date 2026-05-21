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
# 数据库备份模式: docker | host | skip
# 生产环境 panel DB 跑在主机上，默认使用 host
DB_BACKUP_MODE="${DB_BACKUP_MODE:-host}"
DB_CONTAINER="${DB_CONTAINER:-pterodactyl-database-1}"
# host 模式凭证来源（按优先级）：
#   1) 显式环境变量 DB_HOST/DB_PORT/DB_USER/DB_PASSWORD/DB_NAME
#   2) DB_DEFAULTS_FILE  —— MySQL [client] 段配置文件
#   3) DB_ENV_FILE       —— manager 自己的 .env（默认 $ROOT/.env），从中读取同名键
# 凭证全部缺失时直接报错，不再交互式 prompt 挂起。
DB_ENV_FILE="${DB_ENV_FILE:-$ROOT/.env}"
DB_DEFAULTS_FILE="${DB_DEFAULTS_FILE:-}"

_read_env_var() {
  # 从 dotenv 风格文件中读取指定键的值（不展开变量，仅取最后一次定义）
  local file="$1" key="$2"
  [[ -r "$file" ]] || return 1
  local line
  line=$(grep -E "^[[:space:]]*${key}=" "$file" | tail -n1) || return 1
  [[ -z "$line" ]] && return 1
  local val="${line#*=}"
  # 去掉前后引号
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  printf '%s' "$val"
}

if [[ "$DB_BACKUP_MODE" == "host" && -z "${DB_PASSWORD:-}" && -z "$DB_DEFAULTS_FILE" && -r "$DB_ENV_FILE" ]]; then
  DB_HOST="${DB_HOST:-$(_read_env_var "$DB_ENV_FILE" DB_HOST || true)}"
  DB_PORT="${DB_PORT:-$(_read_env_var "$DB_ENV_FILE" DB_PORT || true)}"
  DB_USER="${DB_USER:-$(_read_env_var "$DB_ENV_FILE" DB_USER || true)}"
  DB_PASSWORD="${DB_PASSWORD:-$(_read_env_var "$DB_ENV_FILE" DB_PASSWORD || true)}"
  DB_NAME="${DB_NAME:-$(_read_env_var "$DB_ENV_FILE" DB_NAME || true)}"
fi

DB_HOST="${DB_HOST:-127.0.0.1}"
DB_PORT="${DB_PORT:-3306}"
DB_USER="${DB_USER:-root}"
DB_PASSWORD="${DB_PASSWORD:-}"
DB_NAME="${DB_NAME:-panel}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:5001/api/version}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

require_cmd curl jq tar systemctl
[[ "$DB_BACKUP_MODE" == "docker" ]] && require_cmd docker
[[ "$DB_BACKUP_MODE" == "host"   ]] && require_cmd mysqldump

TAG=$(resolve_tag "$TAG_INPUT")
[[ -z "$TAG" || "$TAG" == "null" ]] && { echo "❌ 无法解析 tag: $TAG_INPUT" >&2; exit 1; }

PREV=$(readlink "$ROOT/current" 2>/dev/null | xargs -r basename || true)
echo "→ backend: 部署 $TAG（当前 ${PREV:-<none>}）"

# ---- 1. 数据库备份 ----
if [[ "$DB_BACKUP_MODE" == "skip" ]]; then
  echo "  DB_BACKUP_MODE=skip，跳过数据库备份"
else
  mkdir -p "$BACKUP_DIR"
  BACKUP="$BACKUP_DIR/$DB_NAME-$(date +%Y%m%d-%H%M%S).sql.gz"
  case "$DB_BACKUP_MODE" in
    docker)
      docker exec "$DB_CONTAINER" mysqldump -u root --single-transaction --routines "$DB_NAME" | gzip > "$BACKUP"
      ;;
    host)
      # 优先使用 defaults-file（含 [client] user/password），其次走 MYSQL_PWD 环境变量
      # 避免 `-p""` 在密码缺失时让 mysqldump 交互式 prompt 而把 SSH 会话挂死
      if [[ -n "$DB_DEFAULTS_FILE" ]]; then
        [[ -r "$DB_DEFAULTS_FILE" ]] || { echo "❌ DB_DEFAULTS_FILE 不可读: $DB_DEFAULTS_FILE" >&2; exit 1; }
        mysqldump --defaults-file="$DB_DEFAULTS_FILE" \
          -h"$DB_HOST" -P"$DB_PORT" \
          --single-transaction --routines "$DB_NAME" | gzip > "$BACKUP"
      elif [[ -n "$DB_PASSWORD" ]]; then
        MYSQL_PWD="$DB_PASSWORD" mysqldump -h"$DB_HOST" -P"$DB_PORT" -u"$DB_USER" \
          --single-transaction --routines "$DB_NAME" | gzip > "$BACKUP"
      else
        echo "❌ host 模式需要 DB_PASSWORD 或 DB_DEFAULTS_FILE（避免 mysqldump 交互式挂起）；如需跳过请显式 DB_BACKUP_MODE=skip" >&2
        exit 1
      fi
      ;;
    *)
      echo "❌ 未知 DB_BACKUP_MODE: $DB_BACKUP_MODE（docker|host|skip）" >&2; exit 1
      ;;
  esac
  echo "  数据库已备份: $BACKUP"
fi

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
if [[ "${SKIP_ALEMBIC:-0}" == "1" ]]; then
  echo "  SKIP_ALEMBIC=1，跳过 alembic upgrade"
else
  ( cd "$ROOT/releases/$TAG" && "$ROOT/venv/bin/alembic" -c alembic.ini upgrade head )
fi

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
  if [[ "${SKIP_ALEMBIC:-0}" != "1" ]]; then
    ( cd "$ROOT/releases/$PREV" && "$ROOT/venv/bin/alembic" -c alembic.ini downgrade -1 ) \
      || echo "⚠ alembic 回滚失败，需手工处理" >&2
  fi
  systemctl restart erocraft-manager-web erocraft-manager-jobs
  echo "→ 已回滚到 $PREV（请人工排查 $TAG 的问题）" >&2
fi
exit 1
