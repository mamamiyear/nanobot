from __future__ import annotations

from nanobot.monitor.types import MonitorTask


def build_report_message(
    report_type: str,
    task: MonitorTask,
    phase: str,
    output: str,
    condition: str,
    operation: str,
    report_id: str,
    is_final: bool = False,
) -> str:
    final_text = "true" if is_final else "false"
    return (
        f"[Monitor Report]\n"
        f"type: {report_type}\n"
        f"is_final: {final_text}\n"
        f"report_id: {report_id}\n"
        f"task_id: {task.id}\n"
        f"title: {task.title}\n"
        f"phase: {phase}\n\n"
        f"Task Background:\n{task.task_background}\n\n"
        f"Pre Task:\n{task.pre_task or '(none)'}\n\n"
        f"Monitor Task:\n{task.monitor_task}\n\n"
        f"Condition:\n{condition or '(none)'}\n\n"
        f"Operation:\n{operation or '(none)'}\n\n"
        f"Output:\n{output}\n\n"
        "Please process this report and respond to the user if needed. "
        "If monitor configuration should be changed, call the monitor tool."
    )
