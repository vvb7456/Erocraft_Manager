#!/usr/bin/env bash
# 部署前端静态文件到 /var/www/console.erocraft.com/
# 用法: deploy-frontend.sh [tag]   默认 main
set -euo pipefail

TAG_INPUT="${1:-main}"
ROOT="${FRONTEND_ROOT:-/var/www/console.erocraft.com}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

require_cmd curl jq tar

TAG=$(resolve_tag "$TAG_INPUT")
[[ -z "$TAG" || "$TAG" == "null" ]] && { echo "❌ 无法解析 tag: $TAG_INPUT" >&2; exit 1; }

echo "→ frontend: 部署 $TAG → $ROOT"

mkdir -p "$ROOT/releases/$TAG"
if [[ -n "$(ls -A "$ROOT/releases/$TAG" 2>/dev/null)" ]]; then
  echo "  $TAG 已存在，跳过下载"
else
  TMP=$(mktemp)
  trap 'rm -f "$TMP"' EXIT
  gh_download "^frontend-dist-.*\\.tar\\.gz$" "$TAG" "$TMP"
  tar -xzf "$TMP" -C "$ROOT/releases/$TAG"
  rm -f "$TMP"
  trap - EXIT
fi

atomic_switch "$ROOT/releases" "$TAG" "$ROOT/current"
prune_old "$ROOT/releases"

echo "✓ frontend $TAG 已激活"
