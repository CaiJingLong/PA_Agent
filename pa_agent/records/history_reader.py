"""Parse the analysis history Markdown file into structured entries.

Each entry in ``records/history/analysis_history.md`` starts with ``## `` and
contains a fenced ```` ```meta ```` JSON block. This reader extracts the
metadata for display in the history dialog.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from pa_agent.config.paths import HISTORY_FILE_PATH

logger = logging.getLogger(__name__)

# Entry header: ## 2026-07-26 18:07:49 · 002371 · 15m
_ENTRY_HEADER_RE = re.compile(r"^##\s+.+$", re.MULTILINE)
_META_BLOCK_RE = re.compile(r"```meta\s*\n(.*?)\n```", re.DOTALL)


@dataclass(frozen=True)
class HistoryEntry:
    """One parsed history entry."""

    timestamp: str
    timestamp_ms: int
    symbol: str
    timeframe: str
    bar_count: int
    model: str
    thinking: bool
    reasoning_effort: str
    decision_stance: str
    stage1_ms: float
    stage2_ms: float
    total_ms: float
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    status: str
    record_file: str
    strategy_files: tuple[str, ...]
    # Raw markdown body (header + everything until the next ``---``)
    raw_markdown: str

    @property
    def is_success(self) -> bool:
        return self.status == "success"

    @property
    def duration_label(self) -> str:
        if self.total_ms <= 0:
            return "—"
        return f"{self.total_ms / 1000:.1f}s"

    @property
    def display_title(self) -> str:
        return f"{self.timestamp} · {self.symbol} · {self.timeframe}"


def list_history_entries(path: Path | None = None) -> list[HistoryEntry]:
    """Return all history entries, newest first.

    Returns an empty list if the file does not exist or is unreadable.
    """
    p = path or HISTORY_FILE_PATH
    if not p.exists():
        return []
    try:
        text = p.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("history_reader: cannot read %s: %s", p, exc)
        return []

    entries: list[HistoryEntry] = []
    # Split on entry headers (``## ``). Each entry runs from one header to the
    # next (or to EOF). The ``---`` separators are cosmetic.
    parts = re.split(r"(?=^##\s+.+$)", text, flags=re.MULTILINE)
    for part in parts:
        chunk = part.strip()
        if not chunk.startswith("## "):
            continue
        entry = _parse_chunk(chunk)
        if entry is not None:
            entries.append(entry)

    # File is stored newest-first; keep that order.
    return entries


def _parse_chunk(chunk: str) -> HistoryEntry | None:
    if not chunk or not chunk.startswith("## "):
        return None

    meta_match = _META_BLOCK_RE.search(chunk)
    if meta_match is None:
        return None

    try:
        meta = json.loads(meta_match.group(1))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("history_reader: bad meta JSON: %s", exc)
        return None

    if not isinstance(meta, dict):
        return None

    try:
        return HistoryEntry(
            timestamp=str(meta.get("timestamp", "")),
            timestamp_ms=int(meta.get("timestamp_ms", 0) or 0),
            symbol=str(meta.get("symbol", "")),
            timeframe=str(meta.get("timeframe", "")),
            bar_count=int(meta.get("bar_count", 0) or 0),
            model=str(meta.get("model", "")),
            thinking=bool(meta.get("thinking", False)),
            reasoning_effort=str(meta.get("reasoning_effort", "") or ""),
            decision_stance=str(meta.get("decision_stance", "") or ""),
            stage1_ms=float(meta.get("stage1_ms", 0) or 0),
            stage2_ms=float(meta.get("stage2_ms", 0) or 0),
            total_ms=float(meta.get("total_ms", 0) or 0),
            prompt_tokens=int(meta.get("prompt_tokens", 0) or 0),
            completion_tokens=int(meta.get("completion_tokens", 0) or 0),
            total_tokens=int(meta.get("total_tokens", 0) or 0),
            status=str(meta.get("status", "unknown") or "unknown"),
            record_file=str(meta.get("record_file", "") or ""),
            strategy_files=tuple(meta.get("strategy_files", []) or []),
            raw_markdown=chunk,
        )
    except (TypeError, ValueError) as exc:
        logger.debug("history_reader: bad meta fields: %s", exc)
        return None
