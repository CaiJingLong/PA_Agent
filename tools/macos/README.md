# PA Agent macOS · MT5 桥接环境管理

`tools/macos/` 提供 macOS 下启用 **MT5 数据源**的桥接环境管理脚本。
TradingView 数据源无需此脚本。

## 文件

| 文件 | 作用 |
|---|---|
| `pa_mac.py` | 主脚本，提供 check/install/server/stop/gui/status 子命令 + 交互式菜单 |
| `pa_mac.command` | macOS 双击入口，调用 `pa_mac.py` 的交互式菜单 |

## 背景

官方 `MetaTrader5` PyPI 包只发 Windows wheel，macOS 通过 `mt5linux` 桥接：
Wine 内跑 Windows Python + `MetaTrader5` 包作为 RPyC server，
Mac 原生 Python 作为 client 经网络（127.0.0.1:18812）调用。

官方 MetaTrader 5.app 自带 Wine（`Contents/SharedSupport/wine/`），
终端装在 Wine prefix 内（`~/Library/Application Support/net.metaquotes.wine.metatrader5/`）。
本脚本在该 prefix 内部署 Windows Python + 桥接依赖。

## 用法

### 双击运行

双击 `pa_mac.command`，出现菜单：

```
1) 环境检测          (check)
2) 一次性安装        (install)
3) 启动 MT5 server   (server)  ← 前台运行，需另开窗口
4) 停止 MT5 server   (stop)
5) 启动 PA Agent     (gui)
6) 查看状态          (status)
q) 退出
```

### 命令行运行

优先用项目 venv（与 GUI 运行环境一致）：

```bash
# 方式 A：uv run（自动用项目 .venv，无需手动激活）
uv run python tools/macos/pa_mac.py <subcommand>

# 方式 B：直接用 .venv 的 python
.venv/bin/python tools/macos/pa_mac.py <subcommand>

# 方式 C：激活 venv 后用 python
source .venv/bin/activate
python tools/macos/pa_mac.py <subcommand>
```

> `pa_mac.py` 只用标准库，系统 `python3` 也能跑；但用项目 venv 可保证与 GUI
> 环境一致，避免 `install` 子命令创建 venv 时找不到 `uv` 等差异。

子命令：

| 子命令 | 作用 |
|---|---|
| `check` | 环境检测：Wine / Wine Python / 包 / venv / server 端口 |
| `install` | 一次性安装：Wine Python + 桥接依赖 + 项目 venv |
| `server` | 启动 mt5linux RPyC server（前台，Ctrl+C 退出） |
| `stop` | 停止 mt5linux server |
| `gui` | 启动 PA Agent GUI（使用项目 .venv） |
| `status` | 打印当前状态 |

## 首次使用流程

1. 从 https://www.metatrader5.com/en/download 安装官方 Mac 版 MetaTrader 5.app
2. 打开终端，登录券商账号
3. `uv run python tools/macos/pa_mac.py install` — 一次性部署 Wine Python + 桥接依赖 + 项目 venv
4. `uv run python tools/macos/pa_mac.py server` — 启动 RPyC server（保持窗口开着）
5. 另开终端：`uv run python tools/macos/pa_mac.py gui` — 启动 GUI，数据来源选 MT5

## 日常使用

每次使用 MT5 数据源前先启动 server（步骤 4），然后启动 GUI（步骤 5）。
不用 MT5 时 `uv run python tools/macos/pa_mac.py stop` 关闭 server 释放资源。
只用 TradingView 数据源则无需启动 server，直接启动 GUI 即可。

## 环境变量覆盖

| 变量 | 默认值 | 作用 |
|---|---|---|
| `PA_MT5_TERMINAL_PATH` | `C:\Program Files\MetaTrader 5\terminal64.exe` | terminal64.exe 的 Windows 路径 |
| `PA_MT5LINUX_HOST` | `127.0.0.1` | RPyC server host |
| `PA_MT5LINUX_PORT` | `18812` | RPyC server port |

## 故障排查

- **`check` 报 Wine Python 包缺失**：重跑 `install`
- **`server` 启动后 `check` 仍报端口未监听**：Wine 启动慢，等 5-10 秒再 check
- **GUI 里选 MT5 报连接失败**：确认 server 在跑（`status` 检查端口）、终端已登录
- **`install` 下载 Python 失败**：网络问题，可手动下载 embeddable 包放到 `/tmp/pa_mt5_install/`
