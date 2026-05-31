from pathlib import Path

from codex_recap_agent.cli import _path_date


def test_path_date_from_session_tree():
    path = Path("/Users/example/.codex/sessions/2026/05/29/rollout.jsonl")
    assert _path_date(path) == "2026-05-29"


def test_path_date_from_archived_filename():
    path = Path("/Users/example/.codex/archived_sessions/rollout-2026-05-27T04-06-27-session.jsonl")
    assert _path_date(path) == "2026-05-27"
