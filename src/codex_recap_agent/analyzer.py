from __future__ import annotations

import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Sequence

from .models import DailyInsight, DailyReport, DailyScore, ScoreDimension, SessionSummary


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


def build_daily_report(
    report_date: str,
    sessions: Sequence[SessionSummary],
    generated_at: str | None = None,
    history_sessions: Sequence[SessionSummary] | None = None,
) -> DailyReport:
    sessions = sorted(sessions, key=lambda s: (s.updated_at or s.started_at or "", s.session_id), reverse=True)
    history_sessions = list(history_sessions or sessions)
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

    score = build_daily_score(report_date, sessions, history_sessions)
    metrics = {
        "session_count": len(sessions),
        "function_calls": function_calls,
        "tool_errors": tool_errors,
        "tokens_input": tokens_input,
        "tokens_output": tokens_output,
        "cwd_count": len(cwd_counts),
        "top_cwds": cwd_counts.most_common(5),
        "score": score.total if score else None,
        "score_label": score.label if score else None,
        "score_trend_delta": score.trend_delta if score else None,
    }
    return DailyReport(
        report_date=report_date,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        sessions=list(sessions),
        insights=insights,
        score=score,
        metrics=metrics,
    )


def recommend_actions(report: DailyReport) -> List[str]:
    sessions = report.sessions
    score = report.score
    if not sessions:
        if score and score.total == 0:
            return ["今天没有可分析的会话记录，记为 0 分。", "明天先保证至少有一次明确的目标收束，再进入执行。"]
        return ["今天没有找到可分析的会话记录。"]
    actions = []
    if score:
        if score.total >= 80:
            actions.append("今天整体状态不错，保持现在的收束方式和节奏。")
        elif score.total < 60:
            actions.append("今天偏低，明天先把目标、输入、输出和完成标准说清楚。")
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


def build_daily_score(
    report_date: str,
    sessions: Sequence[SessionSummary],
    history_sessions: Sequence[SessionSummary] | None = None,
) -> DailyScore:
    current_profile = _profile_for_day(sessions, report_date)
    history_profiles = _profiles_by_day(history_sessions or sessions)
    previous_profiles = [
        profile
        for day, profile in sorted(history_profiles.items())
        if day < report_date
    ]
    previous_7 = previous_profiles[-7:]
    baseline = _average_profiles(previous_7) if previous_7 else None
    if int(current_profile.get("session_count", 0) or 0) == 0:
        trend_delta = 0
        trend_label = "暂无趋势"
        if previous_7:
            prior_avg = round(sum(_score_profile(profile, baseline=None).total for profile in previous_7) / len(previous_7))
            trend_delta = -prior_avg
            trend_label = f"低于近 7 天平均 {abs(trend_delta)} 分"
        dimensions = [
            ScoreDimension(label="目标清晰度", score=0, detail="今天没有可分析的会话。"),
            ScoreDimension(label="执行效率", score=0, detail="今天没有可分析的工具调用。"),
            ScoreDimension(label="稳定性", score=0, detail="今天没有可分析的执行记录。"),
            ScoreDimension(label="收尾质量", score=0, detail="今天没有可分析的收尾信号。"),
        ]
        return DailyScore(
            total=0,
            label="负向",
            trend_label=trend_label,
            trend_delta=trend_delta,
            positive_feedback="今天没有产生新的长会话负担。",
            negative_feedback="今天没有可分析的 Codex 协作记录，无法证明有推进。",
            dimensions=dimensions,
        )

    focus = _score_focus(current_profile)
    efficiency = _score_efficiency(current_profile, baseline)
    stability = _score_stability(current_profile)
    completion = _score_completion(current_profile)
    dimensions = [
        ScoreDimension(label="目标清晰度", score=focus, detail=_focus_detail(current_profile)),
        ScoreDimension(label="执行效率", score=efficiency, detail=_efficiency_detail(current_profile, baseline)),
        ScoreDimension(label="稳定性", score=stability, detail=_stability_detail(current_profile)),
        ScoreDimension(label="收尾质量", score=completion, detail=_completion_detail(current_profile)),
    ]
    total = round(sum(d.score for d in dimensions) / len(dimensions)) if dimensions else 0
    trend_delta = 0
    trend_label = "暂无趋势"
    if previous_7:
        prior_avg = round(sum(_score_profile(profile, baseline=None).total for profile in previous_7) / len(previous_7))
        trend_delta = total - prior_avg
        trend_label = _trend_label(trend_delta)
    label = _overall_label(total)
    positive, negative = _feedback_for_score(total, dimensions, current_profile)
    return DailyScore(
        total=total,
        label=label,
        trend_label=trend_label,
        trend_delta=trend_delta,
        positive_feedback=positive,
        negative_feedback=negative,
        dimensions=dimensions,
    )


