#!/bin/sh
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
if ! command -v uv >/dev/null 2>&1; then
  echo '需要先安装 uv：https://docs.astral.sh/uv/getting-started/installation/' >&2
  exit 1
fi
uv sync --frozen
echo '打开 http://127.0.0.1:8640；按 Ctrl+C 停止服务。'
exec uv run centerstage serve "$@"
