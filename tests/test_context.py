from pathlib import Path

from codex_recap_agent.parser import count_shell_snapshots, load_history_tails


def test_history_tail_loading():
    fixture = Path(__file__).parent / "fixtures" / "history_sample.jsonl"
    tails = load_history_tails(fixture)
    assert tails["sess-1"] == "I can start with a quick guide to install/run it on your machine"


def test_shell_snapshot_counting(tmp_path):
    snap_dir = tmp_path / "shell_snapshots"
    snap_dir.mkdir()
    (snap_dir / "sess-1.1.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (snap_dir / "sess-1.2.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (snap_dir / "sess-2.1.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    counts = count_shell_snapshots(snap_dir)
    assert counts["sess-1"] == 2
    assert counts["sess-2"] == 1
