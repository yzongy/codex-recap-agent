from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from .models import EventRecord, SessionMeta, SessionSummary


def read_jsonl(path: Path) -> Iterator[dict]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def load_thread_names(session_index_path: Path) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    for row in read_jsonl(session_index_path):
        session_id = row.get("id")
        thread_name = row.get("thread_name")
        if session_id and thread_name:
            mapping[session_id] = thread_name
    return mapping


def load_history_tails(history_path: Path) -> Dict[str, str]:
    tails: Dict[str, str] = {}
    for row in read_jsonl(history_path):
        session_id = row.get("session_id")
        text = row.get("text")
        if session_id and isinstance(text, str) and text.strip():
            tails[session_id] = text.strip()
    return tails


def count_shell_snapshots(shell_snapshots_dir: Path) -> Dict[str, int]:
    counts: Dict[str, int] = defaultdict(int)
    if not shell_snapshots_dir.exists():
        return {}
    for path in shell_snapshots_dir.glob("*.sh"):
        session_id = path.name.split(".", 1)[0]
        if session_id:
            counts[session_id] += 1
    return dict(counts)


def parse_session_file(path: Path, thread_name_map: Optional[Dict[str, str]] = None) -> Tuple[SessionMeta, List[EventRecord], SessionSummary]:
    rows = list(read_jsonl(path))
    session_meta_row = next((row for row in rows if row.get("type") == "session_meta"), {})
    session_meta_payload = session_meta_row.get("payload", {})
    session_id = session_meta_payload.get("id") or path.stem
    cwd = session_meta_payload.get("cwd")
    thread_name = (thread_name_map or {}).get(session_id)

    meta = SessionMeta(
        session_id=session_id,
        timestamp=session_meta_payload.get("timestamp"),
        cwd=cwd,
        originator=session_meta_payload.get("originator"),
        cli_version=session_meta_payload.get("cli_version"),
        source=session_meta_payload.get("source"),
        thread_source=session_meta_payload.get("thread_source"),
        model_provider=session_meta_payload.get("model_provider"),
        raw=session_meta_payload,
    )

    events: List[EventRecord] = []
    function_calls = 0
    tool_errors = 0
    tokens_input = 0
    tokens_output = 0
    last_message = None
    started_at = None
    updated_at = None

    for row in rows:
        timestamp = row.get("timestamp") or session_meta_row.get("timestamp") or ""
        payload = row.get("payload", {})
        raw_type = row.get("type", "")
        turn_id = payload.get("turn_id")
        event_type = payload.get("type") or raw_type
        message = payload.get("message")
        if event_type == "task_started":
            started_at = _ts_from_epoch(payload.get("started_at")) or timestamp
        if raw_type == "turn_context":
            updated_at = timestamp
        if event_type == "function_call":
            function_calls += 1
        if event_type == "function_call_output":
            output = _to_text(payload.get("output", ""))
            exit_code = _extract_exit_code(output)
            if exit_code is not None and exit_code != 0:
                tool_errors += 1
        if event_type == "token_count":
            info = payload.get("info") or {}
            usage = info.get("last_token_usage", {})
            tokens_input += int(usage.get("input_tokens", 0) or 0)
            tokens_output += int(usage.get("output_tokens", 0) or 0)
        if event_type in {"user_message", "agent_message"} and message:
            last_message = message.strip()
        if raw_type == "response_item" and payload.get("type") == "function_call_output":
            data = payload
        else:
            data = payload
        if raw_type in {"event_msg", "response_item", "turn_context"}:
            events.append(
                EventRecord(
                    session_id=session_id,
                    turn_id=turn_id,
                    event_type=event_type,
                    timestamp=timestamp,
                    raw_type=raw_type,
                    message=message.strip() if isinstance(message, str) else None,
                    data=data,
                )
            )

    summary = SessionSummary(
        session_id=session_id,
        thread_name=thread_name,
        cwd=cwd,
        started_at=started_at or meta.timestamp,
        updated_at=updated_at or meta.timestamp,
        event_count=len(events),
        function_calls=function_calls,
        tool_errors=tool_errors,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        last_message=last_message,
        raw=meta.raw,
    )
    return meta, events, summary


def _ts_from_epoch(epoch: Optional[int]) -> Optional[str]:
    if not epoch:
        return None
    from datetime import datetime, timezone

    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _to_text(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except TypeError:
        return str(value)


def _extract_exit_code(text: str) -> Optional[int]:
    patterns = [
        r"exit(?:ed)?\s+code\s+(-?\d+)",
        r"exited\s+with\s+code\s+(-?\d+)",
        r"Process\s+exited\s+with\s+code\s+(-?\d+)",
    ]
    lowered = text.lower()
    for pattern in patterns:
        match = re.search(pattern, lowered)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                return None
    return None
