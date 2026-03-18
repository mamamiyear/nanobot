from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Coroutine

from croniter import croniter
from loguru import logger

from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.monitor.evaluator import evaluate_condition_rule
from nanobot.monitor.reporter import build_report_message
from nanobot.monitor.store import MonitorStore
from nanobot.monitor.types import MonitorSchedule, MonitorTask, MonitorTaskState
from nanobot.utils.helpers import safe_filename


def _now_ms() -> int:
    return int(time.time() * 1000)


def _compute_next_run(schedule: MonitorSchedule, now_ms: int) -> int | None:
    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo

            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            c = croniter(schedule.expr, base_dt)
            next_dt = c.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            return None
    return None


class MonitorService:
    def __init__(
        self,
        store_dir: Path,
        bus: MessageBus,
        on_execute: Callable[[MonitorTask, str, str], Coroutine[Any, Any, str | None]] | None = None,
        condition_evaluator: Callable[[str, str, MonitorTask], Coroutine[Any, Any, bool]] | None = None,
        keep_recent_rounds: int = 10,
        max_error_streak: int = 3,
    ):
        self.store_dir = store_dir
        self.bus = bus
        self.on_execute = on_execute
        self.condition_evaluator = condition_evaluator
        self.keep_recent_rounds = max(1, keep_recent_rounds)
        self.max_error_streak = max(1, max_error_streak)
        self._store = MonitorStore(store_dir)
        self._tasks: dict[str, MonitorTask] = {}
        self._timer_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        self._running = True
        self._tasks = {task.id: task for task in self._store.list_tasks()}
        now = _now_ms()
        for task in self._tasks.values():
            self._recover_runtime_state(task)
            if task.state.status != "running":
                continue
            if not task.state.next_run_at_ms:
                task.state.next_run_at_ms = _compute_next_run(task.schedule, now)
                self._store.save_task(task)
        self._arm_timer()
        logger.info("Monitor service started with {} tasks", len(self._tasks))

    def stop(self) -> None:
        self._running = False
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None

    def list_tasks(self, owner_channel: str | None = None, owner_chat_id: str | None = None) -> list[MonitorTask]:
        tasks = list(self._tasks.values())
        if owner_channel and owner_chat_id:
            tasks = [t for t in tasks if t.owner_channel == owner_channel and t.owner_chat_id == owner_chat_id]
        return sorted(tasks, key=lambda t: t.created_at_ms)

    def get_task(self, task_id: str) -> MonitorTask | None:
        return self._tasks.get(task_id)

    def create_task(
        self,
        title: str,
        owner_channel: str,
        owner_chat_id: str,
        task_background: str,
        pre_task: str,
        monitor_task: str,
        schedule: MonitorSchedule,
        report_condition: str,
        report_operation: str,
        end_condition: str,
        end_operation: str,
    ) -> MonitorTask:
        now = _now_ms()
        task_id = str(uuid.uuid4())[:8]
        slug = safe_filename((title or monitor_task)[:36].lower().replace(" ", "-")) or "monitor-task"
        task_dir_name = f"{now}_{slug}_{task_id}"
        task = MonitorTask(
            id=task_id,
            title=title or monitor_task[:30],
            slug=slug,
            owner_channel=owner_channel,
            owner_chat_id=owner_chat_id,
            task_background=task_background,
            pre_task=pre_task,
            monitor_task=monitor_task,
            schedule=schedule,
            report_condition=report_condition,
            report_operation=report_operation,
            end_condition=end_condition,
            end_operation=end_operation,
            created_at_ms=now,
            updated_at_ms=now,
            state=MonitorTaskState(next_run_at_ms=_compute_next_run(schedule, now)),
            task_dir_name=task_dir_name,
        )
        self._tasks[task.id] = task
        self._store.save_task(task)
        self._store.append_event(task, {"type": "created", "at_ms": now})
        self._arm_timer()
        return task

    def update_task(
        self,
        task_id: str,
        title: str | None = None,
        task_background: str | None = None,
        pre_task: str | None = None,
        monitor_task: str | None = None,
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        report_condition: str | None = None,
        report_operation: str | None = None,
        end_condition: str | None = None,
        end_operation: str | None = None,
    ) -> MonitorTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None

        if title is not None:
            task.title = title
        if task_background is not None:
            task.task_background = task_background
        if pre_task is not None:
            task.pre_task = pre_task
        if monitor_task is not None:
            task.monitor_task = monitor_task
        if report_condition is not None:
            task.report_condition = report_condition
        if report_operation is not None:
            task.report_operation = report_operation
        if end_condition is not None:
            task.end_condition = end_condition
        if end_operation is not None:
            task.end_operation = end_operation

        if every_seconds is not None:
            task.schedule = MonitorSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr is not None:
            task.schedule = MonitorSchedule(kind="cron", expr=cron_expr, tz=tz)
        elif tz is not None and task.schedule.kind == "cron":
            task.schedule.tz = tz

        task.updated_at_ms = _now_ms()
        if task.state.status == "running":
            task.state.next_run_at_ms = _compute_next_run(task.schedule, _now_ms())
        self._store.save_task(task)
        self._store.append_event(task, {"type": "updated", "at_ms": task.updated_at_ms})
        self._arm_timer()
        return task

    def pause_task(self, task_id: str) -> MonitorTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task.state.status = "paused"
        task.state.next_run_at_ms = None
        task.updated_at_ms = _now_ms()
        self._store.save_task(task)
        self._store.append_event(task, {"type": "paused", "at_ms": task.updated_at_ms})
        self._arm_timer()
        return task

    def resume_task(self, task_id: str) -> MonitorTask | None:
        task = self._tasks.get(task_id)
        if not task:
            return None
        task.state.status = "running"
        task.state.next_run_at_ms = _compute_next_run(task.schedule, _now_ms())
        task.updated_at_ms = _now_ms()
        self._store.save_task(task)
        self._store.append_event(task, {"type": "resumed", "at_ms": task.updated_at_ms})
        self._arm_timer()
        return task

    def delete_task(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task:
            for disk_task in self._store.list_tasks():
                if disk_task.id == task_id:
                    self._store.delete_task(disk_task)
                    return True
            return False
        task.state.status = "deleted"
        task.updated_at_ms = _now_ms()
        self._store.append_event(task, {"type": "deleted", "at_ms": task.updated_at_ms})
        self._store.delete_task(task)
        del self._tasks[task_id]
        self._arm_timer()
        return True

    async def run_now(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.state.status != "running":
            return False
        await self._execute_task(task)
        return True

    def status(self) -> dict[str, Any]:
        return {
            "enabled": self._running,
            "tasks": len(self._tasks),
            "next_wake_at_ms": self._get_next_wake_ms(),
        }

    def _get_next_wake_ms(self) -> int | None:
        times = [t.state.next_run_at_ms for t in self._tasks.values() if t.state.status == "running" and t.state.next_run_at_ms]
        return min(times) if times else None

    def _arm_timer(self) -> None:
        if self._timer_task:
            self._timer_task.cancel()

        next_wake = self._get_next_wake_ms()
        if not next_wake or not self._running:
            return

        delay_ms = max(0, next_wake - _now_ms())
        delay_s = delay_ms / 1000

        async def tick():
            await asyncio.sleep(delay_s)
            if self._running:
                await self._on_timer()

        self._timer_task = asyncio.create_task(tick())

    async def _on_timer(self) -> None:
        now = _now_ms()
        due_tasks = [
            t for t in self._tasks.values()
            if t.state.status == "running" and t.state.next_run_at_ms and now >= t.state.next_run_at_ms
        ]
        for task in due_tasks:
            await self._execute_task(task)
        self._arm_timer()

    async def _execute_task(self, task: MonitorTask) -> None:
        start_ms = _now_ms()
        logger.info("Monitor: executing task '{}' ({})", task.title, task.id)

        try:
            if not task.state.pre_done and task.pre_task:
                pre_output = await self._run_phase(task, "pre", task.pre_task)
                task.state.pre_done = True
                await self._publish_report(
                    task=task,
                    report_type="pre_result",
                    phase="pre",
                    output=pre_output or "",
                    condition="pre_task completed",
                    operation=task.report_operation,
                    report_id=self._build_report_id(task, "pre_result", phase="pre"),
                    is_final=False,
                )
                self._mark_round_protected(task, task.state.round_index)

            monitor_output = await self._run_phase(task, "monitor", task.monitor_task)
            should_report = await self._should_trigger(task.report_condition, monitor_output or "", task)
            if should_report:
                sent = await self._publish_report(
                    task=task,
                    report_type="monitor_report",
                    phase="monitor",
                    output=monitor_output or "",
                    condition=task.report_condition,
                    operation=task.report_operation,
                    report_id=self._build_report_id(task, "monitor_report", phase="monitor"),
                    is_final=False,
                )
                if sent:
                    task.state.report_count += 1
                    self._mark_round_protected(task, task.state.round_index)

            should_end = await self._should_trigger(task.end_condition, monitor_output or "", task)
            if should_end:
                task.state.status = "completed"
                task.state.next_run_at_ms = None
                final_payload = {
                    "task_id": task.id,
                    "title": task.title,
                    "ended_at_ms": _now_ms(),
                    "reason": task.end_condition,
                    "last_output": monitor_output or "",
                    "round_index": task.state.round_index,
                }
                self._store.save_final_result(task, final_payload)
                await self._publish_report(
                    task=task,
                    report_type="final_result",
                    phase="monitor",
                    output=monitor_output or "",
                    condition=task.end_condition,
                    operation=task.end_operation,
                    report_id=self._build_report_id(task, "final_result", phase="monitor"),
                    is_final=True,
                )
                self._mark_round_protected(task, task.state.round_index)
            else:
                task.state.next_run_at_ms = _compute_next_run(task.schedule, _now_ms())

            task.state.last_status = "ok"
            task.state.last_error = None
            task.state.error_streak = 0
        except Exception as e:
            task.state.last_status = "error"
            task.state.last_error = str(e)
            task.state.error_streak += 1
            if task.state.error_streak >= self.max_error_streak:
                task.state.status = "failed"
                task.state.next_run_at_ms = None
                await self._publish_report(
                    task=task,
                    report_type="monitor_error",
                    phase="monitor",
                    output=str(e),
                    condition=f"error_streak >= {self.max_error_streak}",
                    operation=task.end_operation or task.report_operation,
                    report_id=self._build_report_id(task, "monitor_error", phase="monitor"),
                    is_final=False,
                )
            else:
                task.state.next_run_at_ms = _compute_next_run(task.schedule, _now_ms())
            logger.error("Monitor: task '{}' failed: {}", task.title, e)

        task.state.last_run_at_ms = start_ms
        task.updated_at_ms = _now_ms()
        self._store.save_task(task)
        self._compress_history(task)

    async def _run_phase(self, task: MonitorTask, phase: str, instruction: str) -> str | None:
        prompt = self._build_prompt(task, phase, instruction)
        output = None
        if self.on_execute:
            output = await self.on_execute(task, phase, prompt)
        task.state.round_index += 1
        self._store.append_session(task, phase, {
            "at_ms": _now_ms(),
            "phase": phase,
            "instruction": instruction,
            "prompt": prompt,
            "output": output or "",
            "round_index": task.state.round_index,
        })
        self._store.append_event(task, {
            "type": "phase_done",
            "phase": phase,
            "at_ms": _now_ms(),
            "round_index": task.state.round_index,
        })
        return output

    def _build_prompt(self, task: MonitorTask, phase: str, instruction: str) -> str:
        return (
            f"[Monitor Task Execution]\n"
            f"Task ID: {task.id}\n"
            f"Title: {task.title}\n"
            f"Phase: {phase}\n\n"
            f"Task Background:\n{task.task_background}\n\n"
            f"Pre Task:\n{task.pre_task or '(none)'}\n\n"
            f"Current Instruction:\n{instruction}\n\n"
            f"Report Condition:\n{task.report_condition or '(none)'}\n"
            f"End Condition:\n{task.end_condition or '(none)'}"
        )

    async def _publish_report(
        self,
        task: MonitorTask,
        report_type: str,
        phase: str,
        output: str,
        condition: str,
        operation: str,
        report_id: str,
        is_final: bool,
    ) -> bool:
        if report_id in task.state.sent_report_ids:
            return False
        content = build_report_message(
            report_type=report_type,
            task=task,
            phase=phase,
            output=output,
            condition=condition,
            operation=operation,
            report_id=report_id,
            is_final=is_final,
        )
        await self.bus.publish_inbound(InboundMessage(
            channel="system",
            sender_id="monitor",
            chat_id=f"{task.owner_channel}:{task.owner_chat_id}",
            content=content,
        ))
        task.state.sent_report_ids.append(report_id)
        self._store.append_event(task, {
            "type": "report_sent",
            "report_type": report_type,
            "phase": phase,
            "report_id": report_id,
            "round_index": task.state.round_index,
            "is_final": is_final,
            "at_ms": _now_ms(),
        })
        return True

    async def _should_trigger(self, condition: str, output: str, task: MonitorTask) -> bool:
        rule_result = evaluate_condition_rule(condition, output, task, now_dt=datetime.now().astimezone())
        if rule_result is not None:
            return rule_result
        if self.condition_evaluator:
            return await self.condition_evaluator(condition, output, task)
        return False

    @staticmethod
    def _build_report_id(task: MonitorTask, report_type: str, phase: str) -> str:
        return f"{task.id}:{phase}:{report_type}:{task.state.round_index}"

    @staticmethod
    def _mark_round_protected(task: MonitorTask, round_index: int) -> None:
        if round_index <= 0:
            return
        if round_index not in task.state.protected_rounds:
            task.state.protected_rounds.append(round_index)
            task.state.protected_rounds.sort()

    def _compress_history(self, task: MonitorTask) -> None:
        records = self._store.read_session(task, "monitor")
        if len(records) <= self.keep_recent_rounds:
            return
        keep_start = max(0, len(records) - self.keep_recent_rounds)
        keep = records[keep_start:]
        drop = records[:keep_start]
        kept_drop: list[dict] = []
        summaries: list[dict] = []
        protected = set(task.state.protected_rounds)
        for record in drop:
            round_index = int(record.get("round_index", 0) or 0)
            if round_index in protected:
                kept_drop.append(record)
                continue
            summaries.append(self._summarize_record(task, record))
        rewritten = kept_drop + keep
        if len(rewritten) == len(records):
            return
        self._store.append_summaries(task, summaries)
        self._store.rewrite_session(task, "monitor", rewritten)
        self._store.append_event(task, {
            "type": "history_compacted",
            "at_ms": _now_ms(),
            "dropped": len(records) - len(rewritten),
            "kept": len(rewritten),
        })

    @staticmethod
    def _summarize_record(task: MonitorTask, record: dict) -> dict:
        output = str(record.get("output", ""))
        short = output[:280] + ("..." if len(output) > 280 else "")
        return {
            "type": "round_summary",
            "task_id": task.id,
            "round_index": record.get("round_index"),
            "phase": record.get("phase"),
            "at_ms": record.get("at_ms"),
            "instruction": record.get("instruction", "")[:180],
            "output_summary": short,
        }

    def _recover_runtime_state(self, task: MonitorTask) -> None:
        event_path = self.store_dir / task.task_dir_name / "events.jsonl"
        if not event_path.exists():
            return
        report_ids: list[str] = []
        protected = set(task.state.protected_rounds)
        with open(event_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    evt = json.loads(line)
                except Exception:
                    continue
                rid = evt.get("report_id")
                if isinstance(rid, str) and rid:
                    report_ids.append(rid)
                if evt.get("type") == "report_sent" and evt.get("report_type") in {"monitor_report", "final_result", "pre_result"}:
                    rr = evt.get("round_index")
                    if isinstance(rr, int):
                        protected.add(rr)
        if report_ids:
            task.state.sent_report_ids = sorted(set(task.state.sent_report_ids + report_ids))
        if protected:
            task.state.protected_rounds = sorted(protected)
