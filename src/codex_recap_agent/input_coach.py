from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Dict, Iterable, List, Sequence

from .models import DailyExample, DailyScore, EventRecord, PromptReview, ScoreDimension, SessionSummary


def build_input_quality_score(
    report_date: str,
    sessions: Sequence[SessionSummary],
    history_sessions: Sequence[SessionSummary] | None = None,
    events: Sequence[EventRecord] | None = None,
) -> DailyScore:
    _ = history_sessions
    _ = report_date
    current_profile = _input_profile_for_day(sessions, events or [])
    if int(current_profile.get("message_count", 0) or 0) == 0:
        dimensions = [
            ScoreDimension(label="目标清晰度", score=0, detail="今天没有可分析的用户输入。", max_score=20),
            ScoreDimension(label="上下文充分度", score=0, detail="今天没有可分析的用户输入。", max_score=20),
            ScoreDimension(label="输出/约束明确度", score=0, detail="今天没有可分析的用户输入。", max_score=20),
            ScoreDimension(label="完成标准", score=0, detail="今天没有可分析的用户输入。", max_score=20),
            ScoreDimension(label="追问节奏", score=0, detail="今天没有可分析的用户输入。", max_score=20),
        ]
        return DailyScore(
            total=0,
            label="需要调整",
            trend_label="暂无输入质量趋势",
            trend_delta=0,
            positive_feedback="今天没有新的输入负担。",
            negative_feedback="今天没有可分析的自然语言输入，无法判断你和 Codex 的沟通质量。",
            score_reason="今天需要调整，因为没有可分析的用户输入；工具调用、工具失败和 token 消耗不参与这个分数。",
            dimensions=dimensions,
        )

    dimensions = [
        ScoreDimension(label="目标清晰度", score=_score_goal_clarity(current_profile), detail=_input_goal_detail(current_profile), max_score=20),
        ScoreDimension(label="上下文充分度", score=_score_context_quality(current_profile), detail=_input_context_detail(current_profile), max_score=20),
        ScoreDimension(label="输出/约束明确度", score=_score_output_constraints(current_profile), detail=_input_output_detail(current_profile), max_score=20),
        ScoreDimension(label="完成标准", score=_score_completion_standard(current_profile), detail=_input_completion_detail(current_profile), max_score=20),
        ScoreDimension(label="追问节奏", score=_score_followup_rhythm(current_profile), detail=_input_rhythm_detail(current_profile), max_score=20),
    ]
    total = sum(d.score for d in dimensions)
    label = _overall_label(total)
    positive, negative = _input_feedback_for_score(total, dimensions)
    return DailyScore(
        total=total,
        label=label,
        trend_label="暂无输入质量趋势",
        trend_delta=0,
        positive_feedback=positive,
        negative_feedback=negative,
        score_reason=_input_score_reason(label, current_profile),
        dimensions=dimensions,
    )


