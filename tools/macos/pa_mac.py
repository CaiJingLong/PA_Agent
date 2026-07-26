#!/usr/bin/env python3
"""PA Agent macOS · MT5 桥接环境管理脚本。

仅用于在 macOS 上启用 MT5 数据源（TradingView 数据源无需此脚本）。
原理：官方 MetaTrader 5.app 自带 Wine，终端装在 Wine prefix 内；
本脚本在该 prefix 部署 Windows Python + MetaTrader5 包作为 RPyC server，
Mac 原生 Python 通过 mt5linux client 经网络调用。

子命令:
  check     环境检测：Wine、Wine Python、MetaTrader5 包、mt5linux server 端口
  install   在 Wine prefix 内部署 Windows Python + MetaTrader5 + mt5linux（一次性）
  server    启动 mt5linux RPyC server（前台，Ctrl+C 退出）
  stop      停止 mt5linux RPyC server（不影响 MT5 终端）
  gui       启动 PA Agent GUI（使用项目 .venv）
  status    打印 server / 终端 / venv 状态

用法:
  uv run python tools/macos/pa_mac.py <subcommand>
  .venv/bin/python tools/macos/pa_mac.py <subcommand>
  python3 tools/macos/pa_mac.py            # 交互式菜单（系统 python3 亦可）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

# ── 路径常量 ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
VENV = PROJECT_ROOT / ".venv"
VENV_PY = VENV / "bin" / "python"

HOME = Path.home()
MT5_APP = Path("/Applications/MetaTrader 5.app")
WINE = MT5_APP / "Contents" / "SharedSupport" / "wine" / "bin" / "wine"
WINEPREFIX = HOME / "Library" / "Application Support" / "net.metaquotes.wine.metatrader5"
WINE_PY = WINEPREFIX / "drive_c" / "Python312" / "python.exe"
TERMINAL_EXE_WIN = r"C:\Program Files\MetaTrader 5\terminal64.exe"

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 18812

EMBED_URL = "https://www.python.org/ftp/python/3.12.7/python-3.12.7-embed-amd64.zip"
GETPIP_URL = "https://bootstrap.pypa.io/get-pip.py"

# ── 颜色 ──────────────────────────────────────────────────────────────────
if sys.stdout.isatty():
    C_RED = "\033[31m"; C_GREEN = "\033[32m"; C_YELLOW = "\033[33m"
    C_BLUE = "\033[34m"; C_RESET = "\033[0m"
else:
    C_RED = C_GREEN = C_YELLOW = C_BLUE = C_RESET = ""


def log(msg: str = "") -> None: print(msg)
def ok(msg: str) -> None: print(f"{C_GREEN}✓{C_RESET} {msg}")
def warn(msg: str) -> None: print(f"{C_YELLOW}!{C_RESET} {msg}")
def err(msg: str) -> None: print(f"{C_RED}✗{C_RESET} {msg}", file=sys.stderr)
def info(msg: str) -> None: print(f"{C_BLUE}→{C_RESET} {msg}")


# ── 工具函数 ──────────────────────────────────────────────────────────────
def run(cmd: list[str], timeout: int = 60, capture: bool = False,
        check: bool = False, env: dict | None = None) -> subprocess.CompletedProcess | None:
    """运行命令，超时返回 None。"""
    e = os.environ.copy()
    e["WINEPREFIX"] = str(WINEPREFIX)
    if env:
        e.update(env)
    try:
        return subprocess.run(
            cmd, timeout=timeout, capture_output=capture, text=True,
            check=check, env=e,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def wine_run(args: list[str], timeout: int = 60, capture: bool = False) -> subprocess.CompletedProcess | None:
    """运行 Wine 命令（自动加 WINEPREFIX）。"""
    return run([str(WINE), *args], timeout=timeout, capture=capture)


def port_listening(port: int) -> bool:
    """检测端口是否在监听。"""
    try:
        r = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        return bool(r.stdout.strip())
    except Exception:
        return False


def pgrep(pattern: str) -> bool:
    """检测进程是否在跑。"""
    try:
        r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# ── 检测函数 ──────────────────────────────────────────────────────────────
def check_mt5_app() -> bool:
    if MT5_APP.is_dir(): ok(f"MetaTrader 5.app: {MT5_APP}"); return True
    err(f"MetaTrader 5.app 未安装: {MT5_APP}"); return False


def check_wine() -> bool:
    if WINE.exists() and os.access(WINE, os.X_OK):
        r = wine_run(["--version"], timeout=10, capture=True)
        ver = r.stdout.strip() if r and r.stdout else "（启动慢，跳过版本）"
        ok(f"Wine: {ver}"); return True
    err(f"Wine 不可用: {WINE}"); return False


def check_terminal_running() -> bool:
    if pgrep("terminal64.exe"): ok("MT5 终端进程运行中"); return True
    warn("MT5 终端未运行——请打开 MetaTrader 5.app 并登录"); return False


def check_wine_prefix() -> bool:
    if (WINEPREFIX / "drive_c" / "Program Files" / "MetaTrader 5").is_dir():
        ok(f"Wine prefix: {WINEPREFIX}"); return True
    err(f"Wine prefix 不存在或未装 MT5: {WINEPREFIX}"); return False


def check_wine_python() -> bool:
    if WINE_PY.is_file(): ok(f"Wine Python: {WINE_PY}"); return True
    warn(f"Wine Python 未部署（运行: {sys.argv[0]} install）"); return False


def check_wine_pkgs() -> bool:
    if not WINE_PY.is_file(): return False
    code = (
        "import importlib.util as u\n"
        "for m in ('MetaTrader5','mt5linux','rpyc','win32api'):\n"
        "    print(m, 'OK' if u.find_spec(m) else 'MISSING')\n"
    )
    r = wine_run([str(WINE_PY), "-c", code], timeout=30, capture=True)
    if r is None or r.returncode != 0:
        err("无法检查 Wine Python 包（超时或 Wine 错误）"); return False
    # Wine Python 输出 \r\n，去 \r
    lines = [ln.replace("\r", "") for ln in r.stdout.splitlines() if ln.strip()]
    lines = [ln for ln in lines if not ln.startswith(("fixme", "err:", "wine:"))]
    all_ok = True
    for ln in lines:
        parts = ln.split()
        if len(parts) != 2: continue
        mod, status = parts
        if status == "OK": ok(f"Wine Python 包: {mod}")
        else: err(f"Wine Python 包缺失: {mod}"); all_ok = False
    return all_ok


def check_venv() -> bool:
    if VENV_PY.exists() and os.access(VENV_PY, os.X_OK):
        ok(f"项目 venv: {VENV}"); return True
    warn(f"项目 venv 未创建（运行: {sys.argv[0]} install）"); return False


def check_venv_mt5linux() -> bool:
    if not VENV_PY.exists(): return False
    r = run([str(VENV_PY), "-c", "import mt5linux"], timeout=10, capture=True)
    if r and r.returncode == 0: ok("venv 包: mt5linux"); return True
    err(f"venv 缺 mt5linux（运行: cd {PROJECT_ROOT} && uv pip install -e .）"); return False


def check_server_port() -> bool:
    if port_listening(SERVER_PORT):
        ok(f"mt5linux server 监听 {SERVER_HOST}:{SERVER_PORT}"); return True
    warn(f"mt5linux server 未启动（运行: {sys.argv[0]} server）"); return False


# ── 子命令 ────────────────────────────────────────────────────────────────
def cmd_check() -> int:
    log("=== PA Agent macOS 环境检测 ===")
    checks = [
        check_mt5_app, check_wine, check_wine_prefix, check_wine_python,
        check_wine_pkgs, check_terminal_running, check_venv,
        check_venv_mt5linux, check_server_port,
    ]
    rc = 0
    for fn in checks:
        if not fn(): rc = 1
    log()
    if rc == 0: ok("环境就绪，可使用 MT5 数据源")
    else: warn("环境不完整——MT5 数据源不可用，但 TradingView 仍可用（无需 server）")
    return rc


def cmd_install() -> int:
    log("=== 在 Wine prefix 内部署 Windows Python + 桥接依赖 ===")
    if not (check_mt5_app() and check_wine() and check_wine_prefix()):
        return 1

    # 步骤 1：embeddable Python
    if WINE_PY.is_file():
        ok(f"Wine Python 已存在: {WINE_PY}")
    else:
        info("下载 Python 3.12 embeddable (amd64)...")
        tmp = Path("/tmp/pa_mt5_install")
        tmp.mkdir(parents=True, exist_ok=True)
        zip_path = tmp / "py312-embed.zip"
        try:
            urllib.request.urlretrieve(EMBED_URL, zip_path)
        except Exception as e:
            err(f"下载失败: {e}"); return 1
        extract_dir = tmp / "py312-embed"
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        dest = WINEPREFIX / "drive_c" / "Python312"
        if dest.exists(): shutil.rmtree(dest)
        shutil.copytree(extract_dir, dest)
        # 启用 site-packages
        pth = dest / "python312._pth"
        if pth.is_file():
            txt = pth.read_text().replace("#import site", "import site")
            pth.write_text(txt)
        shutil.rmtree(tmp, ignore_errors=True)
        ok("Wine Python 部署完成")

    # 步骤 2：pip
    info("检查 pip...")
    r = wine_run([str(WINE_PY), "-m", "pip", "--version"], timeout=30, capture=True)
    if r and r.returncode == 0:
        ok("pip 已安装")
    else:
        info("安装 pip...")
        getpip = Path("/tmp/pa_get_pip.py")
        try:
            urllib.request.urlretrieve(GETPIP_URL, getpip)
        except Exception as e:
            err(f"下载 get-pip.py 失败: {e}"); return 1
        r = wine_run([str(WINE_PY), str(getpip)], timeout=120, capture=True)
        getpip.unlink(missing_ok=True)
        if r is None or r.returncode != 0:
            err("pip 安装失败"); return 1
        ok("pip 安装完成")

    # 步骤 3：桥接依赖
    info("安装 MetaTrader5 + mt5linux + rpyc + pywin32 到 Wine Python...")
    r = wine_run(
        [str(WINE_PY), "-m", "pip", "install", "--quiet",
         "MetaTrader5", "mt5linux", "rpyc", "pywin32"],
        timeout=180, capture=True,
    )
    if r is None or r.returncode != 0:
        err("桥接依赖安装失败"); return 1
    ok("桥接依赖安装完成")

    # 步骤 4：验证连接
    if check_terminal_running():
        info("验证 MetaTrader5 能否连到终端...")
        code = (
            f"import MetaTrader5 as mt5\n"
            f"path = r'{TERMINAL_EXE_WIN}'\n"
            f"if mt5.initialize(path):\n"
            f"    info = mt5.terminal_info()\n"
            f"    print('OK:', info.name, 'build', info.build)\n"
            f"    mt5.shutdown()\n"
            f"else:\n"
            f"    print('FAIL:', mt5.last_error())\n"
            f"    raise SystemExit(1)\n"
        )
        r = wine_run([str(WINE_PY), "-c", code], timeout=30, capture=True)
        if r and "OK:" in (r.stdout or ""):
            ok("MT5 连接验证通过")
        else:
            warn("MT5 连接验证失败——终端可能未登录，稍后再试")
    else:
        warn(f"终端未运行，跳过连接验证（启动终端后可重跑 {sys.argv[0]} check）")

    # 步骤 5：项目 venv
    if not VENV_PY.exists():
        info("创建项目 venv...")
        r = run(["uv", "venv", "--python", "3.12", str(VENV)],
                timeout=60, capture=True, cwd=str(PROJECT_ROOT))
        if r is None or r.returncode != 0:
            err("uv venv 创建失败"); return 1
    info("安装项目依赖到 venv...")
    r = run(["uv", "pip", "install", "-e", "."],
            timeout=300, capture=True, cwd=str(PROJECT_ROOT))
    if r is None or r.returncode != 0:
        err("项目依赖安装失败"); return 1
    ok("项目 venv 就绪")

    log()
    ok(f"安装完成。下一步: {sys.argv[0]} server（另开终端），然后 {sys.argv[0]} gui")
    return 0


def cmd_server() -> int:
    if not check_wine_python(): return 1
    if port_listening(SERVER_PORT):
        warn(f"server 已在监听 {SERVER_PORT}，无需重复启动"); return 0
    info("启动 mt5linux RPyC server（前台，Ctrl+C 退出）...")
    env = os.environ.copy()
    env["WINEPREFIX"] = str(WINEPREFIX)
    try:
        subprocess.run([str(WINE), str(WINE_PY), "-m", "mt5linux",
                        "--host", SERVER_HOST, "--port", str(SERVER_PORT)], env=env)
    except KeyboardInterrupt:
        log("\nserver 已停止")
    return 0


def cmd_stop() -> int:
    stopped = False
    # 1) 杀监听 SERVER_PORT 的进程（最精确）
    try:
        r = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{SERVER_PORT}", "-sTCP:LISTEN", "-t"],
            capture_output=True, text=True, timeout=5,
        )
        for pid in r.stdout.strip().split():
            if pid:
                info(f"停止 server (pid={pid})...")
                subprocess.run(["kill", pid], timeout=5)
                stopped = True
    except Exception:
        pass
    # 2) 兜底：杀命令行精确匹配 "python.exe" + "mt5linux" 的进程
    #    不用 pkill -f mt5linux（太宽，会匹配 Wine 进程链连带杀终端）
    try:
        r = subprocess.run(
            ["pgrep", "-f", r"python\.exe.*-m.*mt5linux"],
            capture_output=True, text=True, timeout=5,
        )
        for pid in r.stdout.strip().split():
            if pid:
                info(f"停止 mt5linux 进程 (pid={pid})...")
                subprocess.run(["kill", pid], timeout=5)
                stopped = True
    except Exception:
        pass
    if stopped: ok("server 已停止")
    else: warn("未发现运行中的 server")
    return 0


def cmd_gui() -> int:
    if not VENV_PY.exists():
        err(f"项目 venv 不存在: {VENV}")
        err(f"运行: {sys.argv[0]} install")
        return 1
    info("启动 PA Agent GUI...")
    os.chdir(PROJECT_ROOT)
    os.execv(str(VENV_PY), [str(VENV_PY), "run.py"])

def cmd_status() -> int:
    log("=== PA Agent macOS 状态 ===")
    for fn in [check_mt5_app, check_wine_prefix, check_wine_python, check_wine_pkgs,
               check_venv, check_venv_mt5linux, check_terminal_running, check_server_port]:
        fn()
    return 0


# ── 交互式菜单 ────────────────────────────────────────────────────────────
def menu() -> int:
    try:
        while True:
            print("\033[2J\033[H", end="")  # clear
            log("═══════════════════════════════════════════════════════════")
            log("  PA Agent · macOS · MT5 桥接环境管理")
            log("═══════════════════════════════════════════════════════════")
            log("  （仅 MT5 数据源需要；TradingView 无需此脚本）")
            log("  1) 环境检测          (check)")
            log("  2) 一次性安装        (install)")
            log("  3) 启动 MT5 server   (server)  ← 前台运行，需另开窗口")
            log("  4) 停止 MT5 server   (stop)")
            log("  5) 启动 PA Agent     (gui)")
            log("  6) 查看状态          (status)")
            log("  q) 退出")
            log("═══════════════════════════════════════════════════════════")
            choice = input("请选择: ").strip().lower()
            cmds = {
                "1": cmd_check, "2": cmd_install, "3": cmd_server,
                "4": cmd_stop, "5": cmd_gui, "6": cmd_status,
            }
            if choice in ("q", "quit", "exit"):
                log("再见"); return 0
            fn = cmds.get(choice)
            if fn is None:
                err(f"无效选择: {choice}"); time.sleep(1); continue
            rc = fn()
            if fn in (cmd_server, cmd_gui):  # exec 接管，不会回来
                return rc
            input("\n按回车继续...")
    except KeyboardInterrupt:
        log("\n再见"); return 0


def usage() -> None:
    print(__doc__)


# ── 入口 ──────────────────────────────────────────────────────────────────
def main() -> int:
    if len(sys.argv) < 2:
        return menu()
    cmd = sys.argv[1]
    if cmd in ("-h", "--help", "help"):
        usage(); return 0
    cmds = {
        "check": cmd_check, "install": cmd_install, "server": cmd_server,
        "stop": cmd_stop, "gui": cmd_gui, "status": cmd_status,
    }
    fn = cmds.get(cmd)
    if fn is None:
        err(f"未知子命令: {cmd}"); usage(); return 1
    return fn()


if __name__ == "__main__":
    sys.exit(main())
