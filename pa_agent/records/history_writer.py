"""Append-only Markdown writer for analysis history.

Each completed analysis appends one entry to ``records/history/analysis_history.md``.
Entries are separated by ``---`` and carry a fenced JSON metadata block for
reliable machine parsing, followed by a human-readable summary.
"""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pa_agent.config.paths import HISTORY_DIR, HISTORY_FILE_PATH
from pa_agent.records.schema import AnalysisRecord

logger = logging.getLogger(__name__)

_META_FENCE = "```meta"


def _ms_to_local_str(ms: int) -> str:
    """Epoch ms → ``YYYY-MM-DD HH:MM:SS`` local time."""
    dt = datetime.fromtimestamp(ms / 1000, tz=UTC).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _safe_get(d: Any, *keys: str, default: Any = None) -> Any:
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
    return cur if cur is not None else default


def _fmt_duration_s(ms: float | None) -> str:
    if ms is None or ms <= 0:
        return "—"
    return f"{ms / 1000:.1f}s"


def _extract_stage_summary(record: AnalysisRecord) -> tuple[str, str]:
    """Return (stage1_summary, stage2_summary) as short human-readable text."""
    s1 = record.stage1_diagnosis or {}
    s2 = record.stage2_decision or {}

    # Stage 1
    direction = s1.get("direction", "—")
    gate = s1.get("gate_result", "—")
    bar_analysis = s1.get("bar_analysis") or {}
    always_in = bar_analysis.get("always_in", "—") if isinstance(bar_analysis, dict) else "—"
    cycle = _safe_get(s1, "cycle_position", default="—")
    s1_lines = [
        f"- 方向: {direction} · 闸门: {gate} · AlwaysIn: {always_in}",
        f"- 周期位置: {cycle}",
    ]
    detected = s1.get("detected_patterns")
    if isinstance(detected, list) and detected:
        s1_lines.append(f"- 识别形态: {', '.join(str(p) for p in detected[:4])}")
    s1_summary = "\n".join(s1_lines)

    # Stage 2
    decision = s2.get("decision") or {}
    order_type = decision.get("order_type", "—") if isinstance(decision, dict) else "—"
    order_dir = decision.get("order_direction", "—") if isinstance(decision, dict) else "—"
    entry = decision.get("entry_price", "—") if isinstance(decision, dict) else "—"
    stop = decision.get("stop_loss_price", "—") if isinstance(decision, dict) else "—"
    tp = decision.get("take_profit_price", "—") if isinstance(decision, dict) else "—"
    terminal = s2.get("terminal") or {}
    outcome = terminal.get("outcome", "—") if isinstance(terminal, dict) else "—"
    node_id = terminal.get("node_id", "—") if isinstance(terminal, dict) else "—"
    s2_lines = [
        f"- 终端节点: {node_id} → {outcome}",
        f"- 下单: {order_type} · 方向: {order_dir}",
        f"- 入场: {entry} · 止损: {stop} · 目标: {tp}",
    ]
    diag_summary = s2.get("diagnosis_summary")
    if isinstance(diag_summary, dict):
        ds_cycle = diag_summary.get("cycle_position", "—")
        ds_dir = diag_summary.get("direction", "—")
        s2_lines.append(f"- 诊断摘要: {ds_cycle} / {ds_dir}")
    s2_summary = "\n".join(s2_lines)

    return s1_summary, s2_summary


