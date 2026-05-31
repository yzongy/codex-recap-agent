from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .models import DailyInsight, DailyReport, SessionSummary


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def filter_sessions_for_day(sessions: Sequence[SessionSummary], target_date: str) -> List[SessionSummary]:
    wanted = []
    for session in sessions:
        dt = _parse_dt(session.updated_at or session.started_at)
        if dt and dt.date().isoformat() == target_date:
            wanted.append(session)
    return wanted


def build_daily_report(report_date: str, sessions: Sequence[SessionSummary], generated_at: str | None = None) -> DailyReport:
    sessions = sorted(sessions, key=lambda s: (s.updated_at or s.started_at or "", s.session_id), reverse=True)
    cwd_counts = Counter((s.cwd or "unknown") for s in sessions)
    thread_names = [s.thread_name for s in sessions if s.thread_name]
    function_calls = sum(s.function_calls for s in sessions)
    tool_errors = sum(s.tool_errors for s in sessions)
    tokens_input = sum(s.tokens_input for s in sessions)
    tokens_output = sum(s.tokens_output for s in sessions)
    repeated_cwds = [cwd for cwd, count in cwd_counts.items() if count > 1]
    biggest = sessions[0] if sessions else None

    insights = []
    if biggest and biggest.last_message:
        insights.append(DailyInsight(label="最后一条关键消息", detail=truncate(biggest.last_message, 120)))
    if repeated_cwds:
        insights.append(DailyInsight(label="重复聚焦的工作区", detail=f"{len(repeated_cwds)} 个目录今天被反复进入，优先检查是否存在来回切换或目标不清。"))
    if tool_errors:
        insights.append(DailyInsight(label="工具失败", detail=f"观察到 {tool_errors} 次疑似失败输出，适合把前置条件写得更明确。"))
    if function_calls:
        insights.append(DailyInsight(label="工具使用", detail=f"今天共有 {function_calls} 次工具调用，适合检查有没有先搜再问、先列清单再改文件。"))
    if tokens_input + tokens_output:
        insights.append(DailyInsight(label="模型消耗", detail=f"累计输入 {tokens_input} tokens，输出 {tokens_output} tokens。"))
    if thread_names:
        insights.append(DailyInsight(label="线程标题", detail=", ".join(thread_names[:5])))
    history_tails = [s.raw.get("history_tail") for s in sessions if isinstance(s.raw, dict) and s.raw.get("history_tail")]
    if history_tails:
        insights.append(DailyInsight(label="历史补强", detail=f"找到了 {len(history_tails)} 条本地历史补充，说明复盘可以补上线程末尾语境。"))
    shell_snapshots = [s.raw.get("shell_snapshot_count") for s in sessions if isinstance(s.raw, dict) and s.raw.get("shell_snapshot_count")]
    if shell_snapshots:
        insights.append(DailyInsight(label="Shell 快照", detail=f"关联到 {sum(int(v) for v in shell_snapshots)} 个 shell 快照，能看见更多命令层上下文。"))

    metrics = {
        "session_count": len(sessions),
        "function_calls": function_calls,
        "tool_errors": tool_errors,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "cwd_count": len(cwd_counts),
        "top_cwds": cwd_counts.most_common(5),
    }
    return DailyReport(
        report_date=report_date,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        sessions=list(sessions),
        insights=insights,
        metrics=metrics,
    )


def recommend_actions(report: DailyReport) -> List[str]:
    sessions = report.sessions
    if not sessions:
        return ["今天没有找到可分析的会话记录。"]
    actions = []
    if report.metrics.get("tool_errors", 0):
        actions.append("先把失败前提写进任务开头，避免 Codex 反复试错。")
    if report.metrics.get("function_calls", 0) > len(sessions) * 6:
        actions.append("把一次目标拆成更短的步骤，减少无效工具调用。")
    if report.metrics.get("cwd_count", 0) > 3:
        actions.append("把今天涉及的工作区收敛到更少目录，减少上下文跳转。")
    if report.metrics.get("tokens_input", 0) > 0 and report.metrics.get("tokens_output", 0) > 0:
        actions.append("下次先给 Codex 更明确的完成标准和验收条件，通常能省掉不少来回。")
    if not actions:
        actions.append("今天的协作很顺，继续沿用当前节奏。")
    return actions


def truncate(text: str, length: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= length:
        return clean
    return clean[: length - 1].rstrip() + "…"
