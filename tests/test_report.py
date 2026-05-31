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
    assert "## 复盘建议" in markdown
    assert "## 下一步" in markdown
    assert "Thread A" in markdown