def _build_meta_dict(record: AnalysisRecord, pending_filename: str) -> dict[str, Any]:
    meta = record.meta
    s1_raw = record.stage1_response or {}
    s2_raw = record.stage2_response or {}
    s1_latency = _safe_get(s1_raw, "latency_ms", default=0) if isinstance(s1_raw, dict) else 0
    s2_latency = _safe_get(s2_raw, "latency_ms", default=0) if isinstance(s2_raw, dict) else 0
    s1_model = _safe_get(s1_raw, "model", default="") if isinstance(s1_raw, dict) else ""
    s2_model = _safe_get(s2_raw, "model", default="") if isinstance(s2_raw, dict) else ""
    model = s1_model or s2_model or _safe_get(meta.ai_provider, "model", default="")

    exc = record.exception
    status = "success"
    if exc:
        status = exc.get("type", "error") or "error"

    usage = record.usage_total or {}

    return {
        "timestamp": _ms_to_local_str(meta.timestamp_local_ms),
        "timestamp_ms": meta.timestamp_local_ms,
        "symbol": meta.symbol,
        "timeframe": meta.timeframe,
        "bar_count": meta.bar_count,
        "model": model,
        "thinking": bool(_safe_get(meta.ai_provider, "thinking", default=False)),
        "reasoning_effort": _safe_get(meta.ai_provider, "reasoning_effort", default=""),
        "decision_stance": meta.decision_stance,
        "stage1_ms": round(float(s1_latency or 0), 1),
        "stage2_ms": round(float(s2_latency or 0), 1),
        "total_ms": round(float(s1_latency or 0) + float(s2_latency or 0), 1),
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
        "status": status,
        "record_file": pending_filename,
        "strategy_files": list(record.strategy_files_used or []),
    }


def _build_markdown_entry(meta: dict[str, Any], s1_summary: str, s2_summary: str) -> str:
    title = f"## {meta['timestamp']} · {meta['symbol']} · {meta['timeframe']}"
    meta_json = json.dumps(meta, ensure_ascii=False, indent=2)

    status_label = "✅ 成功" if meta["status"] == "success" else f"❌ {meta['status']}"
    duration = _fmt_duration_s(meta.get("total_ms"))
    s1_dur = _fmt_duration_s(meta.get("stage1_ms"))
    s2_dur = _fmt_duration_s(meta.get("stage2_ms"))

    strategy = ", ".join(meta.get("strategy_files", [])) or "—"

    body = f"""{title}

{_META_FENCE}
{meta_json}
```

| 字段 | 值 |
|---|---|
| 股票代码 | {meta['symbol']} |
| 周期 | {meta['timeframe']} |
| K线数量 | {meta['bar_count']} |
| 模型 | {meta['model']} |
| 思考 | {'开' if meta['thinking'] else '关'} · effort={meta['reasoning_effort'] or '—'} |
| 决策姿态 | {meta['decision_stance']} |
| 分析用时 | {duration} (Stage1: {s1_dur} + Stage2: {s2_dur}) |
| Token用量 | prompt={meta['prompt_tokens']}, completion={meta['completion_tokens']}, total={meta['total_tokens']} |
| 策略文件 | {strategy} |
| 记录文件 | {meta['record_file']} |
| 结果 | {status_label} |

### 阶段一诊断
{s1_summary}

### 阶段二决策
{s2_summary}

---"""

    return body + "\n"


def append_history_entry(
    record: AnalysisRecord,
    pending_filename: str,
    *,
    history_path: Path | None = None,
) -> bool:
    """Append one analysis entry to the history markdown file.

    Returns True on success, False on disk error.
    """
    path = history_path or HISTORY_FILE_PATH
    try:
        HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logger.warning("history: cannot create dir %s: %s", HISTORY_DIR, exc)
        return False

    try:
        meta = _build_meta_dict(record, pending_filename)
        s1_summary, s2_summary = _extract_stage_summary(record)
        entry = _build_markdown_entry(meta, s1_summary, s2_summary)

        # Prepend new entries (newest first) so the dialog and file both read top-down.
        existing = ""
        if path.exists():
            try:
                existing = path.read_text(encoding="utf-8")
            except OSError as exc:
                logger.warning("history: cannot read existing %s: %s", path, exc)

        header = "# 分析历史记录\n\n"
        if existing.startswith(header):
            rest = existing[len(header):]
            new_content = header + entry + rest
        elif existing.strip():
            new_content = header + entry + existing
        else:
            new_content = header + entry

        path.write_text(new_content, encoding="utf-8")
        return True
    except OSError as exc:
        logger.warning("history: write failed to %s: %s", path, exc)
        return False
    except Exception as exc:
        logger.warning("history: unexpected error: %s", exc)
        return False
