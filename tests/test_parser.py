from pathlib import Path

from codex_recap_agent.parser import load_thread_names, parse_session_file


def test_parse_session_fixture():
    fixture = Path(__file__).parent / "fixtures" / "session_sample.jsonl"
    _, events, summary = parse_session_file(fixture, {"sess-1": "Sample thread"})
    assert summary.session_id == "sess-1"
    assert summary.thread_name == "Sample thread"
    assert summary.function_calls == 1
    assert summary.tool_errors == 1
    assert summary.tokens_input == 10
    assert summary.tokens_output == 20
    assert summary.event_count == len(events)
    assert any(event.event_type == "agent_message" for event in events)
