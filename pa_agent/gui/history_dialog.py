"""Analysis history dialog — lists past analyses, click to restore query info.

Each row shows timestamp, symbol, timeframe, model, duration, status.
Selecting a row and clicking「复原」loads the linked pending JSON record,
restores the symbol/timeframe selectors, and pushes the K-line frame into
the chart so the user can re-examine or re-run the analysis.
"""
from __future__ import annotations

import logging

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from pa_agent.records.history_reader import HistoryEntry, list_history_entries

logger = logging.getLogger(__name__)


class HistoryDialog(QDialog):
    """Modal dialog showing analysis history with restore-on-click."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("分析历史记录")
        self.setMinimumSize(720, 520)
        self.resize(820, 600)
        self._selected: HistoryEntry | None = None

        layout = QVBoxLayout(self)

        # ── Top: split list (left) + detail (right) ──────────────────────
        split_layout = QHBoxLayout()

        # Left: entry list
        list_col = QVBoxLayout()
        list_col.addWidget(QLabel("历史记录(最新在前)"))
        self._list = QListWidget()
        self._list.setMinimumWidth(320)
        self._list.currentItemChanged.connect(self._on_item_changed)
        self._list.itemDoubleClicked.connect(self._accept_current)
        list_col.addWidget(self._list, 1)
        split_layout.addLayout(list_col, 2)

        # Right: detail view
        detail_col = QVBoxLayout()
        detail_col.addWidget(QLabel("详情"))
        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMinimumWidth(360)
        detail_col.addWidget(self._detail, 1)
        split_layout.addLayout(detail_col, 3)

        layout.addLayout(split_layout, 1)

        # ── Status row ───────────────────────────────────────────────────
        self._status = QLabel("加载中…")
        self._status.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self._status)

        # ── Buttons ──────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.clicked.connect(self._load_entries)
        btn_row.addWidget(self._refresh_btn)
        btn_row.addStretch()

        self._restore_btn = QPushButton("复原查询信息")
        self._restore_btn.setObjectName("primaryButton")
        self._restore_btn.setEnabled(False)
        self._restore_btn.clicked.connect(self._accept_current)
        btn_row.addWidget(self._restore_btn)

        self._close_btn = QPushButton("关闭")
        self._close_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._close_btn)
        layout.addLayout(btn_row)

        self._entries: list[HistoryEntry] = []
        self._load_entries()

    # ── public ──────────────────────────────────────────────────────────
    def selected_entry(self) -> HistoryEntry | None:
        """Return the entry the user chose to restore (``None`` if cancelled)."""
        return self._selected

    # ── internals ───────────────────────────────────────────────────────
    def _load_entries(self) -> None:
        """Reload entries from disk and populate the list."""
        self._list.clear()
        self._detail.clear()
        self._restore_btn.setEnabled(False)
        self._entries = list_history_entries()
        if not self._entries:
            self._status.setText("暂无历史记录(完成一次分析后会出现)")
            return
        for entry in self._entries:
            label = self._format_list_label(entry)
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._list.addItem(item)
        self._status.setText(f"共 {len(self._entries)} 条记录")
        self._list.setCurrentRow(0)

    @staticmethod
    def _format_list_label(entry: HistoryEntry) -> str:
        status_tag = "✅" if entry.is_success else "❌"
        return (
            f"{status_tag} {entry.timestamp}  "
            f"{entry.symbol} {entry.timeframe}  "
            f"{entry.bar_count}K  "
            f"{entry.duration_label}"
        )

    def _on_item_changed(
        self, current: QListWidgetItem | None, _prev: QListWidgetItem | None
    ) -> None:
        if current is None:
            self._detail.clear()
            self._restore_btn.setEnabled(False)
            return
        entry = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, HistoryEntry):
            self._detail.setMarkdown(self._render_detail(entry))
            can_restore = bool(entry.record_file)
            self._restore_btn.setEnabled(can_restore)

    @staticmethod
    def _render_detail(entry: HistoryEntry) -> str:
        thinking = "开" if entry.thinking else "关"
        effort = entry.reasoning_effort or "—"
        strategy = ", ".join(entry.strategy_files) if entry.strategy_files else "—"
        status_label = "✅ 成功" if entry.is_success else f"❌ {entry.status}"
        return f"""### {entry.display_title}

| 字段 | 值 |
|---|---|
| 股票代码 | `{entry.symbol}` |
| 周期 | `{entry.timeframe}` |
| K线数量 | {entry.bar_count} |
| 模型 | `{entry.model}` |
| 思考 | {thinking} · effort={effort} |
| 决策姿态 | {entry.decision_stance} |
| Stage1 用时 | {entry.stage1_ms / 1000:.1f}s |
| Stage2 用时 | {entry.stage2_ms / 1000:.1f}s |
| 总用时 | **{entry.duration_label}** |
| Token | prompt={entry.prompt_tokens}, completion={entry.completion_tokens}, total={entry.total_tokens} |
| 策略文件 | {strategy} |
| 记录文件 | `{entry.record_file}` |
| 结果 | {status_label} |
"""

    def _accept_current(self) -> None:
        item = self._list.currentItem()
        if item is None:
            return
        entry = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(entry, HistoryEntry) and entry.record_file:
            self._selected = entry
            self.accept()


def open_history_dialog(parent: QWidget | None) -> HistoryEntry | None:
    """Open the history dialog; return the chosen entry (``None`` if cancelled)."""
    dlg = HistoryDialog(parent)
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.selected_entry()
    return None
