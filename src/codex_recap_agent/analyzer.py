from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Sequence

from .models import DailyExample, DailyInsight, DailyReport, DailyScore, EventRecord, ScoreDimension, SessionSummary


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
    events: Sequence[EventRecord] | None = None,
) -> DailyReport:
    sessions = sorted(sessions, key=lambda s: (s.updated_at or s.started_at or "", s.session_id), reverse=True)
    history_sessions = list(history_sessions or sessions)
    events = list(events or [])
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
    examples = build_daily_examples(sessions, events)
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
        examples=examples,
    )


def recommend_actions(report: DailyReport) -> List[str]:
    sessions = report.sessions
    score = report.score
    if not sessions:
        return ["明天开第一个任务时，先写清目标、输入、输出和完成标准。"]
    actions = [
        example.next_time
        for example in report.examples
        if example.example_type != "正向样例"
    ]
    if score:
        if score.total >= 80:
            actions.append("保留今天有效做法：先收束目标，再执行和验证。")
        elif score.total < 60:
            actions.append("明天第一个复杂任务先写一句完成标准，再让 Codex 动手。")
    has_failure_example = any(example.example_type == "失败重试" for example in report.examples)
    if report.metrics.get("tool_errors", 0) and not has_failure_example:
        actions.append("同类失败出现两次后，先让 Codex 检查 cwd、PATH、权限和最小复现命令。")
    if report.metrics.get("function_calls", 0) > len(sessions) * 6:
        actions.append("把工具调用很多的任务拆成“先定位、再修改、最后验证”三段。")
    if report.metrics.get("cwd_count", 0) > 3:
        actions.append("跨多个工作区前，先说明当前只处理哪一个目录和交付物。")
    if report.metrics.get("tokens_input", 0) > 0 and report.metrics.get("tokens_output", 0) > 0:
        actions.append("长任务开头加一句“完成后请验证什么”，减少收尾来回。")
    if not actions:
        actions.append("继续保持今天这种目标明确、执行后有验证的节奏。")
    return _dedupe(actions)[:3]


def build_daily_examples(
    sessions: Sequence[SessionSummary],
    events: Sequence[EventRecord],
) -> List[DailyExample]:
    if not sessions:
        return []
    sessions_by_id = {session.session_id: session for session in sessions}
    events_by_session: Dict[str, List[EventRecord]] = defaultdict(list)
    for event in events:
        if event.session_id in sessions_by_id:
            events_by_session[event.session_id].append(event)

    improvement_examples: List[DailyExample] = []
    improvement_examples.extend(_failure_retry_examples(sessions_by_id, events_by_session))
    improvement_examples.extend(_goal_drift_examples(sessions_by_id, events_by_session))
    improvement_examples.extend(_heavy_tool_examples(sessions))
    positive_examples = _positive_examples(sessions)
    return improvement_examples[:2] + positive_examples[:1]


def _goal_drift_examples(
    sessions_by_id: Dict[str, SessionSummary],
    events_by_session: Dict[str, List[EventRecord]],
) -> List[DailyExample]:
    examples: List[DailyExample] = []
    for session_id, session_events in events_by_session.items():
        user_messages = [
            _event_text(event)
            for event in session_events
            if event.event_type == "user_message" and _event_text(event)
        ]
        distinct_messages = _distinct_texts(user_messages)
        if len(distinct_messages) < 3:
            continue
        session = sessions_by_id[session_id]
        snippets = "；".join(truncate(message, 34) for message in distinct_messages[:4])
        examples.append(
            DailyExample(
                example_type="目标漂移",
                session_label=_session_label(session),
                cwd=session.cwd or "unknown",
                what_happened=f"同一个会话里连续出现 {len(distinct_messages)} 个方向：{snippets}。",
                why_it_matters="方向连续切换会让 Codex 反复重建上下文，后面的判断、写作和验证容易互相挤占。",
                next_time="把这类任务拆成连续小任务：先定义本轮只交付什么，完成后再开下一轮。",
            )
        )
    return sorted(examples, key=lambda example: example.what_happened, reverse=True)


