from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Sequence

from .input_coach import (
    build_discussion_questions,
    build_input_quality_score,
    build_prompt_reviews,
    has_strong_drift,
    is_internal_prompt,
    is_progressive_thread,
    looks_scope_sequence,
    structured_prompt_score,
)
from .models import DailyExample, DailyInsight, DailyReport, DailyScore, EventRecord, SessionSummary


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
        insights.append(DailyInsight(label="工具/环境摩擦", detail=f"观察到 {tool_errors} 次工具或环境失败；这不直接归因于你，但适合让 Codex 尽早诊断。"))
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

    examples = build_daily_examples(sessions, events)
    prompt_reviews = build_prompt_reviews(sessions, events)
    score = build_daily_score(report_date, sessions, history_sessions, events)
    discussion_questions = build_discussion_questions(score, prompt_reviews, examples, sessions)
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
        "prompt_review_count": len(prompt_reviews),
    }
    return DailyReport(
        report_date=report_date,
        generated_at=generated_at or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        sessions=list(sessions),
        insights=insights,
        score=score,
        metrics=metrics,
        examples=examples,
        prompt_reviews=prompt_reviews,
        discussion_questions=discussion_questions,
    )


def recommend_actions(report: DailyReport) -> List[str]:
    sessions = report.sessions
    score = report.score
    if not sessions:
        return ["明天开第一个任务时，先写清目标、输入、输出和完成标准。"]
    actions = [
        example.next_time
        for example in report.examples
        if not _is_positive_example(example)
    ]
    if score:
        if score.total >= 80:
            actions.append("保留今天有效做法：先收束目标，再执行和验证。")
        elif score.total < 60:
            actions.append("明天第一个复杂任务先写一句完成标准，再让 Codex 动手。")
    has_failure_example = any(example.example_type == "工具/环境摩擦" for example in report.examples)
    has_language_example = any(example.example_type in {"目标漂移", "渐进延展", "输入范围过大", "正向输入"} for example in report.examples)
    if report.metrics.get("tool_errors", 0) and not has_failure_example and not has_language_example:
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

    language_improvements = _goal_drift_examples(sessions_by_id, events_by_session)
    positive_language_examples = _positive_input_examples(sessions_by_id, events_by_session)
    if language_improvements or positive_language_examples:
        return language_improvements[:2] + positive_language_examples[:1]

    external_examples: List[DailyExample] = []
    external_examples.extend(_failure_retry_examples(sessions_by_id, events_by_session))
    external_examples.extend(_heavy_tool_examples(sessions))
    return external_examples[:2] + _positive_examples(sessions)[:1]


def _goal_drift_examples(
    sessions_by_id: Dict[str, SessionSummary],
    events_by_session: Dict[str, List[EventRecord]],
) -> List[DailyExample]:
    examples: List[DailyExample] = []
    for session_id, session_events in events_by_session.items():
        user_messages = [
            _event_text(event)
            for event in session_events
            if event.event_type == "user_message" and _event_text(event) and not is_internal_prompt(_event_text(event))
        ]
        distinct_messages = _distinct_texts(user_messages)
        if len(distinct_messages) < 3:
            continue
        session = sessions_by_id[session_id]
        snippets = "；".join(truncate(message, 34) for message in distinct_messages[:4])
        if is_progressive_thread(distinct_messages):
            examples.append(
                DailyExample(
                    example_type="渐进延展",
                    session_label=_session_label(session),
                    cwd=session.cwd or "unknown",
                    what_happened=f"同一个主线被连续推进了 {len(distinct_messages)} 轮：{snippets}。",
                    why_it_matters="这是围绕同一主线逐步深入，不是目标漂移；真正的风险是长会话后当前结论和下一步边界变模糊。",
                    next_time="每 3-5 轮做一次阶段收束：让 Codex 先总结当前结论、未决问题和下一轮只做什么。",
                )
            )
            continue
        if not has_strong_drift(distinct_messages):
            if looks_scope_sequence(distinct_messages):
                examples.append(
                    DailyExample(
                        example_type="输入范围过大",
                        session_label=_session_label(session),
                        cwd=session.cwd or "unknown",
                        what_happened=f"同一会话里连续叠加了多个交付：{snippets}。",
                        why_it_matters="这不一定是目标漂移，但一次把多个输出形态塞进同一轮，会让 Codex 难以判断先交付哪一个。",
                        next_time="先指定本轮唯一交付物，再把其他方向列成下一轮候选。",
                    )
                )
            continue
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
            happened = f"同类工具/环境失败出现 {count} 次：{truncate(sample, 100)}。"
        else:
            happened = f"这个会话出现 {len(failures)} 次工具/环境失败信号，其中一条是：{truncate(sample, 100)}。"
        examples.append(
            DailyExample(
                example_type="工具/环境摩擦",
                session_label=_session_label(session),
                cwd=session.cwd or "unknown",
                what_happened=happened,
                why_it_matters="这不算你的操作问题；真正影响效率的是 Codex 继续重试，而不是先定位路径、安装、权限或 PATH。",
                next_time="看到同类工具/环境失败两次后，直接要求 Codex 进入诊断模式并先跑最小验证命令。",
            )
        )
    return sorted(examples, key=lambda example: example.what_happened, reverse=True)


def _positive_input_examples(
    sessions_by_id: Dict[str, SessionSummary],
    events_by_session: Dict[str, List[EventRecord]],
) -> List[DailyExample]:
    candidates: List[tuple[int, DailyExample]] = []
    for session_id, session_events in events_by_session.items():
        session = sessions_by_id[session_id]
        for event in session_events:
            if event.event_type != "user_message":
                continue
            message = _event_text(event)
            if is_internal_prompt(message):
                continue
            score = structured_prompt_score(message)
            if score < 3:
                continue
            candidates.append(
                (
                    score,
                    DailyExample(
                        example_type="正向输入",
                        session_label=_session_label(session),
                        cwd=session.cwd or "unknown",
                        what_happened=f"这条输入给出了目标、材料或完成标准：{truncate(message, 100)}。",
                        why_it_matters="结构化输入会让 Codex 更快对齐交付物、边界和验收方式，少靠后续追问补信息。",
                        next_time="继续用这个格式开复杂任务：目标、输入材料、输出形式、完成标准、先不要做的事。",
                    ),
                )
            )
    return [example for _, example in sorted(candidates, key=lambda item: item[0], reverse=True)]


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
            what_happened=f"这个会话用 {session.function_calls} 次工具调用推进，且没有工具/环境失败。",
            why_it_matters="低故障、低调用的会话通常说明任务入口和收尾比较清楚，Codex 不需要反复补上下文。",
            next_time="保留这个模式：先给目标和验收标准，再让 Codex 执行并报告验证结果。",
        )
    ]


def build_daily_score(
    report_date: str,
    sessions: Sequence[SessionSummary],
    history_sessions: Sequence[SessionSummary] | None = None,
    events: Sequence[EventRecord] | None = None,
) -> DailyScore:
    return build_input_quality_score(report_date, sessions, history_sessions, events)


def _dedupe(items: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _is_positive_example(example: DailyExample) -> bool:
    return example.example_type in {"正向样例", "正向输入"}


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


def _looks_complete(message: str) -> bool:
    lowered = message.lower()
    keywords = ("完成", "done", "ready", "fixed", "generated", "success", "resolved", "已完成", "收尾", "总结")
    return any(keyword in lowered or keyword in message for keyword in keywords)


def truncate(text: str, length: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= length:
        return clean
    return clean[: length - 1].rstrip() + "…"
