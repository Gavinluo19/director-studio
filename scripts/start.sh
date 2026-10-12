#!/usr/bin/env bash
set -euo pipefail
STUDIO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$STUDIO_ROOT"
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"
for tool in uv node npm ffmpeg ffprobe; do
  if ! command -v "$tool" >/dev/null 2>&1; then
    echo "缺少 $tool。请查看 docs/installation.md / Missing $tool: see docs/installation.md" >&2
    exit 1
  fi
done
if [[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]]; then
  uv sync --project app/backend --locked --extra transcription
else
  uv sync --project app/backend --locked
  echo '此平台的本地 MLX 转写不可用；核心安装不等于整条跨平台流程已验证。'
fi
if [[ ! -f app/frontend/dist/index.html || "${STUDIO_REBUILD:-0}" == 1 ]]; then
  npm --prefix app/frontend ci --ignore-scripts --no-audit --no-fund
  npm --prefix app/frontend run build
fi
echo '保持此终端运行；Control+C 停止。更新源码后使用 STUDIO_REBUILD=1 bash scripts/start.sh。'
if [[ "${STUDIO_OPEN_BROWSER:-1}" == 1 ]]; then
  exec app/backend/.venv/bin/python -m studio.launcher --open-browser "$@"
else
  exec app/backend/.venv/bin/python -m studio.launcher "$@"
fi