def _failure_retry_examples(
    sessions_by_id: Dict[str, SessionSummary],
    events_by_session: Dict[str, List[EventRecord]],
) -> List[DailyExample]:
    examples: List[DailyExample] = []
    for session_id, session_events in events_by_session.items():
        failures: List[tuple[str, str]] = []
        for event in session_events:
            if event.event_type != "function_call_output":
                continue
            output = _event_text(event)
            failure_line = _failure_line(output)
            if failure_line:
                failures.append((_failure_signature(failure_line), failure_line))
        if not failures:
            continue
        counts = Counter(signature for signature, _ in failures)
        signature, count = counts.most_common(1)[0]
        session = sessions_by_id[session_id]
        if count < 2 and len(failures) < 2 and session.tool_errors < 2:
            continue
        sample = next(line for found_signature, line in failures if found_signature == signature)
        if count >= 2:
            happened = f"同类失败出现 {count} 次：{truncate(sample, 100)}。"
        else:
            happened = f"这个会话出现 {len(failures)} 次疑似失败，其中一条是：{truncate(sample, 100)}。"
        examples.append(
            DailyExample(
                example_type="失败重试",
                session_label=_session_label(session),
                cwd=session.cwd or "unknown",
                what_happened=happened,
                why_it_matters="连续重试会消耗工具调用，也容易把真正的路径、安装、权限或 PATH 问题藏在噪音里。",
                next_time="同类失败两次后先进入诊断模式：检查 cwd、PATH、安装位置、权限，再跑最小验证命令。",
            )
        )
    return sorted(examples, key=lambda example: example.what_happened, reverse=True)


def _heavy_tool_examples(sessions: Sequence[SessionSummary]) -> List[DailyExample]:
    if len(sessions) < 2:
        return []
    average_calls = sum(session.function_calls for session in sessions) / max(1, len(sessions))
    threshold = max(80.0, average_calls * 1.5)
    examples = []
    for session in sessions:
        if session.function_calls < threshold:
            continue
        examples.append(
            DailyExample(
                example_type="工具调用过重",
                session_label=_session_label(session),
                cwd=session.cwd or "unknown",
                what_happened=f"这个会话用了 {session.function_calls} 次工具调用，当天平均约 {average_calls:.1f} 次。",
                why_it_matters="单个会话工具调用过重时，通常说明探索、修改和验证混在一起，后面更难判断哪一步有效。",
                next_time="先让 Codex 列出 2-4 个检查点，只完成当前检查点后再继续下一段。",
            )
        )
    return sorted(examples, key=lambda example: example.what_happened, reverse=True)


def _positive_examples(sessions: Sequence[SessionSummary]) -> List[DailyExample]:
    if not sessions:
        return []
    average_calls = sum(session.function_calls for session in sessions) / max(1, len(sessions))
    candidates = [
        session
        for session in sessions
        if session.tool_errors == 0
        and session.function_calls <= max(6, average_calls)
        and _looks_complete(session.last_message or "")
    ]
    if not candidates:
        candidates = [
            session
            for session in sessions
            if session.tool_errors == 0 and session.function_calls <= max(6, average_calls)
        ]
    if not candidates:
        return []
    session = sorted(candidates, key=lambda item: (item.function_calls, item.event_count))[0]
    return [
        DailyExample(
            example_type="正向样例",
            session_label=_session_label(session),
            cwd=session.cwd or "unknown",
            what_happened=f"这个会话用 {session.function_calls} 次工具调用推进，且没有疑似失败。",
            why_it_matters="低失败、低调用的会话通常说明任务入口和收尾比较清楚，Codex 不需要反复补上下文。",
            next_time="保留这个模式：先给目标和验收标准，再让 Codex 执行并报告验证结果。",
        )
    ]


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
            label="需要调整",
            trend_label=trend_label,
            trend_delta=trend_delta,
            positive_feedback="今天没有产生新的长会话负担。",
            negative_feedback="今天没有可分析的 Codex 协作记录，无法证明有推进。",
            score_reason="今天需要调整，因为没有可分析的 Codex 协作记录，无法判断目标、执行和收尾质量。",
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
    total = sum(d.score for d in dimensions)
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
        score_reason=_score_reason(total, label, current_profile),
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
    total = focus + efficiency + stability + completion
    return DailyScore(
        total=total,
        label=_overall_label(total),
        trend_label="暂无趋势",
        trend_delta=0,
        positive_feedback="",
        negative_feedback="",
        score_reason="",
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
        return "状态很好"
    if score >= 60:
        return "基本可用，有摩擦"
    return "需要调整"


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
        negative = "任务入口、失败处理或收尾信号里至少有一项拖慢了推进，明天先把完成标准写清楚。"
    return positive, negative


def _score_reason(score: int, label: str, profile: Dict[str, object]) -> str:
    session_count = int(profile.get("session_count", 0) or 0)
    cwd_count = int(profile.get("cwd_count", 0) or 0)
    calls = int(profile.get("function_calls", 0) or 0)
    errors = int(profile.get("tool_errors", 0) or 0)
    completion_hits = int(profile.get("completion_hits", 0) or 0)
    question_hits = int(profile.get("question_hits", 0) or 0)
    calls_per_session = calls / max(1, session_count)

    if label == "状态很好":
        prefix = "今天状态很好"
    elif label == "基本可用，有摩擦":
        prefix = "今天基本可用，但还有摩擦"
    else:
        prefix = "今天需要调整"

    details = [f"{session_count} 个会话分布在 {cwd_count} 个工作区"]
    if calls:
        details.append(f"平均 {calls_per_session:.1f} 次工具调用/会话")
    if errors:
        details.append(f"出现 {errors} 次疑似失败")
    elif calls:
        details.append("没有疑似失败输出")
    if question_hits:
        details.append(f"{question_hits} 条收尾仍像未决问题")
    elif completion_hits:
        details.append(f"{completion_hits} 条明显完成信号")
    return f"{prefix}，主要因为 " + "，".join(details[:4]) + "。"


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _session_label(session: SessionSummary) -> str:
    return truncate(session.thread_name or session.session_id, 64)


def _distinct_texts(messages: Sequence[str]) -> List[str]:
    seen = set()
    result = []
    for message in messages:
        clean = " ".join(message.split())
        if len(clean) < 3:
            continue
        signature = re.sub(r"\W+", "", clean.lower())
        if not signature or signature in seen:
            continue
        seen.add(signature)
        result.append(clean)
    return result


def _event_text(event: EventRecord) -> str:
    if event.message:
        return event.message
    data = event.data if isinstance(event.data, dict) else {}
    for key in ("message", "output", "text", "last_agent_message", "arguments"):
        value = data.get(key)
        if value is None:
            continue
        if isinstance(value, str):
            return value
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)
    return ""


