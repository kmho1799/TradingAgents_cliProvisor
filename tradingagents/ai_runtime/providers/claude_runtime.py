# Modified from the originally distributed TradingAgents project.
import os
import shutil
import subprocess
import tempfile
import time

from tradingagents.ai_runtime.base import (
    AIErrorKind,
    AIPromptOptions,
    AIResult,
    AIRuntime,
    build_utf8_subprocess_env,
)


class ClaudeRuntime(AIRuntime):
    def __init__(self, model: str, enable_web: bool, timeout: int):
        self._model = model
        self._enable_web = enable_web
        self._timeout = timeout

    def is_available(self) -> bool:
        return bool(shutil.which("claude"))

    def get_backend_name(self) -> str:
        return "claude-cli"

    def get_model_name(self) -> str:
        return self._model

    def run_prompt(self, prompt: str, options: AIPromptOptions | None = None) -> AIResult:
        timeout = options.timeout if options and options.timeout is not None else self._timeout
        use_web = options.use_web if options and options.use_web is not None else self._enable_web

        claude_cmd = shutil.which("claude")
        if not claude_cmd:
            return AIResult(None, AIErrorKind.CLI_NOT_FOUND, "claude command not found", "claude-cli", self._model, 0.0)

        fd, tmp = tempfile.mkstemp(prefix="tradingagents_ai_", suffix=".txt")
        start = time.monotonic()
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(prompt)

            cmd = [claude_cmd, "-p", "--model", self._model]
            if use_web:
                cmd += ["--allowedTools", "WebSearch,WebFetch"]

            with open(tmp, "r", encoding="utf-8") as stdin_f:
                result = subprocess.run(
                    cmd,
                    stdin=stdin_f,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout,
                    env=build_utf8_subprocess_env(),
                )

            elapsed = time.monotonic() - start
            stdout_text = (result.stdout or "").strip()
            stderr_text = (result.stderr or "").strip()

            if result.returncode != 0:
                return AIResult(
                    None,
                    _classify_error(stderr_text or stdout_text or f"claude exited with code {result.returncode}"),
                    stderr_text or stdout_text or f"claude exited with code {result.returncode}",
                    "claude-cli",
                    self._model,
                    elapsed,
                )

            if not stdout_text:
                return AIResult(None, AIErrorKind.PARSE_ERROR, "empty response", "claude-cli", self._model, elapsed)

            return AIResult(stdout_text, None, None, "claude-cli", self._model, elapsed)
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return AIResult(None, AIErrorKind.TIMEOUT, f"timed out after {timeout}s", "claude-cli", self._model, elapsed)
        except Exception as exc:
            elapsed = time.monotonic() - start
            return AIResult(None, AIErrorKind.UNKNOWN, str(exc), "claude-cli", self._model, elapsed)
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass


def _classify_error(detail: str) -> AIErrorKind:
    detail_l = detail.lower()
    if "authentication" in detail_l or "api key" in detail_l or "login" in detail_l or "does not have access" in detail_l:
        return AIErrorKind.AUTH_ERROR
    if "rate limit" in detail_l:
        return AIErrorKind.RATE_LIMIT
    return AIErrorKind.UNKNOWN
