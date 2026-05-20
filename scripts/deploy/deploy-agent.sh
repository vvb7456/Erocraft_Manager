#!/usr/bin/env bash
# 部署 erocraft-agent
# 用法: deploy-agent.sh [tag]   默认 main
set -euo pipefail

TAG_INPUT="${1:-main}"
ROOT="${AGENT_ROOT:-/opt/erocraft-agent}"
HEALTH_URL="${AGENT_HEALTH_URL:-}"   # 可选，留空跳过 HTTP 检查

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"

require_cmd curl jq tar systemctl

TAG=$(resolve_tag "$TAG_INPUT")
[[ -z "$TAG" || "$TAG" == "null" ]] && { echo "❌ 无法解析 tag: $TAG_INPUT" >&2; exit 1; }

PREV=$(readlink "$ROOT/current" 2>/dev/null | xargs -r basename || true)
echo "→ agent: 部署 $TAG（当前 ${PREV:-<none>}） → $ROOT"

mkdir -p "$ROOT/releases/$TAG/agent"
if [[ -n "$(ls -A "$ROOT/releases/$TAG/agent" 2>/dev/null)" ]]; then
  echo "  $TAG 已存在，跳过下载"
else
  TMP=$(mktemp)
  trap 'rm -f "$TMP"' EXIT
  gh_download "^agent-.*\\.tar\\.gz$" "$TAG" "$TMP"
  # tarball 内是 agent 包的内容（agent.py / collectors/ ...），
  # 解压到 releases/$TAG/agent/ 形成 Python 包目录
  tar -xzf "$TMP" -C "$ROOT/releases/$TAG/agent"
  rm -f "$TMP"
  trap - EXIT
fi

# 软链共享资源（venv/agent.yaml/config.yaml 放在 release 目录顶层，与 agent/ 同级）
ln -sfn "$ROOT/venv" "$ROOT/releases/$TAG/venv"
[[ -e "$ROOT/agent.yaml" ]]  && ln -sfn "$ROOT/agent.yaml"  "$ROOT/releases/$TAG/agent.yaml"
[[ -e "$ROOT/config.yaml" ]] && ln -sfn "$ROOT/config.yaml" "$ROOT/releases/$TAG/config.yaml"

# 安装依赖
"$ROOT/venv/bin/pip" install -q -r "$ROOT/releases/$TAG/agent/requirements.txt"

atomic_switch "$ROOT/releases" "$TAG" "$ROOT/current"
systemctl restart erocraft-agent

# 健康检查
sleep 3
ok=1
systemctl is-active --quiet erocraft-agent || ok=0
if [[ "$ok" == "1" && -n "$HEALTH_URL" ]]; then
  curl -fsS "$HEALTH_URL" >/dev/null 2>&1 || ok=0
fi

if [[ "$ok" == "1" ]]; then
  echo "✓ agent $TAG 已激活"
  prune_old "$ROOT/releases"
  exit 0
fi

echo "❌ agent 启动失败" >&2
if [[ -n "$PREV" && -d "$ROOT/releases/$PREV" ]]; then
  echo "→ 回滚到 $PREV" >&2
  atomic_switch "$ROOT/releases" "$PREV" "$ROOT/current"
  systemctl restart erocraft-agent
fi
exit 1
