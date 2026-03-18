import asyncio
import json
import uuid
from dataclasses import dataclass
from typing import Any

from nanobot.agent.subagent import SubagentManager, SubagentReporter
from nanobot.bus.events import InboundMessage
from nanobot.bus.queue import MessageBus


@dataclass(frozen=True)
class SupervisorReportConfig:
    report_thoughts: bool = True
    report_tool_calls: bool = True
    report_tool_results: bool = False
    min_interval_seconds: float = 0.8
    max_payload_chars: int = 6_000


class SupervisorManager:
    def __init__(self, subagents: SubagentManager, bus: MessageBus):
        self.subagents = subagents
        self.bus = bus

    async def supervise(
        self,
        *,
        task: str,
        label: str | None = None,
        origin_channel: str = "cli",
        origin_chat_id: str = "direct",
        session_key: str | None = None,
        config: SupervisorReportConfig | None = None,
    ) -> str:
        cfg = config or SupervisorReportConfig()
        supervision_id = str(uuid.uuid4())[:8]
        reporter = _BusSubagentReporter(
            bus=self.bus,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            label=label or task[:30] + ("..." if len(task) > 30 else ""),
            supervision_id=supervision_id,
            config=cfg,
        )
        return await self.subagents.spawn(
            task=task,
            label=label,
            origin_channel=origin_channel,
            origin_chat_id=origin_chat_id,
            session_key=session_key,
            reporter=reporter,
        )


class _BusSubagentReporter(SubagentReporter):
    def __init__(
        self,
        *,
        bus: MessageBus,
        origin_channel: str,
        origin_chat_id: str,
        session_key: str | None,
        label: str,
        supervision_id: str,
        config: SupervisorReportConfig,
    ):
        self._bus = bus
        self._origin_channel = origin_channel
        self._origin_chat_id = origin_chat_id
        self._session_key = session_key
        self._label = label
        self._supervision_id = supervision_id
        self._cfg = config
        self._last_emit_at: float | None = None
        self._seq = 0
        self._queue: asyncio.Queue[tuple[InboundMessage, bool]] = asyncio.Queue(maxsize=200)
        self._pump_task = asyncio.create_task(self._pump())

    def on_started(
        self,
        *,
        task_id: str,
        task: str,
        label: str,
        origin_channel: str,
        origin_chat_id: str,
        session_key: str | None,
    ) -> None:
        self._emit(
            "start",
            {"task_id": task_id, "task": task, "label": label},
            bypass_throttle=True,
            persist=True,
            critical=True,
        )

    def on_thought(self, thought: str | None) -> None:
        if not self._cfg.report_thoughts:
            return
        if not thought:
            return
        self._emit("thought", {"thought": thought})

    def on_tool_call(self, tool_name: str, args: dict[str, Any]) -> None:
        if not self._cfg.report_tool_calls:
            return
        self._emit("tool_call", {"tool": tool_name, "args": args}, bypass_throttle=True)

    def on_tool_result(self, tool_name: str, result: str) -> None:
        if not self._cfg.report_tool_results:
            return
        self._emit("tool_result", {"tool": tool_name, "result": result}, bypass_throttle=True)

    def on_final(self, result: str, *, status: str) -> None:
        self._emit(
            "final",
            {"status": status, "result": result},
            bypass_throttle=True,
            persist=True,
            critical=True,
        )

    def _emit(
        self,
        kind: str,
        payload: dict[str, Any],
        *,
        bypass_throttle: bool = False,
        persist: bool = False,
        critical: bool = False,
    ) -> None:
        if not bypass_throttle and not self._should_emit():
            return

        self._seq += 1
        content = self._build_content(kind, payload, seq=self._seq)
        msg = InboundMessage(
            channel="system",
            sender_id="supervisor",
            chat_id=f"{self._origin_channel}:{self._origin_chat_id}",
            content=content,
            metadata={
                "_supervisor": True,
                "kind": kind,
                "label": self._label,
                "persist": persist,
                "session_key": self._session_key,
                "seq": self._seq,
                "supervision_id": self._supervision_id,
            },
        )
        self._enqueue(msg, critical=critical)

    def _enqueue(self, msg: InboundMessage, *, critical: bool) -> None:
        if critical:
            while self._queue.full():
                try:
                    self._queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
        try:
            self._queue.put_nowait((msg, critical))
        except asyncio.QueueFull:
            return

    async def _pump(self) -> None:
        while True:
            msg, critical = await self._queue.get()
            try:
                await self._bus.publish_inbound(msg)
            finally:
                self._queue.task_done()
                if critical and (msg.metadata or {}).get("kind") == "final":
                    break

    def _should_emit(self) -> bool:
        if self._cfg.min_interval_seconds <= 0:
            return True
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._last_emit_at is None or (now - self._last_emit_at) >= self._cfg.min_interval_seconds:
            self._last_emit_at = now
            return True
        return False

    def _build_content(self, kind: str, payload: dict[str, Any], *, seq: int) -> str:
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > self._cfg.max_payload_chars:
            raw = raw[: self._cfg.max_payload_chars] + "\n... (truncated)"
        return (
            "You are the main agent. You received a supervisor update for a background task.\n\n"
            f"Supervision ID: {self._supervision_id}\n"
            f"Label: {self._label}\n"
            f"Seq: {seq}\n"
            f"Kind: {kind}\n"
            f"Payload (json):\n{raw}\n\n"
            "Use this update together with the ongoing conversation and the original user goal.\n"
            "You may call tools if needed.\n"
            "If the user should be informed now, respond with a short progress update (1-2 sentences).\n"
            "If no user-visible output is needed, respond with an empty message."
        )
