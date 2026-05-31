from pathlib import Path

from codex_recap_agent.parser import parse_session_file
from codex_recap_agent.storage import connect, insert_events, upsert_sessions


def test_insert_events_is_idempotent(tmp_path):
    db = tmp_path / "recap.db"
    conn = connect(db)
    fixture = Path(__file__).parent / "fixtures" / "session_sample.jsonl"
    _, events, summary = parse_session_file(fixture, {"sess-1": "Sample thread"})
    upsert_sessions(conn, [summary])
    first = insert_events(conn, events)
    second = insert_events(conn, events)
    row_count = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    assert first > 0
    assert second == 0
    assert row_count == len(events)