_FAILURE_HINTS = (
    "command not found",
    "operation not permitted",
    "permission denied",
    "no such file",
    "not installed",
    "no module named",
    "traceback",
    "failed",
    "exception",
    "errno",
    "importerror",
    "modulenotfounderror",
    "assertionerror",
    "syntaxerror",
)

_BENIGN_FAILURE_HINTS = (
    "failure-prone",
    "error-prone",
    "failure reason this run: none",
    "no failure",
    "no error",
    "0 errors",
    "errors: 0",
)


def _failure_line(output: str) -> str | None:
    if not output:
        return None
    lines = output.splitlines()
    exit_codes = _exit_codes(output)
    if exit_codes:
        nonzero_exit_line = None
        for line in lines:
            clean = " ".join(line.split())
            if not clean:
                continue
            code = _line_exit_code(clean)
            if code is not None and code != 0:
                nonzero_exit_line = clean
                break
        if all(code == 0 for code in exit_codes):
            return None
        for line in lines:
            clean = " ".join(line.split())
            if _line_has_failure_hint(clean):
                return _failure_excerpt(clean)
        return nonzero_exit_line or truncate(output, 120)

    for line in lines:
        clean = " ".join(line.split())
        if _line_has_failure_hint(clean):
            return _failure_excerpt(clean)
    return None


def _failure_signature(line: str) -> str:
    lowered = line.lower()
    lowered = re.sub(r"\b\d+\b", "#", lowered)
    lowered = re.sub(r"\s+", " ", lowered).strip()
    return lowered


def _line_has_failure_hint(line: str) -> bool:
    if not line:
        return False
    lowered = line.lower()
    if any(hint in lowered for hint in _BENIGN_FAILURE_HINTS):
        return False
    if any(hint in lowered for hint in _FAILURE_HINTS):
        return True
    return bool(re.search(r"(?:^|\s)(?:error|fatal):", lowered))


def _failure_excerpt(line: str) -> str:
    lowered = line.lower()
    match_start = -1
    match_end = -1
    for hint in _FAILURE_HINTS:
        index = lowered.find(hint)
        if index >= 0:
            match_start = index
            match_end = index + len(hint)
            break
    if match_start < 0:
        match = re.search(r"(?:^|\s)(?:error|fatal):", lowered)
        if match:
            match_start = match.start()
            match_end = match.end()
    if match_start < 0:
        return line
    start = max(0, match_start - 45)
    end = min(len(line), match_end + 95)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(line) else ""
    return prefix + line[start:end].strip() + suffix


def _exit_codes(output: str) -> List[int]:
    codes: List[int] = []
    for line in output.splitlines():
        code = _line_exit_code(line)
        if code is not None:
            codes.append(code)
    return codes


def _line_exit_code(line: str) -> int | None:
    lowered = line.lower()
    patterns = (
        r"process\s+exited\s+with\s+code\s+(-?\d+)",
        r"exited\s+with\s+code\s+(-?\d+)",
        r"exit(?:ed)?\s+code\s+(-?\d+)",
        r"exit\s+status\s+(-?\d+)",
    )
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if not match:
            continue
        try:
            return int(match.group(1))
        except ValueError:
            return None
    return None


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
