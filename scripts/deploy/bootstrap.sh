#!/usr/bin/env bash
# 把生产从「git 工作区模式」迁移到「tarball + symlink」模式
# 仅运行一次。运行后会:
#   1. 备份并移除 /opt/erocraft_manager/.git（dirty 内容已在 origin/main）
#   2. 把现有 app/ alembic/ 等目录改名为 *.pre-cicd.<ts>（不删，便于回退）
#   3. 创建新布局: releases/, bin/, current symlink（待生成）
#   4. 安装 deploy-*.sh 脚本到 bin/
#   5. 调用 deploy-backend.sh + deploy-frontend.sh 拉取 main 最新 release
#   6. 打印手工操作提示（修改 systemd / nginx）
#
# 用法（在生产 console.erocraft.com 上）:
#   curl -fsSL https://raw.githubusercontent.com/vvb7456/Erocraft_Manager/main/scripts/deploy/bootstrap.sh | bash
# 或先下载、审阅后再执行。
set -euo pipefail

DEST="${MANAGER_ROOT:-/opt/erocraft_manager}"
WEB_ROOT="${FRONTEND_ROOT:-/var/www/console.erocraft.com}"
RAW_BASE="https://raw.githubusercontent.com/vvb7456/Erocraft_Manager/main/scripts/deploy"
TS=$(date +%Y%m%d-%H%M%S)

echo "==== Erocraft Manager bootstrap (CI/CD migration) ===="
echo "DEST     = $DEST"
echo "WEB_ROOT = $WEB_ROOT"
echo

# 0. 必备命令
for c in curl jq tar systemctl docker; do
  command -v "$c" >/dev/null || { echo "❌ 缺少 $c" >&2; exit 1; }
done

# 1. 备份 .git
if [[ -d "$DEST/.git" ]]; then
  GIT_BAK="/tmp/erocraft_manager.git.bak.$TS"
  echo "→ 备份 .git → $GIT_BAK"
  mv "$DEST/.git" "$GIT_BAK"
fi

# 2. 把旧源码改名（保留以便回退）
for d in app alembic templates scripts static; do
  src="$DEST/$d"
  if [[ -e "$src" && ! -L "$src" ]]; then
    echo "→ 重命名 $src → $src.pre-cicd.$TS"
    mv "$src" "$src.pre-cicd.$TS"
  fi
done

# 3. 创建目录
mkdir -p "$DEST/releases" "$DEST/bin" "$WEB_ROOT/releases"

# 4. 安装部署脚本
echo "→ 下载部署脚本"
for s in lib.sh deploy-frontend.sh deploy-backend.sh deploy-agent.sh; do
  curl -fsSL "$RAW_BASE/$s" -o "$DEST/bin/$s"
done
chmod +x "$DEST/bin/"*.sh
echo "  ✓ $DEST/bin/{lib.sh,deploy-frontend.sh,deploy-backend.sh,deploy-agent.sh}"

# 5. 拉取并部署最新 release
echo
echo "→ 拉取 backend (main)"
"$DEST/bin/deploy-backend.sh" main || {
  echo "⚠ backend 部署失败，请检查输出后手工重试。前端步骤跳过。" >&2
  exit 1
}

echo
echo "→ 拉取 frontend (main)"
"$DEST/bin/deploy-frontend.sh" main

# 6. 提示
cat <<EOF

═══════════════════════════════════════════════════════════
✓ 文件就位。请手工执行以下步骤完成 systemd / nginx 切换:
═══════════════════════════════════════════════════════════

# (a) 修改 systemd unit 的 WorkingDirectory
sudo sed -i 's|WorkingDirectory=$DEST\$|WorkingDirectory=$DEST/current|' \\
  /etc/systemd/system/erocraft-manager-web.service \\
  /etc/systemd/system/erocraft-manager-jobs.service
sudo systemctl daemon-reload
sudo systemctl restart erocraft-manager-web erocraft-manager-jobs

# (b) 修改 nginx root（如 vhost 配置文件名不同请相应调整）
sudo sed -i 's|root $DEST/static/dist;|root $WEB_ROOT/current;|' \\
  /etc/nginx/sites-enabled/console.erocraft.com.conf
sudo nginx -t && sudo systemctl reload nginx

# (c) 浏览器验证（登录、服务器列表、SSE、文件管理）后清理:
sudo rm -rf $DEST/*.pre-cicd.$TS
sudo rm -rf /tmp/erocraft_manager.git.bak.*

# 今后部署:
sudo $DEST/bin/deploy-backend.sh  main           # 或 latest / v1.2.3
sudo $DEST/bin/deploy-frontend.sh main

═══════════════════════════════════════════════════════════
EOF
