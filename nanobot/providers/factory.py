"""Create LLM providers from config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from nanobot.config.schema import Config
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.providers.registry import find_by_name


@dataclass(frozen=True)
class ProviderSnapshot:
    provider: LLMProvider
    model: str
    context_window_tokens: int
    signature: tuple[object, ...]


def _freeze(value: object) -> object:
    """Convert nested config values into a hashable, order-stable structure."""
    if isinstance(value, dict):
        return tuple(sorted((k, _freeze(v)) for k, v in value.items()))
    if isinstance(value, list | tuple):
        return tuple(_freeze(v) for v in value)
    return value


def _normalize_provider_name(name: str | None) -> str:
    return (name or "").strip().lower().replace("-", "_")


def _generation_settings(config: Config) -> GenerationSettings:
    defaults = config.agents.defaults
    return GenerationSettings(
        temperature=defaults.temperature,
        max_tokens=defaults.max_tokens,
        reasoning_effort=defaults.reasoning_effort,
    )


def _provider_config_signature(config: Config, provider_name: str) -> tuple[object, ...]:
    provider_key = _normalize_provider_name(provider_name)
    provider_cfg = getattr(config.providers, provider_key, None)
    return (
        provider_key,
        _freeze(provider_cfg.model_dump() if provider_cfg else None),
    )


def _is_provider_available(config: Config, provider_name: str) -> bool:
    provider_key = _normalize_provider_name(provider_name)
    if not provider_key or provider_key == "autofallback":
        return False

    spec = find_by_name(provider_key)
    if spec is None:
        return False

    provider_cfg = getattr(config.providers, spec.name, None)
    if spec.is_oauth:
        return True
    if spec.is_local:
        return bool(getattr(provider_cfg, "api_base", None)) or bool(spec.default_api_base)
    if spec.name == "azure_openai":
        return bool(getattr(provider_cfg, "api_key", None)) and bool(
            getattr(provider_cfg, "api_base", None)
        )
    if spec.is_direct:
        return bool(getattr(provider_cfg, "api_base", None)) or bool(spec.default_api_base)
    return bool(getattr(provider_cfg, "api_key", None))


def _make_concrete_provider(config: Config, *, model: str, provider: str) -> LLMProvider:
    provider_key = _normalize_provider_name(provider)
    if not provider_key or provider_key == "autofallback":
        raise ValueError("Invalid provider name for autofallback target.")

    spec = find_by_name(provider_key)
    if spec is None:
        raise ValueError(f"Unknown provider '{provider}'.")

    provider_cfg = getattr(config.providers, spec.name, None)
    backend = spec.backend
    api_base = getattr(provider_cfg, "api_base", None) or spec.default_api_base or None

    if backend == "azure_openai":
        if not provider_cfg or not provider_cfg.api_key or not provider_cfg.api_base:
            raise ValueError("Azure OpenAI requires api_key and api_base in config.")
    elif backend == "openai_compat" and not model.startswith("bedrock/"):
        needs_key = not (provider_cfg and provider_cfg.api_key)
        exempt = spec.is_oauth or spec.is_local or spec.is_direct
        if needs_key and not exempt:
            raise ValueError(f"No API key configured for provider '{spec.name}'.")

    if backend == "openai_codex":
        from nanobot.providers.openai_codex_provider import OpenAICodexProvider

        provider_impl: LLMProvider = OpenAICodexProvider(default_model=model)
    elif backend == "azure_openai":
        from nanobot.providers.azure_openai_provider import AzureOpenAIProvider

        provider_impl = AzureOpenAIProvider(
            api_key=provider_cfg.api_key,
            api_base=provider_cfg.api_base,
            default_model=model,
        )
    elif backend == "github_copilot":
        from nanobot.providers.github_copilot_provider import GitHubCopilotProvider

        provider_impl = GitHubCopilotProvider(default_model=model)
    elif backend == "anthropic":
        from nanobot.providers.anthropic_provider import AnthropicProvider

        provider_impl = AnthropicProvider(
            api_key=provider_cfg.api_key if provider_cfg else None,
            api_base=api_base,
            default_model=model,
            extra_headers=provider_cfg.extra_headers if provider_cfg else None,
        )
    else:
        from nanobot.providers.openai_compat_provider import OpenAICompatProvider

        provider_impl = OpenAICompatProvider(
            api_key=provider_cfg.api_key if provider_cfg else None,
            api_base=api_base,
            default_model=model,
            extra_headers=provider_cfg.extra_headers if provider_cfg else None,
            spec=spec,
            extra_body=provider_cfg.extra_body if provider_cfg else None,
        )

    provider_impl.generation = _generation_settings(config)
    return provider_impl


def make_provider(config: Config) -> LLMProvider:
    """Create the LLM provider implied by config."""
    defaults = config.agents.defaults
    if defaults.provider == "autofallback":
        from nanobot.providers.fallback_provider import (
            AutoFallbackModelSpec,
            AutoFallbackProvider,
        )

        fallback_cfg = config.providers.autofallback
        if fallback_cfg is None:
            raise ValueError("providers.autofallback is not configured.")

        provider = AutoFallbackProvider(
            default=AutoFallbackModelSpec(
                model=fallback_cfg.default.model,
                provider=fallback_cfg.default.provider,
            ),
            alternatives=[
                AutoFallbackModelSpec(model=item.model, provider=item.provider)
                for item in fallback_cfg.alternatives
            ],
            provider_factory=lambda **kwargs: _make_concrete_provider(config, **kwargs),
            is_provider_available=lambda name: _is_provider_available(config, name),
        )
        provider.generation = _generation_settings(config)
        return provider

    model = defaults.model
    provider_name = config.get_provider_name(model)
    if not provider_name:
        raise ValueError(f"No provider configured for model '{model}'.")
    return _make_concrete_provider(config, model=model, provider=provider_name)


def provider_signature(config: Config) -> tuple[object, ...]:
    """Return the config fields that affect the primary LLM provider."""
    defaults = config.agents.defaults
    if defaults.provider == "autofallback":
        fallback_cfg = config.providers.autofallback
        specs: list[tuple[str, str]] = []
        if fallback_cfg is not None:
            specs.append((fallback_cfg.default.provider, fallback_cfg.default.model))
            specs.extend((item.provider, item.model) for item in fallback_cfg.alternatives)
        seen: set[str] = set()
        provider_signatures: list[tuple[object, ...]] = []
        for provider_name, _model in specs:
            provider_key = _normalize_provider_name(provider_name)
            if provider_key in seen:
                continue
            seen.add(provider_key)
            provider_signatures.append(_provider_config_signature(config, provider_key))
        return (
            defaults.provider,
            _freeze(fallback_cfg.model_dump() if fallback_cfg else None),
            tuple(provider_signatures),
            defaults.max_tokens,
            defaults.temperature,
            defaults.reasoning_effort,
            defaults.context_window_tokens,
        )

    model = defaults.model
    provider_name = config.get_provider_name(model)
    return (
        model,
        defaults.provider,
        provider_name,
        _provider_config_signature(config, provider_name or ""),
        defaults.max_tokens,
        defaults.temperature,
        defaults.reasoning_effort,
        defaults.context_window_tokens,
    )


def build_provider_snapshot(config: Config) -> ProviderSnapshot:
    provider = make_provider(config)
    return ProviderSnapshot(
        provider=provider,
        model=provider.get_default_model(),
        context_window_tokens=config.agents.defaults.context_window_tokens,
        signature=provider_signature(config),
    )


def load_provider_snapshot(config_path: Path | None = None) -> ProviderSnapshot:
    from nanobot.config.loader import load_config, resolve_config_env_vars

    return build_provider_snapshot(resolve_config_env_vars(load_config(config_path)))
