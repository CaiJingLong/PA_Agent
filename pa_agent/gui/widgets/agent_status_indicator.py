"""Prominent agent execution-status indicator with a pulsing dot.

Placed next to the 「提交分析」 button so the user sees feedback right where
they clicked.  States:

    idle       空闲           gray dot, static
    fetching   获取K线…       blue dot, pulsing
    preparing  准备分析…      blue dot, pulsing
    stage1     阶段一分析中…  blue dot, pulsing
    stage1_retry 阶段一重试   amber dot, pulsing
    stage2     阶段二分析中…  blue dot, pulsing
    stage2_retry 阶段二重试   amber dot, pulsing
    done       已完成         green dot, static
    error      失败           red dot, static
    cancelled  已取消         gray dot, static
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QWidget

_STATE_STYLE: dict[str, dict[str, str]] = {
    "idle":          {"color": "#6e7681", "text": "空闲",          "pulse": "0"},
    "fetching":      {"color": "#38bdf8", "text": "获取K线…",      "pulse": "1"},
    "preparing":     {"color": "#38bdf8", "text": "准备分析…",     "pulse": "1"},
    "stage1":        {"color": "#38bdf8", "text": "阶段一分析中…", "pulse": "1"},
    "stage1_retry":  {"color": "#f0b429", "text": "阶段一重试…",   "pulse": "1"},
    "stage2":        {"color": "#38bdf8", "text": "阶段二分析中…", "pulse": "1"},
    "stage2_retry":  {"color": "#f0b429", "text": "阶段二重试…",   "pulse": "1"},
    "done":          {"color": "#22c55e", "text": "已完成",        "pulse": "0"},
    "error":         {"color": "#ef4444", "text": "失败",          "pulse": "0"},
    "cancelled":     {"color": "#6e7681", "text": "已取消",        "pulse": "0"},
}

_PULSE_MS = 650


class AgentStatusIndicator(QWidget):
    """Compact status pill: pulsing dot + state label."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = "idle"
        self._pulse_on = True

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(6)

        self._dot = QLabel("●")
        self._dot.setFixedWidth(14)
        self._dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._dot)

        self._label = QLabel("空闲")
        self._label.setStyleSheet("font-size: 12px; font-weight: 600;")
        layout.addWidget(self._label)

        self._timer = QTimer(self)
        self._timer.setInterval(_PULSE_MS)
        self._timer.timeout.connect(self._tick)
        self._apply_state()

    def set_state(self, state: str) -> None:
        """Set the indicator state. Unknown states fall back to idle."""
        if state not in _STATE_STYLE:
            state = "idle"
        if state == self._state:
            return
        self._state = state
        self._apply_state()

    def state(self) -> str:
        return self._state

    def is_busy(self) -> bool:
        """True for any in-progress state (dot is pulsing)."""
        return _STATE_STYLE.get(self._state, {}).get("pulse") == "1"

    def _apply_state(self) -> None:
        cfg = _STATE_STYLE[self._state]
        color = cfg["color"]
        self._label.setText(cfg["text"])
        self._label.setStyleSheet(
            f"font-size: 12px; font-weight: 600; color: {color};"
        )
        if cfg["pulse"] == "1":
            self._pulse_on = True
            self._dot.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: bold;"
            )
            self._timer.start()
        else:
            self._pulse_on = False
            self._timer.stop()
            self._dot.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: bold;"
            )

    def _tick(self) -> None:
        """Toggle dot opacity for the pulsing effect."""
        self._pulse_on = not self._pulse_on
        cfg = _STATE_STYLE[self._state]
        color = cfg["color"]
        if self._pulse_on:
            self._dot.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: bold;"
            )
        else:
            # Dim toward background — visible but clearly "half strength"
            self._dot.setStyleSheet(
                f"color: {color}; font-size: 13px; font-weight: bold; opacity: 0.35;"
            )
