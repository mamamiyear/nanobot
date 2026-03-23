from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from loguru import logger

from nanobot.providers.base import LLMProvider, LLMResponse
from nanobot.providers.registry import find_by_name
from nanobot.utils.helpers import strip_think


@dataclass(frozen=True)
class AutoFallbackModelSpec:
    model: str
    provider: str


class AutoFallbackProvider(LLMProvider):
    def __init__(
        self,
        default: AutoFallbackModelSpec,
        alternatives: list[AutoFallbackModelSpec] | None,
        *,
        provider_factory: Any,
        is_provider_available: Any,
    ):
        super().__init__(api_key=None, api_base=None)
        self._default = default
        self._alternatives = list(alternatives or [])
        self._provider_factory = provider_factory
        self._is_provider_available = is_provider_available
        self._active: AutoFallbackModelSpec | None = None
        self._active_provider: LLMProvider | None = None

    def get_default_model(self) -> str:
        return self._default.model

    def _reset_if_final(self, response: LLMResponse) -> None:
        if not response.has_tool_calls:
            self._active = None
            self._active_provider = None

    def _iter_specs(self) -> list[AutoFallbackModelSpec]:
        return [self._active or self._default] + self._alternatives

    def _build_provider(self, spec: AutoFallbackModelSpec) -> LLMProvider | None:
        provider_name = (spec.provider or "").strip()
        if not provider_name:
            return None
        if not self._is_provider_available(provider_name):
            return None
        if find_by_name(provider_name) is None:
            return None
        try:
            return self._provider_factory(model=spec.model, provider=provider_name)
        except Exception as e:
            logger.warning("Failed to build provider {} for model {}: {}", provider_name, spec.model, e)
            return None

    async def chat(self, messages: list[dict[str, Any]], tools=None, model=None, max_tokens=4096, temperature=0.7, reasoning_effort=None, tool_choice=None) -> LLMResponse:  # type: ignore[override]
        last_error: LLMResponse | None = None
        specs = self._iter_specs()
        for idx, spec in enumerate(specs):
            provider = self._active_provider if (self._active == spec and self._active_provider) else None
            if provider is None:
                provider = self._build_provider(spec)
            if provider is None:
                continue

            response = await provider.chat(
                messages=messages,
                tools=tools,
                model=spec.model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
            )
            if response.finish_reason != "error":
                if idx != 0:
                    self._active = spec
                    self._active_provider = provider
                self._reset_if_final(response)
                return response
            last_error = response

        if last_error is None:
            return LLMResponse(content="Error calling LLM: no available fallback providers", finish_reason="error")
        self._reset_if_final(last_error)
        return last_error

    async def chat_stream(self, messages: list[dict[str, Any]], tools=None, model=None, max_tokens=4096, temperature=0.7, reasoning_effort=None, tool_choice=None, on_content_delta=None) -> LLMResponse:  # type: ignore[override]
        emitted_visible = False
        buf = ""

        async def _wrapped_delta(delta: str) -> None:
            nonlocal emitted_visible, buf
            prev_clean = strip_think(buf)
            buf += delta
            new_clean = strip_think(buf)
            if new_clean[len(prev_clean):]:
                emitted_visible = True
            if on_content_delta:
                await on_content_delta(delta)

        last_error: LLMResponse | None = None
        specs = self._iter_specs()
        for idx, spec in enumerate(specs):
            provider = self._active_provider if (self._active == spec and self._active_provider) else None
            if provider is None:
                provider = self._build_provider(spec)
            if provider is None:
                continue

            response = await provider.chat_stream(
                messages=messages,
                tools=tools,
                model=spec.model,
                max_tokens=max_tokens,
                temperature=temperature,
                reasoning_effort=reasoning_effort,
                tool_choice=tool_choice,
                on_content_delta=_wrapped_delta,
            )

            if response.finish_reason != "error":
                if idx != 0:
                    self._active = spec
                    self._active_provider = provider
                self._reset_if_final(response)
                return response

            last_error = response
            if emitted_visible:
                break

        if last_error is None:
            return LLMResponse(content="Error calling LLM: no available fallback providers", finish_reason="error")
        self._reset_if_final(last_error)
        return last_error
