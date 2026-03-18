from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nanobot.agent.tools.base import Tool
from nanobot.monitor.types import MonitorSchedule

if TYPE_CHECKING:
    from nanobot.monitor.service import MonitorService


class MonitorTool(Tool):
    def __init__(self, service: "MonitorService"):
        self._service = service
        self._channel = "cli"
        self._chat_id = "direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._channel = channel
        self._chat_id = chat_id

    @property
    def name(self) -> str:
        return "monitor"

    @property
    def description(self) -> str:
        return (
            "Create and manage long-running monitor tasks. "
            "Actions: create, list, get, update, pause, resume, delete, run_now."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "get", "update", "pause", "resume", "delete", "run_now"],
                },
                "task_id": {"type": "string"},
                "title": {"type": "string"},
                "task_background": {"type": "string"},
                "pre_task": {"type": "string"},
                "monitor_task": {"type": "string"},
                "every_seconds": {"type": "integer", "minimum": 1},
                "cron_expr": {"type": "string"},
                "tz": {"type": "string"},
                "report_condition": {"type": "string"},
                "report_operation": {"type": "string"},
                "end_condition": {"type": "string"},
                "end_operation": {"type": "string"},
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        task_id: str | None = None,
        title: str = "",
        task_background: str = "",
        pre_task: str = "",
        monitor_task: str = "",
        every_seconds: int | None = None,
        cron_expr: str | None = None,
        tz: str | None = None,
        report_condition: str = "",
        report_operation: str = "",
        end_condition: str = "",
        end_operation: str = "",
        **kwargs: Any,
    ) -> str:
        if action == "create":
            return self._create(
                title=title,
                task_background=task_background,
                pre_task=pre_task,
                monitor_task=monitor_task,
                every_seconds=every_seconds,
                cron_expr=cron_expr,
                tz=tz,
                report_condition=report_condition,
                report_operation=report_operation,
                end_condition=end_condition,
                end_operation=end_operation,
            )
        if action == "list":
            return self._list()
        if action == "get":
            return self._get(task_id)
        if action == "update":
            return self._update(
                task_id=task_id,
                title=title,
                task_background=task_background,
                pre_task=pre_task,
                monitor_task=monitor_task,
                every_seconds=every_seconds,
                cron_expr=cron_expr,
                tz=tz,
                report_condition=report_condition,
                report_operation=report_operation,
                end_condition=end_condition,
                end_operation=end_operation,
            )
        if action == "pause":
            return self._pause(task_id)
        if action == "resume":
            return self._resume(task_id)
        if action == "delete":
            return self._delete(task_id)
        if action == "run_now":
            return await self._run_now(task_id)
        return f"Unknown action: {action}"

    def _create(
        self,
        title: str,
        task_background: str,
        pre_task: str,
        monitor_task: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        report_condition: str,
        report_operation: str,
        end_condition: str,
        end_operation: str,
    ) -> str:
        if not monitor_task:
            return "Error: monitor_task is required"
        if every_seconds:
            schedule = MonitorSchedule(kind="every", every_ms=every_seconds * 1000)
        elif cron_expr:
            schedule = MonitorSchedule(kind="cron", expr=cron_expr, tz=tz)
        else:
            return "Error: either every_seconds or cron_expr is required"

        task = self._service.create_task(
            title=title or monitor_task[:30],
            owner_channel=self._channel,
            owner_chat_id=self._chat_id,
            task_background=task_background,
            pre_task=pre_task,
            monitor_task=monitor_task,
            schedule=schedule,
            report_condition=report_condition,
            report_operation=report_operation,
            end_condition=end_condition,
            end_operation=end_operation,
        )
        next_run = task.state.next_run_at_ms or 0
        return f"Created monitor task '{task.title}' (id: {task.id}, next_run_at_ms: {next_run})"

    def _list(self) -> str:
        tasks = self._service.list_tasks(owner_channel=self._channel, owner_chat_id=self._chat_id)
        if not tasks:
            return "No monitor tasks."
        lines = []
        for t in tasks:
            lines.append(
                f"- {t.title} (id: {t.id}, status: {t.state.status}, next: {t.state.next_run_at_ms})"
            )
        return "Monitor tasks:\n" + "\n".join(lines)

    def _delete(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required"
        removed = self._service.delete_task(task_id)
        if removed:
            return f"Deleted monitor task {task_id}"
        return f"Monitor task {task_id} not found"

    def _get(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required"
        task = self._service.get_task(task_id)
        if not task:
            return f"Monitor task {task_id} not found"
        return (
            f"Monitor task:\n"
            f"- id: {task.id}\n"
            f"- title: {task.title}\n"
            f"- status: {task.state.status}\n"
            f"- next_run_at_ms: {task.state.next_run_at_ms}\n"
            f"- report_condition: {task.report_condition}\n"
            f"- end_condition: {task.end_condition}"
        )

    def _pause(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required"
        task = self._service.pause_task(task_id)
        if not task:
            return f"Monitor task {task_id} not found"
        return f"Paused monitor task {task_id}"

    def _resume(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required"
        task = self._service.resume_task(task_id)
        if not task:
            return f"Monitor task {task_id} not found"
        return f"Resumed monitor task {task_id}"

    def _update(
        self,
        task_id: str | None,
        title: str,
        task_background: str,
        pre_task: str,
        monitor_task: str,
        every_seconds: int | None,
        cron_expr: str | None,
        tz: str | None,
        report_condition: str,
        report_operation: str,
        end_condition: str,
        end_operation: str,
    ) -> str:
        if not task_id:
            return "Error: task_id is required"
        task = self._service.update_task(
            task_id=task_id,
            title=title if title else None,
            task_background=task_background if task_background else None,
            pre_task=pre_task if pre_task else None,
            monitor_task=monitor_task if monitor_task else None,
            every_seconds=every_seconds,
            cron_expr=cron_expr,
            tz=tz,
            report_condition=report_condition if report_condition else None,
            report_operation=report_operation if report_operation else None,
            end_condition=end_condition if end_condition else None,
            end_operation=end_operation if end_operation else None,
        )
        if not task:
            return f"Monitor task {task_id} not found"
        return f"Updated monitor task {task_id} (status: {task.state.status})"

    async def _run_now(self, task_id: str | None) -> str:
        if not task_id:
            return "Error: task_id is required"
        ok = await self._service.run_now(task_id)
        if ok:
            return f"Triggered monitor task {task_id}"
        return f"Monitor task {task_id} not runnable"