def _profile_for_day(sessions: Sequence[SessionSummary], report_date: str) -> Dict[str, object]:
    day_sessions = list(sessions)
    if not sessions:
        return {
            "session_count": 0,
            "function_calls": 0,
            "tool_errors": 0,
            "tokens_input": 0,
            "tokens_output": 0,
            "cwd_count": 0,
            "last_messages": [],
            "completion_hits": 0,
            "question_hits": 0,
        }
    cwd_counts = Counter((s.cwd or "unknown") for s in day_sessions)
    last_messages = [s.last_message or "" for s in day_sessions if s.last_message]
    completion_hits = sum(1 for message in last_messages if _looks_complete(message))
    question_hits = sum(1 for message in last_messages if _looks_open(message))
    return {
        "session_count": len(day_sessions),
        "function_calls": sum(s.function_calls for s in day_sessions),
        "tool_errors": sum(s.tool_errors for s in day_sessions),
        "tokens_input": sum(s.tokens_input for s in day_sessions),
        "tokens_output": sum(s.tokens_output for s in day_sessions),
        "cwd_count": len(cwd_counts),
        "cwd_repeats": sum(1 for count in cwd_counts.values() if count > 1),
        "last_messages": last_messages,
        "completion_hits": completion_hits,
        "question_hits": question_hits,
    }


def _profiles_by_day(sessions: Sequence[SessionSummary]) -> Dict[str, Dict[str, object]]:
    buckets: Dict[str, List[SessionSummary]] = defaultdict(list)
    for session in sessions:
        dt = _parse_dt(session.updated_at or session.started_at)
        if not dt:
            continue
        buckets[dt.date().isoformat()].append(session)
    return {day: _profile_for_day(items, day) for day, items in buckets.items()}


def _average_profiles(profiles: Sequence[Dict[str, object]]) -> Dict[str, float]:
    keys = ("session_count", "function_calls", "tool_errors", "tokens_input", "tokens_output", "cwd_count", "cwd_repeats", "completion_hits", "question_hits")
    totals = {key: 0.0 for key in keys}
    for profile in profiles:
        for key in keys:
            totals[key] += float(profile.get(key, 0) or 0)
    count = max(1, len(profiles))
    return {key: value / count for key, value in totals.items()}


def _score_profile(profile: Dict[str, object], baseline: Dict[str, float] | None) -> DailyScore:
    focus = _score_focus(profile)
    efficiency = _score_efficiency(profile, baseline)
    stability = _score_stability(profile)
    completion = _score_completion(profile)
    total = round((focus + efficiency + stability + completion) / 4)
    return DailyScore(
        total=total,
        label=_overall_label(total),
        trend_label="暂无趋势",
        trend_delta=0,
        positive_feedback="",
        negative_feedback="",
        dimensions=[],
    )


def _score_focus(profile: Dict[str, object]) -> int:
    score = 25
    score -= int(max(0, (profile.get("cwd_count", 0) or 0) - 1) * 4)
    score -= int(max(0, (profile.get("session_count", 0) or 0) - 4) * 1.5)
    if (profile.get("session_count", 0) or 0) <= 2 and (profile.get("cwd_count", 0) or 0) <= 1:
        score += 2
    return _clamp(score)


def _score_efficiency(profile: Dict[str, object], baseline: Dict[str, float] | None) -> int:
    session_count = max(1, int(profile.get("session_count", 0) or 0))
    calls_per_session = float(profile.get("function_calls", 0) or 0) / session_count
    tokens_total = float(profile.get("tokens_input", 0) or 0) + float(profile.get("tokens_output", 0) or 0)
    tokens_per_session = tokens_total / session_count
    if baseline:
        baseline_calls = max(1.0, baseline.get("function_calls", 0.0) / max(1.0, baseline.get("session_count", 1.0)))
        baseline_tokens = max(1.0, (baseline.get("tokens_input", 0.0) + baseline.get("tokens_output", 0.0)) / max(1.0, baseline.get("session_count", 1.0)))
        call_ratio = calls_per_session / baseline_calls
        token_ratio = tokens_per_session / baseline_tokens
        score = 25
        if call_ratio > 1:
            score -= min(10, int(round((call_ratio - 1) * 8)))
        else:
            score += min(2, int(round((1 - call_ratio) * 4)))
        if token_ratio > 1:
            score -= min(10, int(round((token_ratio - 1) * 4)))
        else:
            score += min(2, int(round((1 - token_ratio) * 3)))
        return _clamp(score)
    score = 25
    if calls_per_session > 120:
        score -= 10
    elif calls_per_session > 80:
        score -= 5
    elif calls_per_session > 40:
        score -= 1
    if tokens_per_session > 20000000:
        score -= 7
    elif tokens_per_session > 10000000:
        score -= 4
    elif tokens_per_session > 5000000:
        score -= 2
    return _clamp(score)


