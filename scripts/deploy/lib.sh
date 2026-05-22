# shellcheck shell=bash
# 公共函数：供 deploy-{frontend,backend,agent}.sh 复用
# 通过 `source "$(dirname "$0")/lib.sh"` 引入

REPO="${EROCRAFT_REPO:-vvb7456/Erocraft_Manager}"
KEEP_RELEASES="${KEEP_RELEASES:-5}"

# 当 GitHub 直连受限时，可改走镜像站：
#   GITHUB_API          — releases JSON API 入口（默认 api.github.com）
#   GITHUB_DL_PREFIX    — 拼接在最终下载 URL 之前的前缀（如 https://ghfast.top/）
# 例：export GITHUB_API=https://api.kkgithub.com GITHUB_DL_PREFIX=https://ghfast.top/
GITHUB_API="${GITHUB_API:-https://api.github.com}"
GITHUB_DL_PREFIX="${GITHUB_DL_PREFIX:-}"

# 用法: gh_download <name-regex> <tag> <dest-file>
gh_download() {
  local pattern="$1" tag="$2" dest="$3"
  local auth=()
  [[ -n "${GITHUB_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer $GITHUB_TOKEN")

  local url
  url=$(curl -fsSL "${auth[@]}" "$GITHUB_API/repos/$REPO/releases/tags/$tag" \
        | jq -r --arg p "$pattern" '.assets[] | select(.name | test($p)) | .browser_download_url')

  if [[ -z "$url" || "$url" == "null" ]]; then
    echo "❌ asset matching /$pattern/ not found in release $tag" >&2
    return 1
  fi

  # 通过镜像前缀加速 release 下载（ghfast / ghproxy / gh-proxy 等同款代理）。
  [[ -n "$GITHUB_DL_PREFIX" ]] && url="${GITHUB_DL_PREFIX%/}/${url}"

  curl -fsSL "${auth[@]}" -o "$dest" "$url"
}

# 用法: resolve_tag <latest|main|v1.2.3|main-abc1234>
# - latest: 最新正式 release（非 prerelease）
# - main  : 最近一次 main 分支自动构建（main-<sha>）
# - 其他  : 原样返回
resolve_tag() {
  local input="$1"
  case "$input" in
    latest)
      curl -fsSL "$GITHUB_API/repos/$REPO/releases/latest" | jq -r .tag_name
      ;;
    main)
      curl -fsSL "$GITHUB_API/repos/$REPO/releases?per_page=30" \
        | jq -r '[.[] | select(.tag_name | startswith("main-"))]
                  | sort_by(.created_at) | reverse | .[0].tag_name'
      ;;
    *)
      echo "$input"
      ;;
  esac
}

# 用法: prune_old <releases_dir>
# 保留 $KEEP_RELEASES 个最新目录，其余删除
prune_old() {
  local dir="$1"
  [[ -d "$dir" ]] || return 0
  # shellcheck disable=SC2012
  ls -1t "$dir" 2>/dev/null \
    | tail -n +$((KEEP_RELEASES + 1)) \
    | while IFS= read -r old; do
        rm -rf -- "${dir:?}/$old"
      done
}

# 用法: atomic_switch <releases_dir> <new_release_name> <current_symlink>
atomic_switch() {
  local releases_dir="$1" name="$2" link="$3"
  ln -sfn "$releases_dir/$name" "$link.new"
  mv -Tf "$link.new" "$link"
}

# 用法: require_cmd jq curl tar
require_cmd() {
  local missing=()
  for c in "$@"; do
    command -v "$c" >/dev/null 2>&1 || missing+=("$c")
  done
  if ((${#missing[@]})); then
    echo "❌ 缺少命令: ${missing[*]}（请 apt install ${missing[*]}）" >&2
    return 1
  fi
}
