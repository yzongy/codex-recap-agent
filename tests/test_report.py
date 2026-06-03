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
    assert "## 输入质量评分" in markdown
    assert "## Token 统计" in markdown
    assert "总分:" in markdown
    assert "为什么:" in markdown
    assert "加分项:" in markdown
    assert "扣分项:" in markdown
    assert "## 今天的具体例子" in markdown
    assert "## 复盘建议" in markdown
    assert "## 下一步" in markdown
    assert "Thread A" in markdown
    assert "今天偏低" not in markdown


def test_render_report_keeps_token_stats_and_adds_input_coach_sections():
    session = SessionSummary(
        session_id="input",
        thread_name="Input coaching",
        cwd="/tmp/recap",
        started_at="2026-06-02T10:00:00Z",
        updated_at="2026-06-02T10:30:00Z",
        event_count=8,
        function_calls=12,
        tool_errors=4,
        tokens_input=1234,
        tokens_output=567,
        last_message="完成",
        raw={},
    )
    events = [
        EventRecord("input", None, "user_message", "2026-06-02T10:00:00Z", "message", message="帮我把 recap 继续升级，建议要更具体"),
        EventRecord("input", None, "user_message", "2026-06-02T10:10:00Z", "message", message="基于上面的方向，继续关注自然语言输入质量"),
    ]

    report = build_daily_report("2026-06-02", [session], events=events)
    markdown = render_markdown(report)

    assert "## 输入质量评分" in markdown
    assert "## Token 统计" in markdown
    assert "- 输入 tokens: 1234" in markdown
    assert "- 输出 tokens: 567" in markdown
    assert "## 逐句改写" in markdown
    assert "## 今天和你讨论" in markdown
    assert "工具/环境失败" in markdown
    assert "工具/环境失败" not in report.score.score_reason


def test_input_quality_score_ignores_tool_errors():
    clean = SessionSummary(
        session_id="clean",
        thread_name="Clean env",
        cwd="/tmp/recap",
        started_at="2026-06-02T10:00:00Z",
        updated_at="2026-06-02T10:30:00Z",
        event_count=8,
        function_calls=2,
        tool_errors=0,
        tokens_input=100,
        tokens_output=50,
        last_message="完成",
        raw={},
    )
    noisy = SessionSummary(
        session_id="noisy",
        thread_name="Noisy env",
        cwd="/tmp/recap",
        started_at="2026-06-02T10:00:00Z",
        updated_at="2026-06-02T10:30:00Z",
        event_count=8,
        function_calls=40,
        tool_errors=30,
        tokens_input=100,
        tokens_output=50,
        last_message="完成",
        raw={},
    )
    clean_events = [
        EventRecord("clean", None, "user_message", "2026-06-02T10:00:00Z", "message", message="目标：升级日报\n输入：事件库\n输出：Markdown\n完成标准：pytest 通过且报告包含逐句改写"),
    ]
    noisy_events = [
        EventRecord("noisy", None, "user_message", "2026-06-02T10:00:00Z", "message", message="目标：升级日报\n输入：事件库\n输出：Markdown\n完成标准：pytest 通过且报告包含逐句改写"),
    ]

    clean_report = build_daily_report("2026-06-02", [clean], events=clean_events)
    noisy_report = build_daily_report("2026-06-02", [noisy], events=noisy_events)

    assert clean_report.score.total == noisy_report.score.total
    assert clean_report.score.dimensions == noisy_report.score.dimensions


def test_prompt_review_rewrites_missing_completion_standard():
    session = SessionSummary(
        session_id="rewrite",
        thread_name="Prompt rewrite",
        cwd="/tmp/recap",
        started_at="2026-06-02T10:00:00Z",
        updated_at="2026-06-02T10:30:00Z",
        event_count=8,
        function_calls=5,
        tool_errors=0,
        tokens_input=100,
        tokens_output=50,
        last_message="完成",
        raw={},
    )
    events = [
        EventRecord("rewrite", None, "user_message", "2026-06-02T10:00:00Z", "message", message="帮我把 recap 报告继续升级，意见更具体"),
    ]

    report = build_daily_report("2026-06-02", [session], events=events)
    markdown = render_markdown(report)

    assert report.prompt_reviews
    assert "完成标准" in report.prompt_reviews[0].issue
    assert "完成标准" in report.prompt_reviews[0].better_prompt
    assert "原输入" in markdown
    assert "更好的说法" in markdown


