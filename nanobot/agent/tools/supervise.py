from typing import TYPE_CHECKING, Any

from nanobot.agent.supervisior import SupervisorReportConfig
from nanobot.agent.tools.base import Tool

if TYPE_CHECKING:
    from nanobot.agent.supervisior import SupervisorManager


class SuperviseTool(Tool):
    def __init__(self, manager: "SupervisorManager"):
        self._manager = manager
        self._origin_channel = "cli"
        self._origin_chat_id = "direct"
        self._session_key = "cli:direct"

    def set_context(self, channel: str, chat_id: str) -> None:
        self._origin_channel = channel
        self._origin_chat_id = chat_id
        self._session_key = f"{channel}:{chat_id}"

    @property
    def name(self) -> str:
        return "supervise"

    @property
    def description(self) -> str:
        return (
            "Spawn a supervised subagent for background execution, with progress updates. "
            "Use this when you want intermediate tool calls / thoughts to be observable by the main agent."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "The task for the subagent to complete"},
                "label": {"type": "string", "description": "Optional short label for the task"},
                "report_thoughts": {"type": "boolean", "description": "Report subagent thoughts (default true)"},
                "report_tool_calls": {"type": "boolean", "description": "Report tool calls (default true)"},
                "report_tool_results": {"type": "boolean", "description": "Report tool results (default false)"},
                "min_interval_seconds": {
                    "type": "number",
                    "description": "Minimum seconds between progress events (default 0.8)",
                    "minimum": 0,
                },
            },
            "required": ["task"],
        }

    async def execute(
        self,
        task: str,
        label: str | None = None,
        report_thoughts: bool | None = None,
        report_tool_calls: bool | None = None,
        report_tool_results: bool | None = None,
        min_interval_seconds: float | None = None,
        **kwargs: Any,
    ) -> str:
        cfg = SupervisorReportConfig(
            report_thoughts=True if report_thoughts is None else report_thoughts,
            report_tool_calls=True if report_tool_calls is None else report_tool_calls,
            report_tool_results=False if report_tool_results is None else report_tool_results,
            min_interval_seconds=0.8 if min_interval_seconds is None else float(min_interval_seconds),
        )
        return await self._manager.supervise(
            task=task,
            label=label,
            origin_channel=self._origin_channel,
            origin_chat_id=self._origin_chat_id,
            session_key=self._session_key,
            config=cfg,
        )
