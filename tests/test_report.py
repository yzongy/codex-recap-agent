from codex_recap_agent.analyzer import build_daily_report
from codex_recap_agent.models import SessionSummary
from codex_recap_agent.reporting import render_markdown


def test_render_report_contains_sections():
    report = build_daily_report(
        "2026-05-29",
        [
            SessionSummary(
                session_id="a",
                thread_name="Thread A",
                cwd="/tmp/project",
                started_at="2026-05-29T10:00:00Z",
                updated_at="2026-05-29T10:30:00Z",
                event_count=10,
                function_calls=3,
                tool_errors=1,
                tokens_input=100,
                tokens_output=50,
                last_message="Finish the refactor",
                raw={},
            )
        ],
        generated_at="2026-05-29T12:00:00Z",
    )
    markdown = render_markdown(report)
    assert "# Codex 协作复盘 2026-05-29" in markdown
    assert "## 今日评分" in markdown
    assert "总分:" in markdown
    assert "正反馈:" in markdown
    assert "负反馈:" in markdown
    assert "## 复盘建议" in markdown
    assert "## 下一步" in markdown
    assert "Thread A" in markdown


def test_daily_score_has_trend_and_dimensions():
    history = [
        SessionSummary(
            session_id="old",
            thread_name="Old thread",
            cwd="/tmp/a",
            started_at="2026-05-28T10:00:00Z",
            updated_at="2026-05-28T10:30:00Z",
            event_count=10,
            function_calls=120,
            tool_errors=20,
            tokens_input=8_000_000,
            tokens_output=500_000,
            last_message="still needs follow up?",
            raw={},
        ),
        SessionSummary(
            session_id="today",
            thread_name="Today",
            cwd="/tmp/a",
            started_at="2026-05-29T10:00:00Z",
            updated_at="2026-05-29T10:30:00Z",
            event_count=10,
            function_calls=12,
            tool_errors=0,
            tokens_input=100_000,
            tokens_output=20_000,
            last_message="已完成，ready for review",
            raw={},
        ),
    ]
    report = build_daily_report(
        "2026-05-29",
        [history[1]],
        generated_at="2026-05-29T12:00:00Z",
        history_sessions=history,
    )
    assert report.score is not None
    assert report.score.total > 0
    assert report.score.label in {"正向", "中性", "负向"}
    assert len(report.score.dimensions) == 4
    assert report.score.trend_label != "暂无趋势"


def test_empty_day_gets_zero_score():
    report = build_daily_report(
        "2026-06-01",
        [],
        generated_at="2026-06-01T12:00:00Z",
        history_sessions=[],
    )
    markdown = render_markdown(report)
    assert report.score is not None
    assert report.score.total == 0
    assert report.score.label == "负向"
    assert "总分: 0 / 100（负向）" in markdown
