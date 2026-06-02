from codex_recap_agent.analyzer import build_daily_report
from codex_recap_agent.models import EventRecord, SessionSummary
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
    assert "为什么:" in markdown
    assert "加分项:" in markdown
    assert "扣分项:" in markdown
    assert "## 今天的具体例子" in markdown
    assert "## 复盘建议" in markdown
    assert "## 下一步" in markdown
    assert "Thread A" in markdown
    assert "今天偏低" not in markdown


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
    assert report.score.label in {"状态很好", "基本可用，有摩擦", "需要调整"}
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
    assert report.score.label == "需要调整"
    assert "总分: 0 / 100（需要调整）" in markdown
    assert "## 今天的具体例子" in markdown
    assert "今天没有可分析会话，不能生成具体例子。" in markdown
    assert "今天偏低" not in markdown


def test_topic_drift_example_from_multiple_user_messages():
    session = SessionSummary(
        session_id="drift",
        thread_name="CS2009 analysis",
        cwd="/tmp/biotech",
        started_at="2026-06-01T10:00:00Z",
        updated_at="2026-06-01T11:00:00Z",
        event_count=12,
        function_calls=8,
        tool_errors=0,
        tokens_input=300,
        tokens_output=200,
        last_message="已完成分析",
        raw={},
    )
    events = [
        EventRecord("drift", None, "user_message", "2026-06-01T10:00:00Z", "message", message="深入分析 CS2009 ASCO abstract 的临床数据"),
        EventRecord("drift", None, "user_message", "2026-06-01T10:10:00Z", "message", message="再判断它是不是潜在 BIC"),
        EventRecord("drift", None, "user_message", "2026-06-01T10:20:00Z", "message", message="帮我写一篇微信公众号文章"),
        EventRecord("drift", None, "user_message", "2026-06-01T10:30:00Z", "message", message="顺便分析一下估值和股价影响"),
    ]

    report = build_daily_report("2026-06-01", [session], events=events)

    assert report.examples
    example = report.examples[0]
    assert example.example_type == "目标漂移"
    assert "CS2009 analysis" in example.session_label
    assert "微信公众号" in example.what_happened
    assert "拆成" in example.next_time


def test_repeated_failure_example_from_function_outputs():
    session = SessionSummary(
        session_id="fail",
        thread_name="Daily automation",
        cwd="/tmp/recap",
        started_at="2026-06-01T21:30:00Z",
        updated_at="2026-06-01T21:40:00Z",
        event_count=8,
        function_calls=4,
        tool_errors=3,
        tokens_input=100,
        tokens_output=50,
        last_message="still failing?",
        raw={},
    )
    events = [
        EventRecord("fail", None, "function_call_output", "2026-06-01T21:31:00Z", "tool_output", data={"call_id": "a", "output": "/bin/bash: codex-recap: command not found\nexit status 127"}),
        EventRecord("fail", None, "function_call_output", "2026-06-01T21:32:00Z", "tool_output", data={"call_id": "b", "output": "/bin/bash: codex-recap: command not found\nexit status 127"}),
        EventRecord("fail", None, "function_call_output", "2026-06-01T21:33:00Z", "tool_output", data={"call_id": "c", "output": "/bin/bash: codex-recap: command not found\nexit status 127"}),
    ]

    report = build_daily_report("2026-06-01", [session], events=events)

    failure = next(example for example in report.examples if example.example_type == "失败重试")
    assert "command not found" in failure.what_happened
    assert "诊断" in failure.next_time