def _score_stability(profile: Dict[str, object]) -> int:
    calls = int(profile.get("function_calls", 0) or 0)
    errors = int(profile.get("tool_errors", 0) or 0)
    if calls <= 0:
        return 10 if errors else 20
    error_rate = errors / calls
    score = 25 - int(round(min(18, error_rate * 120)))
    if errors == 0 and calls > 0:
        score += 1
    return _clamp(score)


def _score_completion(profile: Dict[str, object]) -> int:
    score = 15
    completion_hits = int(profile.get("completion_hits", 0) or 0)
    question_hits = int(profile.get("question_hits", 0) or 0)
    last_messages = len(profile.get("last_messages", []) or [])
    score += min(8, completion_hits * 2)
    score += min(2, last_messages // 3)
    score -= min(6, question_hits * 2)
    if int(profile.get("tool_errors", 0) or 0) == 0 and last_messages:
        score += 1
    return _clamp(score)


def _overall_label(score: int) -> str:
    if score >= 80:
        return "正向"
    if score >= 60:
        return "中性"
    return "负向"


def _trend_label(delta: int) -> str:
    if delta >= 8:
        return f"高于近 7 天平均 {delta} 分"
    if delta <= -8:
        return f"低于近 7 天平均 {abs(delta)} 分"
    return f"接近近 7 天平均（{delta:+d} 分）"


def _feedback_for_score(score: int, dimensions: List[ScoreDimension], profile: Dict[str, object]) -> tuple[str, str]:
    best = max(dimensions, key=lambda d: d.score) if dimensions else None
    worst = min(dimensions, key=lambda d: d.score) if dimensions else None
    positive_map = {
        "目标清晰度": "今天的目标收束得比较早，协作没有明显发散。",
        "执行效率": "工具调用和推进节奏比较干净，没有太多空转。",
        "稳定性": "今天的执行很稳，失败重试没有明显放大。",
        "收尾质量": "今天的收尾信号不错，任务结束得比较完整。",
    }
    negative_map = {
        "目标清晰度": "今天工作区切换偏多，任务边界还有点散。",
        "执行效率": "工具调用偏重，明天可以先拆步再执行。",
        "稳定性": "失败输出偏多，最好先诊断再继续跑。",
        "收尾质量": "收尾信号不够强，最好提前定义什么算完成。",
    }
    positive = positive_map.get(best.label if best else "", "今天整体还可以。")
    negative = negative_map.get(worst.label if worst else "", "今天还有一些摩擦，明天可以再收紧一点。")
    if score >= 80:
        positive = "今天整体状态不错，节奏和收尾都比较稳。"
    elif score < 60:
        negative = "今天整体偏低，最该先改的是任务入口和失败处理。"
    return positive, negative


def _focus_detail(profile: Dict[str, object]) -> str:
    return f"{int(profile.get('session_count', 0) or 0)} 个会话、{int(profile.get('cwd_count', 0) or 0)} 个工作区。"


def _efficiency_detail(profile: Dict[str, object], baseline: Dict[str, float] | None) -> str:
    session_count = max(1, int(profile.get("session_count", 0) or 0))
    calls_per_session = float(profile.get("function_calls", 0) or 0) / session_count
    tokens = float(profile.get("tokens_input", 0) or 0) + float(profile.get("tokens_output", 0) or 0)
    tokens_per_session = tokens / session_count
    if baseline:
        baseline_calls = max(1.0, baseline.get("function_calls", 0.0) / max(1.0, baseline.get("session_count", 1.0)))
        return f"平均 {calls_per_session:.1f} 次工具调用/会话，对比近 7 天基线 {baseline_calls:.1f}。"
    return f"平均 {calls_per_session:.1f} 次工具调用/会话，约 {tokens_per_session:.0f} tokens/会话。"


def _stability_detail(profile: Dict[str, object]) -> str:
    calls = int(profile.get("function_calls", 0) or 0)
    errors = int(profile.get("tool_errors", 0) or 0)
    rate = (errors / calls * 100) if calls else 0
    return f"{errors} 次疑似失败，约 {rate:.1f}% 的调用出现问题。"


def _completion_detail(profile: Dict[str, object]) -> str:
    return f"{int(profile.get('completion_hits', 0) or 0)} 条明显完成信号，{int(profile.get('question_hits', 0) or 0)} 条未决信号。"


def _looks_complete(message: str) -> bool:
    lowered = message.lower()
    keywords = ("完成", "done", "ready", "fixed", "generated", "success", "resolved", "已完成", "收尾", "总结")
    return any(keyword in lowered or keyword in message for keyword in keywords)


def _looks_open(message: str) -> bool:
    lowered = message.lower()
    keywords = ("待", "需要", "please", "todo", "question", "?", "未决", "继续", "still")
    return any(keyword in lowered or keyword in message for keyword in keywords)


def _clamp(value: int) -> int:
    return max(0, min(25, int(value)))


def truncate(text: str, length: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= length:
        return clean
    return clean[: length - 1].rstrip() + "…"
