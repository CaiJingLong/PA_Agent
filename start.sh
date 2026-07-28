#!/usr/bin/env bash
# PA Agent 启动脚本（macOS / Linux）
# 用法: ./start.sh
set -euo pipefail

# 切到脚本所在目录（项目根），保证能找到 pa_agent 包与 config
cd "$(dirname "$(readlink -f "$0" 2>/dev/null || echo "$0")")"

echo "============================================================"
echo "  Starting PA Agent (Price Action AI Analysis)..."
echo "  Project dir: $(pwd)"
echo "============================================================"
echo

# 优先用 uv 隔离环境；没有 uv 就回退到系统 python
if command -v uv >/dev/null 2>&1; then
    echo "[uv] 检测到 uv，使用隔离环境启动..."
    exec uv run python -m pa_agent.main "$@"
elif command -v python3 >/dev/null 2>&1; then
    echo "[python3] 使用系统 python3 启动..."
    exec python3 run.py "$@"
else
    echo "未找到 uv 或 python3，请先安装 Python >= 3.11 或 uv。" >&2
    exit 127
fi