def test_progressive_extension_review_asks_for_stage_summary():
    session = SessionSummary(
        session_id="progressive-review",
        thread_name="Progressive prompt",
        cwd="/tmp/recap",
        started_at="2026-06-02T10:00:00Z",
        updated_at="2026-06-02T11:00:00Z",
        event_count=12,
        function_calls=8,
        tool_errors=0,
        tokens_input=200,
        tokens_output=100,
        last_message="完成",
        raw={},
    )
    events = [
        EventRecord("progressive-review", None, "user_message", "2026-06-02T10:00:00Z", "message", message="我想继续升级 recap，让它更像输入教练"),
        EventRecord("progressive-review", None, "user_message", "2026-06-02T10:10:00Z", "message", message="基于上面的方向，继续加入逐句改写"),
        EventRecord("progressive-review", None, "user_message", "2026-06-02T10:20:00Z", "message", message="很好，进一步让它每天主动和我讨论"),
        EventRecord("progressive-review", None, "user_message", "2026-06-02T10:30:00Z", "message", message="沿着这个方向，再保留 token 统计报告"),
    ]

    report = build_daily_report("2026-06-02", [session], events=events)

    assert any("阶段收束" in review.better_prompt for review in report.prompt_reviews)
    assert any("讨论" in question for question in report.discussion_questions)


def test_internal_prompts_are_not_scored_as_user_input():
    session = SessionSummary(
        session_id="internal",
        thread_name="Internal context",
        cwd="/tmp/recap",
        started_at="2026-06-02T10:00:00Z",
        updated_at="2026-06-02T10:30:00Z",
        event_count=8,
        function_calls=4,
        tool_errors=0,
        tokens_input=100,
        tokens_output=50,
        last_message="完成",
        raw={},
    )
    events = [
        EventRecord("internal", None, "user_message", "2026-06-02T10:00:00Z", "message", message="The following is the Codex agent history added since your last approval assessment. Continue the same task."),
        EventRecord("internal", None, "user_message", "2026-06-02T10:10:00Z", "message", message="帮我继续优化日报"),
    ]

    report = build_daily_report("2026-06-02", [session], events=events)

    assert "分析了 1 条用户输入" in report.score.score_reason
    assert not any("Codex agent history" in example.what_happened for example in report.examples)


def test_preserving_token_stats_is_treated_as_constraint_not_scope_bundle():
    session = SessionSummary(
        session_id="token",
        thread_name="Token report",
        cwd="/tmp/recap",
        started_at="2026-06-02T10:00:00Z",
        updated_at="2026-06-02T10:30:00Z",
        event_count=8,
        function_calls=4,
        tool_errors=0,
        tokens_input=100,
        tokens_output=50,
        last_message="完成",
        raw={},
    )
    events = [
        EventRecord("token", None, "user_message", "2026-06-02T10:00:00Z", "message", message="执行计划，另外保留现有的token统计报告"),
    ]

    report = build_daily_report("2026-06-02", [session], events=events)

    assert not any(review.review_type == "范围打包" for review in report.prompt_reviews)
    assert not any(example.example_type == "输入范围过大" for example in report.examples)


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
        events=[
            EventRecord("today", None, "user_message", "2026-05-29T10:00:00Z", "message", message="目标：优化日报\n输入：历史会话\n输出：Markdown\n完成标准：pytest 通过且报告包含输入质量评分"),
        ],
    )
    assert report.score is not None
    assert report.score.total > 0
    assert report.score.label in {"状态很好", "基本可用，有摩擦", "需要调整"}
    assert len(report.score.dimensions) == 5
    assert {dimension.max_score for dimension in report.score.dimensions} == {20}
    assert report.score.trend_label == "暂无输入质量趋势"


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
        EventRecord("drift", None, "user_message", "2026-06-01T10:10:00Z", "message", message="另外换个话题，帮我创建每日自动任务"),
        EventRecord("drift", None, "user_message", "2026-06-01T10:20:00Z", "message", message="再顺便写一篇微信公众号文章"),
        EventRecord("drift", None, "user_message", "2026-06-01T10:30:00Z", "message", message="然后改做估值和股价影响分析"),
    ]

    report = build_daily_report("2026-06-01", [session], events=events)

    assert report.examples
    example = report.examples[0]
    assert example.example_type == "目标漂移"
    assert "CS2009 analysis" in example.session_label
    assert "微信公众号" in example.what_happened
    assert "拆成" in example.next_time


def test_progressive_followups_are_not_treated_as_goal_drift():
    session = SessionSummary(
        session_id="progressive",
        thread_name="CS2009 deep dive",
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
        EventRecord("progressive", None, "user_message", "2026-06-01T10:00:00Z", "message", message="深入分析 CS2009 ASCO abstract 的临床数据"),
        EventRecord("progressive", None, "user_message", "2026-06-01T10:10:00Z", "message", message="基于上面的分析，再判断它是不是潜在 BIC"),
        EventRecord("progressive", None, "user_message", "2026-06-01T10:20:00Z", "message", message="很好，接下来进一步整理否定潜在 BIC 的标准"),
        EventRecord("progressive", None, "user_message", "2026-06-01T10:30:00Z", "message", message="继续沿着这个方向，比较同类创新药 ORR 数据"),
    ]

    report = build_daily_report("2026-06-01", [session], events=events)

    assert report.examples
    example = report.examples[0]
    assert example.example_type == "渐进延展"
    assert "不是目标漂移" in example.why_it_matters
    assert "阶段收束" in example.next_time


