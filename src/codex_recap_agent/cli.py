from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from .analyzer import build_daily_report, filter_sessions_for_day
from .automation import ensure_daily_automation_script
from .config import get_app_paths
from .git_context import collect_git_summaries
from .parser import count_shell_snapshots, load_history_tails, load_thread_names, parse_session_file
from .reporting import render_markdown, write_report
from .storage import connect, fetch_events_for_sessions, fetch_sessions, insert_events, store_report, upsert_sessions


def _today() -> str:
    return date.today().isoformat()


def _normalize_date(value: str | None) -> str:
    if not value or value == "today":
        return _today()
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="codex-recap")
    sub = parser.add_subparsers(dest="command", required=True)

    backfill = sub.add_parser("backfill")
    backfill.add_argument("--days", type=int, default=30)
    backfill.add_argument("--since", default=None)

    ingest = sub.add_parser("ingest")
    ingest.add_argument("--paths", nargs="*", default=None)

    report = sub.add_parser("report")
    report.add_argument("--date", default="today")
    report.add_argument("--write", action="store_true", default=True)
    report.add_argument("--stdout", action="store_true")

    sub.add_parser("status")
    sub.add_parser("setup-automation")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = get_app_paths()
    app.reports_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(app.db_path)

    if args.command == "setup-automation":
        ensure_daily_automation_script(app.repo_root)
        print("automation updated")
        return 0

    if args.command == "ingest":
        return ingest_paths(app, conn, args.paths)

    if args.command == "backfill":
        since = args.since
        if not since:
            since = (datetime.now().astimezone() - timedelta(days=max(args.days, 0))).date().isoformat()
        return ingest_backfill(app, conn, since)

    if args.command == "report":
        target_date = _normalize_date(args.date)
        ingest_backfill(app, conn, (datetime.now().astimezone() - timedelta(days=30)).date().isoformat())
        report = generate_report(app, conn, target_date)
        if args.stdout:
            sys.stdout.write(render_markdown(report))
        if args.write:
            path = write_report(report, app.reports_dir)
            store_report(conn, report.report_date, report.generated_at, str(path), report.metrics)
            print(str(path))
        return 0

    if args.command == "status":
        sessions = fetch_sessions(conn)
        total = len(sessions)
        latest = sessions[0]["updated_at"] if sessions else None
        print(json.dumps({"sessions": total, "latest_updated_at": latest, "db": str(app.db_path)}, ensure_ascii=False))
        return 0

    return 1


def ingest_paths(app, conn, paths) -> int:
    thread_name_map = load_thread_names(app.session_index_path)
    if not paths:
        paths = [str(p) for p in sorted(app.sessions_dir.rglob("*.jsonl"))]
    summaries = []
    event_total = 0
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        _, events, summary = parse_session_file(path, thread_name_map)
        summaries.append(summary)
        event_total += insert_events(conn, events)
    upsert_sessions(conn, summaries)
    print(json.dumps({"sessions": len(summaries), "events_inserted": event_total}, ensure_ascii=False))
    return 0


def ingest_backfill(app, conn, since: str) -> int:
    thread_name_map = load_thread_names(app.session_index_path)
    paths = [
        p
        for root in (app.sessions_dir, app.archived_sessions_dir)
        for p in sorted(root.rglob("*.jsonl"))
        if _path_date(p) >= since
    ]
    summaries = []
    event_total = 0
    for path in paths:
        _, events, summary = parse_session_file(path, thread_name_map)
        summaries.append(summary)
        event_total += insert_events(conn, events)
    upsert_sessions(conn, summaries)
    print(json.dumps({"backfilled": len(summaries), "events_inserted": event_total, "since": since}, ensure_ascii=False))
    return 0


def generate_report(app, conn, target_date: str):
    sessions = fetch_sessions(conn)
    selected = [row_to_summary(row) for row in sessions]
    history_tails = load_history_tails(app.history_path)
    shell_snapshot_counts = count_shell_snapshots(app.shell_snapshots_dir)
    enrich_summaries(selected, history_tails, shell_snapshot_counts)
    daily = filter_sessions_for_day(selected, target_date)
    daily_events = fetch_events_for_sessions(conn, [session.session_id for session in daily])
    report = build_daily_report(target_date, daily, history_sessions=selected, events=daily_events)
    report.metrics["git"] = collect_git_summaries([session.cwd for session in daily])
    report.path = str(app.reports_dir / f"{target_date}.md")
    return report


def enrich_summaries(summaries, history_tails, shell_snapshot_counts):
    for summary in summaries:
        history_tail = history_tails.get(summary.session_id)
        if history_tail:
            summary.raw["history_tail"] = history_tail
            if not summary.last_message:
                summary.last_message = history_tail
        if summary.session_id in shell_snapshot_counts:
            summary.raw["shell_snapshot_count"] = shell_snapshot_counts[summary.session_id]


def row_to_summary(row):
    from .models import SessionSummary

    import json

    return SessionSummary(
        session_id=row["session_id"],
        thread_name=row["thread_name"],
        cwd=row["cwd"],
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        event_count=row["event_count"],
        function_calls=row["function_calls"],
        tool_errors=row["tool_errors"],
        tokens_input=row["tokens_input"],
        tokens_output=row["tokens_output"],
        last_message=row["last_message"],
        raw=json.loads(row["raw_json"]),
    )


def _path_date(path: Path) -> str:
    parts = path.parts
    for idx, part in enumerate(parts):
        if part.isdigit() and len(part) == 4 and idx + 2 < len(parts):
            year, month, day = part, parts[idx + 1], parts[idx + 2]
            if month.isdigit() and day.isdigit():
                return f"{year}-{month}-{day}"
    match = __import__("re").search(r"(\d{4})-(\d{2})-(\d{2})T", path.name)
    if match:
        return "-".join(match.groups())
    return "1970-01-01"


if __name__ == "__main__":
    raise SystemExit(main())
