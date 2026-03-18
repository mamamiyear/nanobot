from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from nanobot.monitor.types import MonitorSchedule, MonitorTask, MonitorTaskState
from nanobot.utils.helpers import ensure_dir


class MonitorStore:
    def __init__(self, base_dir: Path):
        self.base_dir = ensure_dir(base_dir)

    def list_tasks(self) -> list[MonitorTask]:
        tasks: list[MonitorTask] = []
        for task_json in self.base_dir.glob("*/task.json"):
            try:
                raw = json.loads(task_json.read_text(encoding="utf-8"))
                tasks.append(self._decode_task(raw, task_json.parent.name))
            except Exception:
                continue
        return sorted(tasks, key=lambda x: x.created_at_ms)

    def save_task(self, task: MonitorTask) -> None:
        task_dir = ensure_dir(self.base_dir / task.task_dir_name)
        data = self._encode_task(task)
        tmp_path = task_dir / "task.json.tmp"
        final_path = task_dir / "task.json"
        tmp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(final_path)

    def append_event(self, task: MonitorTask, event: dict) -> None:
        task_dir = ensure_dir(self.base_dir / task.task_dir_name)
        p = task_dir / "events.jsonl"
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def append_session(self, task: MonitorTask, phase: str, record: dict) -> None:
        task_dir = ensure_dir(self.base_dir / task.task_dir_name)
        filename = "session_pre.jsonl" if phase == "pre" else "session_monitor.jsonl"
        p = task_dir / filename
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def read_session(self, task: MonitorTask, phase: str) -> list[dict]:
        task_dir = ensure_dir(self.base_dir / task.task_dir_name)
        filename = "session_pre.jsonl" if phase == "pre" else "session_monitor.jsonl"
        p = task_dir / filename
        if not p.exists():
            return []
        records: list[dict] = []
        with open(p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except Exception:
                    continue
        return records

    def rewrite_session(self, task: MonitorTask, phase: str, records: list[dict]) -> None:
        task_dir = ensure_dir(self.base_dir / task.task_dir_name)
        filename = "session_pre.jsonl" if phase == "pre" else "session_monitor.jsonl"
        p = task_dir / filename
        tmp = task_dir / f"{filename}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        Path(tmp).replace(p)

    def append_summaries(self, task: MonitorTask, summaries: list[dict]) -> None:
        if not summaries:
            return
        task_dir = ensure_dir(self.base_dir / task.task_dir_name)
        p = task_dir / "summaries.jsonl"
        with open(p, "a", encoding="utf-8") as f:
            for summary in summaries:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")

    def save_final_result(self, task: MonitorTask, data: dict) -> None:
        task_dir = ensure_dir(self.base_dir / task.task_dir_name)
        p = task_dir / "final_result.json"
        tmp = task_dir / "final_result.json.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)

    def delete_task(self, task: MonitorTask) -> None:
        task_dir = self.base_dir / task.task_dir_name
        if not task_dir.exists():
            return
        for p in sorted(task_dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            else:
                p.rmdir()
        task_dir.rmdir()

    @staticmethod
    def _encode_task(task: MonitorTask) -> dict:
        data = asdict(task)
        data["schedule"] = asdict(task.schedule)
        data["state"] = asdict(task.state)
        return data

    @staticmethod
    def _decode_task(raw: dict, task_dir_name: str) -> MonitorTask:
        schedule = MonitorSchedule(
            kind=raw["schedule"]["kind"],
            every_ms=raw["schedule"].get("every_ms"),
            expr=raw["schedule"].get("expr"),
            tz=raw["schedule"].get("tz"),
        )
        state = raw.get("state", {})
        return MonitorTask(
            id=raw["id"],
            title=raw["title"],
            slug=raw.get("slug", raw["title"][:30]),
            owner_channel=raw.get("owner_channel", "cli"),
            owner_chat_id=raw.get("owner_chat_id", "direct"),
            task_background=raw.get("task_background", ""),
            pre_task=raw.get("pre_task", ""),
            monitor_task=raw.get("monitor_task", ""),
            schedule=schedule,
            report_condition=raw.get("report_condition", ""),
            report_operation=raw.get("report_operation", ""),
            end_condition=raw.get("end_condition", ""),
            end_operation=raw.get("end_operation", ""),
            created_at_ms=raw.get("created_at_ms", 0),
            updated_at_ms=raw.get("updated_at_ms", 0),
            state=MonitorTaskState(
                status=state.get("status", "running"),
                next_run_at_ms=state.get("next_run_at_ms"),
                last_run_at_ms=state.get("last_run_at_ms"),
                last_status=state.get("last_status"),
                last_error=state.get("last_error"),
                round_index=state.get("round_index", 0),
                pre_done=state.get("pre_done", False),
                report_count=state.get("report_count", 0),
                error_streak=state.get("error_streak", 0),
                sent_report_ids=state.get("sent_report_ids", []),
                protected_rounds=state.get("protected_rounds", []),
            ),
            task_dir_name=raw.get("task_dir_name", task_dir_name),
        )
