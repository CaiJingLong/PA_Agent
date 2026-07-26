"""macOS / Linux adapter for MetaTrader 5 via the ``mt5linux`` bridge.

The official ``MetaTrader5`` PyPI package ships Windows-only wheels and talks
to the MT5 terminal through Windows IPC. On macOS / Linux we use ``mt5linux``
instead: a Windows Python running under Wine hosts an RPyC server that wraps
the real ``MetaTrader5`` package, and the native Python talks to that server
over a socket.

Strategy — zero-touch on the parent class:
    ``MT5Source`` (pa_agent/data/mt5.py) does ``import MetaTrader5 as mt5``
    in every method. We install the ``mt5linux`` proxy into
    ``sys.modules['MetaTrader5']`` inside :meth:`connect`, so the parent's
    imports transparently resolve to the proxy. The RPyC proxy also forwards
    module-level constants (``TIMEFRAME_*``), so the parent's
    ``getattr(mt5, "TIMEFRAME_M1")`` works unchanged.

The only real divergence from the parent is :meth:`connect`: the official
Mac MT5 build lives inside a Wine prefix at a non-default path, so
``mt5.initialize()`` (no args) fails with "MetaTrader 5 x64 not found". We
must pass the terminal exe path explicitly.

Prerequisites for end users (documented separately):
    - Wine (the official MetaTrader 5.app bundles its own Wine on macOS)
    - Windows Python installed into the same Wine prefix as the MT5 terminal
    - ``MetaTrader5`` + ``mt5linux`` installed into that Windows Python
    - MT5 terminal running under Wine, logged in
    - ``wine python -m mt5linux`` started as the RPyC server on
      ``host:port`` (default ``127.0.0.1:18812``)
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

from pa_agent.data.base import DataSourceTransientError
from pa_agent.data.mt5 import MT5Source

logger = logging.getLogger(__name__)

# Default RPyC server endpoint used by ``mt5linux``.
_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 18812

# Default terminal path *inside the Wine prefix's C: drive*. The official
# MetaTrader 5.app on macOS installs the terminal here.
_DEFAULT_TERMINAL_PATH = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# Environment variable overrides.
_ENV_TERMINAL_PATH = "PA_MT5_TERMINAL_PATH"
_ENV_HOST = "PA_MT5LINUX_HOST"
_ENV_PORT = "PA_MT5LINUX_PORT"


def _default_wine_prefix() -> Path:
    """The Wine prefix MetaQuotes' official macOS MT5.app uses."""
    return Path.home() / "Library" / "Application Support" / "net.metaquotes.wine.metatrader5"


def _resolve_terminal_path(explicit: str | None) -> str:
    """Resolve the terminal exe path to pass to ``mt5.initialize``.

    Priority: explicit ctor arg > ``$PA_MT5_TERMINAL_PATH`` > default
    Wine-relative path. The Wine-relative path is a Windows-style path
    (``C:\\...``) understood by the MT5 package inside the Wine environment.
    """
    if explicit:
        return explicit
    env = os.environ.get(_ENV_TERMINAL_PATH)
    if env:
        return env
    return _DEFAULT_TERMINAL_PATH


class MT5LinuxSource(MT5Source):
    """MT5 data source for macOS / Linux via the ``mt5linux`` RPyC bridge.

    Behaves identically to :class:`MT5Source` from the caller's perspective.
    Configuration (all optional, via ctor args or env vars):

    - ``terminal_path`` / ``$PA_MT5_TERMINAL_PATH`` — path to
      ``terminal64.exe`` inside the Wine prefix (Windows-style ``C:\\...``).
      Defaults to the official Mac MT5.app location.
    - ``host`` / ``$PA_MT5LINUX_HOST`` — RPyC server host (default
      ``127.0.0.1``).
    - ``port`` / ``$PA_MT5LINUX_PORT`` — RPyC server port (default ``18812``).
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        terminal_path: str | None = None,
    ) -> None:
        super().__init__()
        self._host = host or os.environ.get(_ENV_HOST, _DEFAULT_HOST)
        self._port = port or int(os.environ.get(_ENV_PORT, str(_DEFAULT_PORT)))
        self._terminal_path = _resolve_terminal_path(terminal_path)
        # Holds the underlying mt5linux connection so it stays alive for the
        # lifetime of this source (otherwise RPyC GC closes the socket).
        self._mt5linux_conn: Any = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def connect(self) -> None:
        """Connect to the ``mt5linux`` RPyC server and through it to MT5.

        Unlike the parent's :meth:`MT5Source.connect`, this must pass the
        terminal exe path explicitly: the official Mac MT5.app installs the
        terminal into a Wine prefix at a non-default location, so
        ``mt5.initialize()`` (no args) cannot auto-discover it.
        """
        try:
            from mt5linux import MetaTrader5 as _LinuxMT5  # type: ignore[import]
        except ImportError as exc:
            raise DataSourceTransientError(
                "mt5linux package not installed — run: pip install mt5linux. "
                "Also requires a running `wine python -m mt5linux` RPyC server "
                "that wraps the real MetaTrader5 inside the Wine prefix."
            ) from exc

        proxy = _LinuxMT5(host=self._host, port=self._port)
        # Expose the proxy under the official module name so the parent class's
        # `import MetaTrader5 as mt5` picks it up transparently. The proxy
        # forwards method calls AND module-level constants (TIMEFRAME_*), so
        # the parent's getattr(mt5, "TIMEFRAME_M1") works unchanged.
        sys.modules["MetaTrader5"] = proxy  # type: ignore[assignment]
        self._mt5linux_conn = proxy

        try:
            import MetaTrader5 as mt5  # type: ignore[import]  # injected proxy
        except ImportError as exc:
            self._teardown_proxy()
            raise DataSourceTransientError(
                "MetaTrader5 proxy unavailable after mt5linux connect"
            ) from exc

        if not mt5.initialize(self._terminal_path):
            error = mt5.last_error()
            self._teardown_proxy()
            raise DataSourceTransientError(
                f"MT5 initialize() failed via mt5linux: {error}. "
                f"Check terminal path={self._terminal_path!r}, that the MT5 "
                f"terminal is running under Wine, and that the RPyC server "
                f"is reachable at {self._host}:{self._port}."
            )

        info = mt5.terminal_info()
        if info is not None:
            logger.info(
                "MT5 (via mt5linux) connected: terminal=%s, build=%s, connected=%s",
                info.name, info.build, info.connected,
            )
        else:
            logger.info("MT5 (via mt5linux) connected (terminal info unavailable)")
        self._connected = True

    def disconnect(self) -> None:
        try:
            super().disconnect()
        finally:
            self._teardown_proxy()

    def _teardown_proxy(self) -> None:
        """Remove the proxy from sys.modules so a later Windows run is clean."""
        self._mt5linux_conn = None
        sys.modules.pop("MetaTrader5", None)