def test_long_project_iteration_is_progressive_extension():
    session = SessionSummary(
        session_id="project",
        thread_name="Codex recap agent",
        cwd="/tmp/recap",
        started_at="2026-06-01T10:00:00Z",
        updated_at="2026-06-01T12:00:00Z",
        event_count=20,
        function_calls=20,
        tool_errors=0,
        tokens_input=500,
        tokens_output=300,
        last_message="已完成",
        raw={},
    )
    events = [
        EventRecord("project", None, "user_message", "2026-06-01T10:00:00Z", "message", message="我想做一个 Codex 协作复盘 agent"),
        EventRecord("project", None, "user_message", "2026-06-01T10:10:00Z", "message", message="很好，帮我生成这个 skill"),
        EventRecord("project", None, "user_message", "2026-06-01T10:20:00Z", "message", message="我怎么知道这套 skill 有没有正在被使用"),
        EventRecord("project", None, "user_message", "2026-06-01T10:30:00Z", "message", message="很好，先把项目推到 GitHub"),
        EventRecord("project", None, "user_message", "2026-06-01T10:40:00Z", "message", message="我觉得目前的 recap 还需要迭代，把报告从泛泛建议改成具体例子"),
        EventRecord("project", None, "user_message", "2026-06-01T10:50:00Z", "message", message="我特别关注的是如何与 Codex 交互，自然语言的输入"),
    ]

    report = build_daily_report("2026-06-01", [session], events=events)

    assert report.examples[0].example_type == "渐进延展"
    assert "阶段收束" in report.examples[0].next_time


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

    failure = next(example for example in report.examples if example.example_type == "工具/环境摩擦")
    assert "command not found" in failure.what_happened
    assert "不算你的操作问题" in failure.why_it_matters
    assert "诊断" in failure.next_time


def test_language_input_examples_are_prioritized_over_tool_friction():
    drift = SessionSummary(
        session_id="drift",
        thread_name="Strategy thread",
        cwd="/tmp/work",
        started_at="2026-06-01T09:00:00Z",
        updated_at="2026-06-01T10:00:00Z",
        event_count=10,
        function_calls=5,
        tool_errors=0,
        tokens_input=300,
        tokens_output=200,
        last_message="完成",
        raw={},
    )
    structured = SessionSummary(
        session_id="structured",
        thread_name="Recap report",
        cwd="/tmp/work",
        started_at="2026-06-01T11:00:00Z",
        updated_at="2026-06-01T11:30:00Z",
        event_count=8,
        function_calls=2,
        tool_errors=0,
        tokens_input=200,
        tokens_output=100,
        last_message="已完成",
        raw={},
    )
    failure = SessionSummary(
        session_id="failure",
        thread_name="Tool setup",
        cwd="/tmp/work",
        started_at="2026-06-01T12:00:00Z",
        updated_at="2026-06-01T12:30:00Z",
        event_count=8,
        function_calls=4,
        tool_errors=3,
        tokens_input=100,
        tokens_output=50,
        last_message="still failing?",
        raw={},
    )
    events = [
        EventRecord("drift", None, "user_message", "2026-06-01T09:00:00Z", "message", message="帮我分析这个产品方向"),
        EventRecord("drift", None, "user_message", "2026-06-01T09:10:00Z", "message", message="再顺便写成融资 pitch 的版本"),
        EventRecord("drift", None, "user_message", "2026-06-01T09:20:00Z", "message", message="然后改成公众号文章"),
        EventRecord("structured", None, "user_message", "2026-06-01T11:00:00Z", "message", message="目标：升级日报\n输入：事件库\n输出：Markdown\n完成标准：pytest 通过且报告包含具体例子"),
        EventRecord("failure", None, "function_call_output", "2026-06-01T12:01:00Z", "tool_output", data={"output": "/bin/bash: codex-recap: command not found\nexit status 127"}),
        EventRecord("failure", None, "function_call_output", "2026-06-01T12:02:00Z", "tool_output", data={"output": "/bin/bash: codex-recap: command not found\nexit status 127"}),
    ]

    report = build_daily_report("2026-06-01", [drift, structured, failure], events=events)
    example_types = [example.example_type for example in report.examples]
    markdown = render_markdown(report)

    assert "输入范围过大" in example_types
    assert "正向输入" in example_types
    assert "工具/环境摩擦" not in example_types
    assert "同类失败出现两次后" not in markdown


def test_tool_errors_are_not_framed_as_user_blame():
    session = SessionSummary(
        session_id="env",
        thread_name="Automation setup",
        cwd="/tmp/recap",
        started_at="2026-06-01T21:30:00Z",
        updated_at="2026-06-01T21:40:00Z",
        event_count=8,
        function_calls=10,
        tool_errors=8,
        tokens_input=100,
        tokens_output=50,
        last_message="完成",
        raw={},
    )

    report = build_daily_report("2026-06-01", [session])
    markdown = render_markdown(report)

    assert "不直接归因于你" in markdown
    assert "失败输出偏多，最好先诊断再继续跑" not in markdown
