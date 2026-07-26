# pa_mac.command — PA Agent macOS · MT5 桥接环境管理（双击入口）
#
# 仅用于启用 MT5 数据源。双击调用 tools/macos/pa_mac.py 的交互式菜单。
# TradingView 数据源无需此脚本。
# 也可终端运行: ./tools/macos/pa_mac.command
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/pa_mac.py"

# 优先用项目 .venv 的 python（依赖更全），回退系统 python3
VENV_PY="$SCRIPT_DIR/../../.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
    exec "$VENV_PY" "$PY"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 "$PY"
else
    echo "✗ 未找到 python3，请先安装 Python 3.11+"
    read -n 1 -s -r -p "按任意键关闭..."
    exit 1
fi
