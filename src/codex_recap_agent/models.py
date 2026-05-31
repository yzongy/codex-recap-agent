from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class SessionMeta:
    session_id: str
    timestamp: Optional[str]
    cwd: Optional[str]
    originator: Optional[str] = None
    cli_version: Optional[str] = None
    source: Optional[str] = None
    thread_source: Optional[str] = None
    model_provider: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EventRecord:
    session_id: str
    turn_id: Optional[str]
    event_type: str
    timestamp: str
    raw_type: str
    message: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionSummary:
    session_id: str
    thread_name: Optional[str]
    cwd: Optional[str]
    started_at: Optional[str]
    updated_at: Optional[str]
    event_count: int
    function_calls: int
    tool_errors: int
    tokens_input: int
    tokens_output: int
    last_message: Optional[str]
    raw: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DailyInsight:
    label: str
    detail: str


@dataclass
class ScoreDimension:
    label: str
    score: int
    detail: str


@dataclass
class DailyScore:
    total: int
    label: str
    trend_label: str
    trend_delta: int
    positive_feedback: str
    negative_feedback: str
    dimensions: List[ScoreDimension] = field(default_factory=list)


@dataclass
class DailyReport:
    report_date: str
    generated_at: str
    sessions: List[SessionSummary]
    insights: List[DailyInsight]
    score: Optional[DailyScore]
    metrics: Dict[str, Any]
    path: Optional[str] = None
