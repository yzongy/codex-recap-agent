from __future__ import annotations

from pathlib import Path

from .analyzer import recommend_actions
from .models import DailyReport


def render_markdown(report: DailyReport) -> str:
    lines = [
        f"# Codex 协作复盘 {report.report_date}",
        "",
        f"- 生成时间: {report.generated_at}",
        f"- 会话数: {report.metrics.get('session_count', 0)}",
        f"- 工具调用: {report.metrics.get('function_calls', 0)}",
        f"- 工具/环境失败: {report.metrics.get('tool_errors', 0)}",
        f"- 输入 tokens: {report.metrics.get('tokens_input', 0)}",
        f"- 输出 tokens: {report.metrics.get('tokens_output', 0)}",
        "",
        "## 输入质量评分",
    ]
    if report.score:
        lines.extend(
            [
                f"- 总分: {report.score.total} / 100（{report.score.label}）",
                f"- 趋势: {report.score.trend_label}",
                f"- 为什么: {report.score.score_reason}",
                f"- 加分项: {report.score.positive_feedback}",
                f"- 扣分项: {report.score.negative_feedback}",
            ]
        )
        if report.score.dimensions:
            for dim in report.score.dimensions:
                lines.append(f"- {dim.label}: {dim.score} / {dim.max_score} - {dim.detail}")
    else:
        lines.append("- 今天没有评分数据。")
    lines.extend(
        [
            "",
            "## Token 统计",
            f"- 输入 tokens: {report.metrics.get('tokens_input', 0)}",
            f"- 输出 tokens: {report.metrics.get('tokens_output', 0)}",
            f"- 合计 tokens: {int(report.metrics.get('tokens_input', 0) or 0) + int(report.metrics.get('tokens_output', 0) or 0)}",
            "- 说明: token 是消耗统计，不参与输入质量评分。",
            "",
            "## 今日摘要",
        ]
    )
    if report.sessions:
        for session in report.sessions[:8]:
            label = session.thread_name or session.session_id
            lines.append(f"- `{label}` · `{session.cwd or 'unknown'}` · {session.event_count} 条事件")
    else:
        lines.append("- 今天没有找到可分析的会话。")
    lines.extend(["", "## 今天的具体例子"])
    if report.examples:
        for example in report.examples:
            lines.append(f"- **{example.example_type} · {example.session_label}**")
            lines.append(f"  - 工作区: `{example.cwd}`")
            lines.append(f"  - 例子: {example.what_happened}")
            lines.append(f"  - 影响: {example.why_it_matters}")
            lines.append(f"  - 下次改法: {example.next_time}")
    elif not report.sessions:
        lines.append("- 今天没有可分析会话，不能生成具体例子。")
    else:
        lines.append("- 今天没有抓到足够明确的具体例子，先看评分和摘要。")
    lines.extend(["", "## 逐句改写"])
    if report.prompt_reviews:
        for review in report.prompt_reviews:
            lines.append(f"- **{review.review_type} · {review.session_label}**")
            lines.append(f"  - 工作区: `{review.cwd}`")
            lines.append(f"  - 原输入: {_inline_text(review.original)}")
            lines.append(f"  - 问题点: {_inline_text(review.issue)}")
            lines.append(f"  - 更好的说法: {_inline_text(review.better_prompt)}")
            lines.append(f"  - 为什么更好: {_inline_text(review.why_better)}")
    elif not report.sessions:
        lines.append("- 今天没有可分析会话，不能生成逐句改写。")
    else:
        lines.append("- 今天没有抓到需要改写的输入。")
    lines.extend(["", "## 今天和你讨论"])
    if report.discussion_questions:
        for question in report.discussion_questions:
            lines.append(f"- {question}")
    else:
        lines.append("- 今天没有足够材料生成讨论问题。")
    lines.extend(["", "## 复盘建议"])
    if report.insights:
        for insight in report.insights:
            lines.append(f"- **{insight.label}**: {insight.detail}")
    else:
        lines.append("- 没有足够数据生成结构化建议。")
    lines.extend(["", "## 下一步",])
    for action in recommend_actions(report):
        lines.append(f"- {action}")
    lines.extend(["", "## Git 状态"])
    git_summaries = report.metrics.get("git", [])
    if git_summaries:
        for item in git_summaries:
            lines.append(f"- `{item.get('repo_root')}`: {item.get('changed_files')} 个未提交条目")
    else:
        lines.append("- 今天的会话没有匹配到可读取的 git 工作区。")
    lines.extend(["", "## 工作区",])
    seen = set()
    for session in report.sessions:
        cwd = session.cwd or "unknown"
        if cwd in seen:
            continue
        seen.add(cwd)
        lines.append(f"- `{cwd}`")
    return "\n".join(lines).rstrip() + "\n"


def _inline_text(text: str) -> str:
    return "；".join(part.strip() for part in text.splitlines() if part.strip())


def write_report(report: DailyReport, reports_dir: Path) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"{report.report_date}.md"
    path.write_text(render_markdown(report), encoding="utf-8")
    return path
