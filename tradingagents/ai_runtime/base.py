# Modified from the originally distributed TradingAgents project.
import os
from dataclasses import dataclass
from enum import Enum


class AIErrorKind(Enum):
    TIMEOUT = "timeout"
    CLI_NOT_FOUND = "cli_not_found"
    AUTH_ERROR = "auth_error"
    RATE_LIMIT = "rate_limit"
    PARSE_ERROR = "parse_error"
    UNKNOWN = "unknown"


@dataclass
class AIResult:
    text: str | None
    error: AIErrorKind | None
    error_detail: str | None
    provider: str
    model: str
    elapsed_seconds: float


@dataclass
class AIPromptOptions:
    timeout: int | None = None
    use_web: bool | None = None
    system_prompt: str | None = None
    temperature: float | None = None


class AIRuntime:
    def is_available(self) -> bool:
        raise NotImplementedError

    def get_backend_name(self) -> str:
        raise NotImplementedError

    def get_model_name(self) -> str:
        raise NotImplementedError

    def run_prompt(self, prompt: str, options: AIPromptOptions | None = None) -> AIResult:
        raise NotImplementedError


def build_utf8_subprocess_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    env.setdefault("LANG", "C.UTF-8")
    env.setdefault("LC_ALL", "C.UTF-8")
    if extra:
        env.update(extra)
    return env
