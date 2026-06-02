# Modified from the originally distributed TradingAgents project.
from dataclasses import dataclass

from .base import AIRuntime


@dataclass
class RuntimeConfig:
    backend: str
    model: str
    enable_web: bool = False
    timeout: int = 600


def normalize_backend(backend: str) -> str:
    return backend.lower().replace("_", "-")


def create_runtime(config: RuntimeConfig) -> AIRuntime:
    backend = normalize_backend(config.backend)

    if backend in ("claude", "claude-cli"):
        from .providers.claude_runtime import ClaudeRuntime

        return ClaudeRuntime(config.model, config.enable_web, config.timeout)

    if backend in ("codex", "codex-cli"):
        from .providers.codex_runtime import CodexRuntime

        return CodexRuntime(config.model, config.enable_web, config.timeout)

    if backend in ("agy", "agy-cli"):
        from .providers.agy_runtime import AgyRuntime

        return AgyRuntime(config.model, config.enable_web, config.timeout)

    raise ValueError(f"Unsupported CLI runtime backend: {config.backend}")
