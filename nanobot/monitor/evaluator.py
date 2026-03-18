from __future__ import annotations

import re
from datetime import datetime

from loguru import logger

from nanobot.monitor.types import MonitorTask
from nanobot.providers.base import LLMProvider

_EVALUATE_CONDITION_TOOL = [
    {
        "type": "function",
        "function": {
            "name": "evaluate_condition",
            "description": "Evaluate whether a monitor condition is satisfied.",
            "parameters": {
                "type": "object",
                "properties": {
                    "matched": {
                        "type": "boolean",
                        "description": "true if condition is met, otherwise false",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short reason of the decision",
                    },
                },
                "required": ["matched"],
            },
        },
    }
]


def evaluate_condition_rule(
    condition: str,
    output: str,
    task: MonitorTask,
    now_dt: datetime | None = None,
) -> bool | None:
    text = condition.strip().lower()
    if not text:
        return False

    if text in {"always", "每次", "always report", "always true", "总是"}:
        return True
    if text in {"never", "never report", "always false", "从不"}:
        return False

    percent_match = re.search(
        r"(>=|<=|>|<|达到|超过|高于|低于|小于|不少于|不高于|不低于)?\s*(\d+(?:\.\d+)?)\s*%",
        condition,
    )
    if percent_match:
        op = percent_match.group(1) or ">="
        threshold = float(percent_match.group(2))
        values = [float(x) for x in re.findall(r"(\d+(?:\.\d+)?)\s*%", output)]
        if not values:
            return False
        value = max(values)
        if op in {">", "超过", "高于"}:
            return value > threshold
        if op in {">=", "达到", "不少于", "不低于"}:
            return value >= threshold
        if op in {"<", "低于", "小于"}:
            return value < threshold
        if op in {"<=", "不高于"}:
            return value <= threshold

    round_match = re.search(
        r"(?:round|轮次)\s*(>=|<=|>|<|=|==|达到|超过|不少于|不高于|小于)?\s*(\d+)",
        text,
    )
    if round_match:
        op = round_match.group(1) or ">="
        target = int(round_match.group(2))
        current = task.state.round_index
        if op in {">", "超过"}:
            return current > target
        if op in {">=", "达到", "不少于"}:
            return current >= target
        if op in {"<", "小于"}:
            return current < target
        if op in {"<=", "不高于"}:
            return current <= target
        return current == target

    time_match = re.search(r"(\d{1,2}):(\d{2})(?::(\d{2}))?", condition)
    if time_match:
        hh = int(time_match.group(1))
        mm = int(time_match.group(2))
        ss = int(time_match.group(3) or 0)
        current = now_dt or datetime.now().astimezone()
        target = current.replace(hour=hh, minute=mm, second=ss, microsecond=0)
        if any(k in text for k in ("before", "早于", "之前", "<")):
            return current < target
        return current >= target

    contain_match = re.search(r"(?:包含|contains?)\s+(.+)$", text)
    if contain_match:
        needle = contain_match.group(1).strip().strip("\"' ")
        return needle in output.lower()

    return None


async def evaluate_condition_with_llm(
    condition: str,
    output: str,
    task: MonitorTask,
    provider: LLMProvider,
    model: str,
) -> bool:
    try:
        response = await provider.chat_with_retry(
            messages=[
                {
                    "role": "system",
                    "content": "You are a strict condition evaluator for monitor tasks.",
                },
                {
                    "role": "user",
                    "content": (
                        f"Task: {task.title}\n"
                        f"Condition:\n{condition}\n\n"
                        f"Latest Output:\n{output}\n\n"
                        f"Round Index: {task.state.round_index}"
                    ),
                },
            ],
            tools=_EVALUATE_CONDITION_TOOL,
            model=model,
            temperature=0.0,
            max_tokens=256,
        )
        if not response.has_tool_calls:
            return False
        args = response.tool_calls[0].arguments
        return bool(args.get("matched", False))
    except Exception:
        logger.exception("evaluate_condition_with_llm failed")
        return False