def build_prompt_reviews(
    sessions: Sequence[SessionSummary],
    events: Sequence[EventRecord],
) -> List[PromptReview]:
    if not sessions:
        return []
    sessions_by_id = {session.session_id: session for session in sessions}
    events_by_session: Dict[str, List[EventRecord]] = defaultdict(list)
    for event in events:
        if event.session_id in sessions_by_id:
            events_by_session[event.session_id].append(event)

    reviews: List[tuple[int, PromptReview]] = []
    for session_id, session_events in events_by_session.items():
        session = sessions_by_id[session_id]
        distinct_messages = _user_messages(session_events)
        if not distinct_messages:
            continue

        progressive_added = False
        if is_progressive_thread(distinct_messages) and not any(_has_stage_summary_signal(message) for message in distinct_messages):
            original = distinct_messages[-1]
            reviews.append(
                (
                    90,
                    PromptReview(
                        review_type="渐进延展收束",
                        session_label=_session_label(session),
                        cwd=session.cwd or "unknown",
                        original=truncate(original, 120),
                        issue="这类追问是有效的逐步深入，但长会话继续推进前缺少一次阶段收束。",
                        better_prompt=_stage_summary_prompt(original),
                        why_better="它先让 Codex 对齐当前结论和下一轮边界，再继续深入，能减少后面越聊越散。",
                    ),
                )
            )
            progressive_added = True

        for message in distinct_messages:
            if structured_prompt_score(message) >= 3:
                reviews.append(
                    (
                        20,
                        PromptReview(
                            review_type="做得好的输入",
                            session_label=_session_label(session),
                            cwd=session.cwd or "unknown",
                            original=truncate(message, 120),
                            issue="这条输入已经给出目标、材料、输出或完成标准，可以作为复杂任务的开头模板。",
                            better_prompt=truncate(message, 180),
                            why_better="结构化输入能让 Codex 少猜边界，直接进入执行和验证。",
                        ),
                    )
                )
                continue
            if looks_scope_bundle(message):
                reviews.append(
                    (
                        80,
                        PromptReview(
                            review_type="范围打包",
                            session_label=_session_label(session),
                            cwd=session.cwd or "unknown",
                            original=truncate(message, 120),
                            issue="同一句里打包了多个交付或方向，Codex 容易同时展开太多分支。",
                            better_prompt=_scope_bundle_prompt(message),
                            why_better="它把本轮交付和下一轮候选分开，Codex 会更容易收尾，也更容易验证。",
                        ),
                    )
                )
                continue
            if not _has_completion_standard(message):
                priority = 70 if not progressive_added else 50
                reviews.append(
                    (
                        priority,
                        PromptReview(
                            review_type="补完成标准",
                            session_label=_session_label(session),
                            cwd=session.cwd or "unknown",
                            original=truncate(message, 120),
                            issue="这条输入说清了方向，但没有说清完成标准；Codex 可能不知道做到什么程度该停。",
                            better_prompt=_completion_standard_prompt(message),
                            why_better="它把目标、输出和验收放到同一句里，能减少收尾时来回确认。",
                        ),
                    )
                )

    deduped: List[PromptReview] = []
    seen = set()
    for _, review in sorted(reviews, key=lambda item: item[0], reverse=True):
        key = (review.session_label, review.original, review.review_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(review)
        if len(deduped) >= 3:
            break
    return deduped


def build_discussion_questions(
    score: DailyScore | None,
    prompt_reviews: Sequence[PromptReview],
    examples: Sequence[DailyExample],
    sessions: Sequence[SessionSummary],
) -> List[str]:
    if not sessions:
        return ["明天如果只复盘一个 Codex 任务，你最想先改进哪一种输入：目标、上下文、输出格式，还是完成标准？"]
    questions: List[str] = []
    if prompt_reviews:
        first = prompt_reviews[0]
        questions.append(f"今天这条输入如果重来，你会不会愿意先用这个改写版开头：{truncate(_inline_text(first.better_prompt), 120)}")
    if any(review.review_type == "渐进延展收束" for review in prompt_reviews) or any(example.example_type == "渐进延展" for example in examples):
        questions.append("我们今天可以讨论：哪些逐步深入的会话适合每 3-5 轮加一次阶段收束？")
    if score and score.dimensions:
        weakest = min(score.dimensions, key=lambda dim: dim.score)
        if weakest.label == "完成标准":
            questions.append("明天开复杂任务时，我们要不要先固定一句完成标准，再让 Codex 动手？")
        elif weakest.label == "输出/约束明确度":
            questions.append("明天你更想优先练习输出格式，还是练习给 Codex 明确保留条件？")
        elif weakest.label == "上下文充分度":
            questions.append("今天哪一次输入如果补上背景材料，Codex 会少问或少猜？")
        elif weakest.label == "追问节奏":
            questions.append("今天哪一段长会话需要先总结结论，再继续下一步？")
    if not questions:
        questions.append("明天最值得保留的输入习惯是哪一个：先说目标、先给材料，还是先写验收？")
    return _dedupe(questions)[:3]


def structured_prompt_score(message: str) -> int:
    if not message:
        return 0
    lowered = message.lower()
    markers = (
        "目标",
        "输入",
        "输出",
        "完成标准",
        "验收",
        "约束",
        "先不要",
        "test plan",
        "assumptions",
        "summary",
        "key changes",
    )
    return sum(1 for marker in markers if marker in lowered or marker in message)


def is_progressive_thread(messages: Sequence[str]) -> bool:
    if len(messages) < 3:
        return False
    followups = messages[1:]
    strong_drift_hits = sum(1 for message in followups if _contains_any(message, _STRONG_DRIFT_MARKERS))
    progressive_hits = sum(1 for message in followups if _contains_any(message, _PROGRESSIVE_MARKERS))
    if strong_drift_hits:
        return False
    if progressive_hits >= 2:
        return True
    return len(messages) >= 6 and progressive_hits >= 1


def is_internal_prompt(message: str) -> bool:
    clean = message.strip()
    prefixes = (
        "The following is the Codex agent history added since your last approval assessment",
        "Another language model started to solve this problem",
        "<permissions instructions>",
        "<environment_context>",
        "<collaboration_mode>",
        "<skills_instructions>",
        "# AGENTS.md instructions",
    )
    return any(clean.startswith(prefix) for prefix in prefixes)


def looks_scope_bundle(message: str) -> bool:
    if re.search(r"(另外|同时|并且|还要)?保留", message):
        return False
    markers = ("顺便", "同时", "另外", "再加", "然后改", "还要", "也帮我", "一并")
    deliverable_markers = ("报告", "文章", "命令", "skill", "推到", "评分", "改写", "自动任务", "github", "分析")
    marker_hits = sum(1 for marker in markers if marker in message)
    deliverable_hits = sum(1 for marker in deliverable_markers if marker.lower() in message.lower() or marker in message)
    return marker_hits >= 1 and deliverable_hits >= 1


def looks_scope_sequence(messages: Sequence[str]) -> bool:
    if len(messages) < 3:
        return False
    return any(looks_scope_bundle(message) for message in messages[1:])


def has_strong_drift(messages: Sequence[str]) -> bool:
    return any(_contains_any(message, _STRONG_DRIFT_MARKERS) for message in messages[1:])


def event_text(event: EventRecord) -> str:
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


def truncate(text: str, length: int) -> str:
    clean = " ".join(text.split())
    if len(clean) <= length:
        return clean
    return clean[: length - 1].rstrip() + "…"


def _input_profile_for_day(sessions: Sequence[SessionSummary], events: Sequence[EventRecord]) -> Dict[str, object]:
    session_ids = {session.session_id for session in sessions}
    events_by_session: Dict[str, List[EventRecord]] = defaultdict(list)
    for event in events:
        if event.session_id in session_ids:
            events_by_session[event.session_id].append(event)

    messages_by_session: Dict[str, List[str]] = {}
    all_messages: List[str] = []
    for session_id, session_events in events_by_session.items():
        distinct_messages = _user_messages(session_events)
        if not distinct_messages:
            continue
        messages_by_session[session_id] = distinct_messages
        all_messages.extend(distinct_messages)

    message_count = len(all_messages)
    if not message_count:
        return {
            "session_count": len(sessions),
            "message_count": 0,
            "messages_by_session": messages_by_session,
        }

    progressive_sessions = sum(1 for messages in messages_by_session.values() if is_progressive_thread(messages))
    drift_sessions = sum(1 for messages in messages_by_session.values() if has_strong_drift(messages))
    scope_bundle_hits = sum(1 for message in all_messages if looks_scope_bundle(message))
    return {
        "session_count": len(sessions),
        "message_count": message_count,
        "session_input_count": len(messages_by_session),
        "goal_hits": sum(1 for message in all_messages if _has_goal_signal(message)),
        "context_hits": sum(1 for message in all_messages if _has_context_signal(message)),
        "output_hits": sum(1 for message in all_messages if _has_output_signal(message)),
        "constraint_hits": sum(1 for message in all_messages if _has_constraint_signal(message)),
        "completion_hits": sum(1 for message in all_messages if _has_completion_standard(message)),
        "structured_hits": sum(1 for message in all_messages if structured_prompt_score(message) >= 3),
        "stage_summary_hits": sum(1 for message in all_messages if _has_stage_summary_signal(message)),
        "progressive_sessions": progressive_sessions,
        "drift_sessions": drift_sessions,
        "scope_bundle_hits": scope_bundle_hits,
        "messages_by_session": messages_by_session,
    }


def _user_messages(session_events: Sequence[EventRecord]) -> List[str]:
    messages = [
        event_text(event)
        for event in session_events
        if event.event_type == "user_message" and event_text(event) and not is_internal_prompt(event_text(event))
    ]
    return _distinct_texts(messages)


def _score_goal_clarity(profile: Dict[str, object]) -> int:
    total = max(1, int(profile.get("message_count", 0) or 0))
    hits = int(profile.get("goal_hits", 0) or 0)
    structured = int(profile.get("structured_hits", 0) or 0)
    score = 7 + round(11 * hits / total) + min(2, structured)
    return _clamp_max(score, 20)


def _score_context_quality(profile: Dict[str, object]) -> int:
    total = max(1, int(profile.get("message_count", 0) or 0))
    hits = int(profile.get("context_hits", 0) or 0)
    progressive = int(profile.get("progressive_sessions", 0) or 0)
    score = 6 + round(12 * hits / total) + min(2, progressive)
    return _clamp_max(score, 20)


def _score_output_constraints(profile: Dict[str, object]) -> int:
    total = max(1, int(profile.get("message_count", 0) or 0))
    output_hits = int(profile.get("output_hits", 0) or 0)
    constraint_hits = int(profile.get("constraint_hits", 0) or 0)
    scope_bundle_hits = int(profile.get("scope_bundle_hits", 0) or 0)
    score = 5 + round(9 * output_hits / total) + round(5 * constraint_hits / total)
    score -= min(4, scope_bundle_hits)
    return _clamp_max(score, 20)


def _score_completion_standard(profile: Dict[str, object]) -> int:
    total = max(1, int(profile.get("message_count", 0) or 0))
    hits = int(profile.get("completion_hits", 0) or 0)
    structured = int(profile.get("structured_hits", 0) or 0)
    score = 3 + round(15 * hits / total) + min(2, structured)
    return _clamp_max(score, 20)


def _score_followup_rhythm(profile: Dict[str, object]) -> int:
    total = max(1, int(profile.get("message_count", 0) or 0))
    session_count = max(1, int(profile.get("session_input_count", 0) or 0))
    progressive = int(profile.get("progressive_sessions", 0) or 0)
    drift = int(profile.get("drift_sessions", 0) or 0)
    stage_summary = int(profile.get("stage_summary_hits", 0) or 0)
    scope_bundle_hits = int(profile.get("scope_bundle_hits", 0) or 0)
    messages_per_session = total / session_count
    score = 14 + min(3, progressive * 2) + min(3, stage_summary * 2)
    score -= min(8, drift * 5)
    score -= min(4, scope_bundle_hits)
    if messages_per_session > 6 and not stage_summary:
        score -= 3
    return _clamp_max(score, 20)


def _input_goal_detail(profile: Dict[str, object]) -> str:
    return f"{int(profile.get('goal_hits', 0) or 0)} / {int(profile.get('message_count', 0) or 0)} 条输入带有明确目标。"


def _input_context_detail(profile: Dict[str, object]) -> str:
    return f"{int(profile.get('context_hits', 0) or 0)} / {int(profile.get('message_count', 0) or 0)} 条输入补了背景、引用上文或说明当前材料。"


def _input_output_detail(profile: Dict[str, object]) -> str:
    return f"{int(profile.get('output_hits', 0) or 0)} 条输入说明输出形式，{int(profile.get('constraint_hits', 0) or 0)} 条输入说明约束。"


def _input_completion_detail(profile: Dict[str, object]) -> str:
    return f"{int(profile.get('completion_hits', 0) or 0)} / {int(profile.get('message_count', 0) or 0)} 条输入包含完成标准、验证方式或保留条件。"


def _input_rhythm_detail(profile: Dict[str, object]) -> str:
    return (
        f"{int(profile.get('progressive_sessions', 0) or 0)} 个渐进延展会话，"
        f"{int(profile.get('drift_sessions', 0) or 0)} 个强目标切换会话，"
        f"{int(profile.get('stage_summary_hits', 0) or 0)} 次阶段收束信号。"
    )


def _input_feedback_for_score(score: int, dimensions: List[ScoreDimension]) -> tuple[str, str]:
    best = max(dimensions, key=lambda d: d.score) if dimensions else None
    worst = min(dimensions, key=lambda d: d.score) if dimensions else None
    positive_map = {
        "目标清晰度": "今天不少输入能直接说清要 Codex 做什么。",
        "上下文充分度": "今天能持续引用上文和当前材料，长任务没有被误判成目标漂移。",
        "输出/约束明确度": "今天对输出形式或保留条件有一定约束，Codex 更容易按边界交付。",
        "完成标准": "今天的验收信号比较清楚，Codex 更容易知道什么时候该收尾。",
        "追问节奏": "今天的追问大多是沿主线推进，节奏是加分项。",
    }
    negative_map = {
        "目标清晰度": "有些输入还可以更早写出本轮目标。",
        "上下文充分度": "有些输入缺少材料、上文引用或当前判断，Codex 需要自己补语境。",
        "输出/约束明确度": "有些输入没有说清输出形式、范围或必须保留的内容。",
        "完成标准": "完成标准是今天最值得补的一项，尤其是复杂任务开头。",
        "追问节奏": "长会话可以增加阶段收束，避免连续延展后边界变模糊。",
    }
    positive = positive_map.get(best.label if best else "", "今天有一些输入是可复用的。")
    negative = negative_map.get(worst.label if worst else "", "明天可以把目标、输出和完成标准写得更清楚。")
    if score >= 80:
        positive = "今天输入质量很好，目标、上下文和追问节奏能支撑 Codex 直接推进。"
    elif score < 60:
        negative = "今天需要调整，主要要补的是输出形式、完成标准或阶段收束。"
    return positive, negative


def _input_score_reason(label: str, profile: Dict[str, object]) -> str:
    message_count = int(profile.get("message_count", 0) or 0)
    structured_hits = int(profile.get("structured_hits", 0) or 0)
    completion_hits = int(profile.get("completion_hits", 0) or 0)
    progressive_sessions = int(profile.get("progressive_sessions", 0) or 0)
    drift_sessions = int(profile.get("drift_sessions", 0) or 0)
    scope_bundle_hits = int(profile.get("scope_bundle_hits", 0) or 0)
    if label == "状态很好":
        prefix = "今天输入质量很好"
    elif label == "基本可用，有摩擦":
        prefix = "今天输入基本可用，但还有摩擦"
    else:
        prefix = "今天输入需要调整"
    details = [
        f"分析了 {message_count} 条用户输入",
        f"{structured_hits} 条结构化输入",
        f"{completion_hits} 条带完成标准或验证信号",
    ]
    if progressive_sessions:
        details.append(f"{progressive_sessions} 个会话是渐进延展")
    if drift_sessions:
        details.append(f"{drift_sessions} 个会话出现强目标切换")
    if scope_bundle_hits:
        details.append(f"{scope_bundle_hits} 条输入一次打包了多个交付")
    return f"{prefix}，主要因为" + "，".join(details[:5]) + "。工具调用、工具失败和 token 消耗只做背景统计，不参与这个分数。"


def _has_goal_signal(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "目标",
        "我想",
        "我要",
        "帮我",
        "执行计划",
        "实现",
        "修复",
        "分析",
        "生成",
        "升级",
        "改进",
        "review",
        "implement",
    )
    return len(message.strip()) >= 8 and any(marker in lowered or marker in message for marker in markers)


def _has_context_signal(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "基于",
        "上面",
        "这里",
        "目前",
        "当前",
        "过去",
        "今天",
        "这个",
        "这套",
        "报告",
        "代码",
        "事件库",
        "session",
        "recap",
        "codex",
    )
    return len(message.strip()) >= 24 or any(marker in lowered or marker in message for marker in markers) or bool(re.search(r"[/\\.][\w.-]+", message))


def _has_output_signal(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "输出",
        "报告",
        "markdown",
        "表格",
        "命令",
        "代码",
        "skill",
        "github",
        "逐句改写",
        "评分",
        "建议",
        "生成",
    )
    return any(marker in lowered or marker in message for marker in markers)


def _has_constraint_signal(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "约束",
        "保留",
        "不要",
        "不能",
        "只",
        "默认",
        "先",
        "本地",
        "不调用",
        "不上传",
        "最多",
    )
    return any(marker in lowered or marker in message for marker in markers)


def _has_completion_standard(message: str) -> bool:
    lowered = message.lower()
    markers = (
        "完成标准",
        "验收",
        "验证",
        "测试",
        "pytest",
        "通过",
        "保留",
        "包含",
        "可复制",
        "可运行",
        "成功",
        "不能出现",
    )
    return any(marker in lowered or marker in message for marker in markers)


def _has_stage_summary_signal(message: str) -> bool:
    markers = ("阶段收束", "总结当前", "当前结论", "未决问题", "下一轮", "先总结", "先复盘")
    return any(marker in message for marker in markers)


def _completion_standard_prompt(message: str) -> str:
    return (
        f"目标：{truncate(message, 70)}\n"
        "输出：请给我具体改动和可检查的结果。\n"
        "完成标准：实现后跑相关测试，并说明哪些内容已经验证、哪些还不确定。"
    )


def _scope_bundle_prompt(message: str) -> str:
    return (
        f"本轮目标：先完成这一个交付：{truncate(message, 60)}\n"
        "暂不展开：其他方向先列成候选清单。\n"
        "完成标准：先交付本轮结果，再告诉我下一轮最值得继续哪一项。"
    )


def _stage_summary_prompt(message: str) -> str:
    return (
        "先做一次阶段收束：请总结当前结论、未决问题和下一轮只做什么。\n"
        f"然后再继续：{truncate(message, 80)}"
    )


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


def _contains_any(message: str, markers: Sequence[str]) -> bool:
    return any(marker in message for marker in markers)


def _overall_label(score: int) -> str:
    if score >= 80:
        return "状态很好"
    if score >= 60:
        return "基本可用，有摩擦"
    return "需要调整"


def _clamp_max(value: int, max_value: int) -> int:
    return max(0, min(max_value, int(value)))


def _inline_text(text: str) -> str:
    return "；".join(part.strip() for part in text.splitlines() if part.strip())


_PROGRESSIVE_MARKERS = (
    "基于",
    "上面",
    "继续",
    "接下来",
    "进一步",
    "很好",
    "这个方向",
    "沿着",
    "围绕",
    "延伸",
    "深入",
)

_STRONG_DRIFT_MARKERS = (
    "换个话题",
    "完全不同",
    "另一个项目",
    "另一个问题",
)
