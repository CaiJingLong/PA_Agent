"""Stock-code search popup.

A modal dialog with a keyword input, a live result list, and a 「填入」 button.
Runs the network query on a worker thread so the UI never freezes.

Results are filtered by the active data source so the user cannot pick a code
the current source cannot consume (e.g. HK stocks under the East Money A-share
source).  The chosen result is returned as a dict with ``code``, ``fullcode``,
``market``, ``type`` and ``name`` — callers route the right field into the
symbol combo depending on the source.
"""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from pa_agent.data.symbol_search import SymbolSearchError, search_symbols

logger = logging.getLogger(__name__)

# Markets/types supported by each data source kind.
_SOURCE_FILTERS: dict[str, set[str]] = {
    "eastmoney": {"SH", "SZ"},
    # tradingview / mt5 / eastmoney_futures / ... → no filter (accept all)
}


def _is_supported(market: str, _type: str, kind: str) -> bool:
    allowed = _SOURCE_FILTERS.get(kind)
    if allowed is None:
        return True
    return market in allowed


class _SearchWorker(QThread):
    results_ready = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, keyword: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._keyword = keyword

    def run(self) -> None:
        try:
            rows = search_symbols(self._keyword)
        except SymbolSearchError as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:
            logger.exception("symbol search worker crashed")
            self.failed.emit(f"搜索出错: {exc}")
            return
        self.results_ready.emit(rows)


class SymbolSearchDialog(QDialog):
    """Search stock codes; return the chosen row via :meth:`selected_result`."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        initial: str = "",
        data_source_kind: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("搜索股票代码")
        self.setMinimumWidth(460)
        self.setMinimumHeight(380)
        self._selected: dict[str, str] | None = None
        self._worker: _SearchWorker | None = None
        self._kind = data_source_kind or ""

        layout = QVBoxLayout(self)

        # ── 搜索输入行 ──────────────────────────────────────────────
        input_row = QHBoxLayout()
        self._input = QLineEdit(initial)
        self._input.setPlaceholderText("输入代码或名称，如 600519 / 茅台 / 700")
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._trigger_search)
        input_row.addWidget(self._input, 1)

        self._search_btn = QPushButton("搜索")
        self._search_btn.clicked.connect(self._trigger_search)
        input_row.addWidget(self._search_btn)
        layout.addLayout(input_row)

        # ── 结果列表 ────────────────────────────────────────────────
        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(self._accept_item)
        layout.addWidget(self._list, 1)

        # ── 状态行 ──────────────────────────────────────────────────
        self._status = QLabel("输入关键词后回车或点击「搜索」")
        self._status.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self._status)

        # ── 操作按钮 ────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._fill_btn = QPushButton("填入")
        self._fill_btn.setObjectName("primaryButton")
        self._fill_btn.setEnabled(False)
        self._fill_btn.clicked.connect(self._accept_current)
        btn_row.addWidget(self._fill_btn)
        self._cancel_btn = QPushButton("取消")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)
        layout.addLayout(btn_row)

        self._list.currentItemChanged.connect(self._on_item_changed)

    # ── public ──────────────────────────────────────────────────────
    def selected_result(self) -> dict[str, str] | None:
        """Return the chosen row dict (``None`` if cancelled).

        Keys: ``code``, ``fullcode``, ``name``, ``market``, ``type``.
        """
        return self._selected

    # ── internals ───────────────────────────────────────────────────
    def _on_text_changed(self, _text: str) -> None:
        self._fill_btn.setEnabled(False)

    def _trigger_search(self) -> None:
        kw = self._input.text().strip()
        if not kw:
            self._status.setText("请先输入关键词")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self._status.setText("搜索中…")
        self._list.clear()
        self._fill_btn.setEnabled(False)
        self._search_btn.setEnabled(False)
        self._worker = _SearchWorker(kw, self)
        self._worker.results_ready.connect(self._on_results)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_results(self, rows: list[Any]) -> None:
        self._search_btn.setEnabled(True)
        if not rows:
            self._status.setText("无匹配结果")
            return
        shown = 0
        skipped = 0
        for row in rows:
            market = str(row.get("market", ""))
            typ = str(row.get("type", ""))
            if not _is_supported(market, typ, self._kind):
                skipped += 1
                continue
            code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            tag = f"[{market}]" if market else ""
            typ_s = f"  ({typ})" if typ else ""
            label = f"{tag} {code}  {name}{typ_s}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._list.addItem(item)
            shown += 1
        if shown == 0:
            hint = "当前数据源不支持这些品种"
            if self._kind == "eastmoney":
                hint += "（东方财富仅支持 A 股/指数，港股/美股请切换 TradingView）"
            self._status.setText(hint)
        else:
            msg = f"共 {shown} 条可用结果，双击或选中后点「填入」"
            if skipped:
                msg += f"（已过滤 {skipped} 条当前数据源不支持的品种）"
            self._status.setText(msg)
            self._list.setCurrentRow(0)

    def _on_failed(self, msg: str) -> None:
        self._search_btn.setEnabled(True)
        self._status.setText(msg)
        self._status.setStyleSheet("color: #f85149; font-size: 11px;")

    def _on_item_changed(self, current: QListWidgetItem | None, _prev: QListWidgetItem | None) -> None:
        self._fill_btn.setEnabled(current is not None)

    def _accept_current(self) -> None:
        item = self._list.currentItem()
        if item is not None:
            self._accept_item(item)

    def _accept_item(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(row, dict):
            self._selected = row
            self.accept()

    def closeEvent(self, event: Any) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(2000)
        super().closeEvent(event)


def open_symbol_search_dialog(
    parent: QWidget | None,
    *,
    initial: str = "",
    data_source_kind: str = "",
) -> dict[str, str] | None:
    """Open the search popup; return the chosen row dict (``None`` if cancelled)."""
    dlg = SymbolSearchDialog(parent, initial=initial, data_source_kind=data_source_kind)
    dlg.exec()
    return dlg.selected_result()
