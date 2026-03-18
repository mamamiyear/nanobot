from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class MonitorSchedule:
    kind: Literal["every", "cron"]
    every_ms: int | None = None
    expr: str | None = None
    tz: str | None = None


@dataclass
class MonitorTaskState:
    status: Literal["running", "completed", "failed", "paused", "deleted"] = "running"
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    last_status: Literal["ok", "error"] | None = None
    last_error: str | None = None
    round_index: int = 0
    pre_done: bool = False
    report_count: int = 0
    error_streak: int = 0
    sent_report_ids: list[str] = field(default_factory=list)
    protected_rounds: list[int] = field(default_factory=list)


@dataclass
class MonitorTask:
    id: str
    title: str
    slug: str
    owner_channel: str
    owner_chat_id: str
    task_background: str
    pre_task: str
    monitor_task: str
    schedule: MonitorSchedule
    report_condition: str
    report_operation: str
    end_condition: str
    end_operation: str
    created_at_ms: int
    updated_at_ms: int
    state: MonitorTaskState = field(default_factory=MonitorTaskState)
    task_dir_name: str = ""


@dataclass
class MonitorStoreSnapshot:
    version: int = 1
    tasks: list[MonitorTask] = field(default_factory=list)
