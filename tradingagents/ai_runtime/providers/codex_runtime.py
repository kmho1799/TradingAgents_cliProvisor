# Modified from the originally distributed TradingAgents project.
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from tradingagents.ai_runtime.base import (
    AIErrorKind,
    AIPromptOptions,
    AIResult,
    AIRuntime,
    build_utf8_subprocess_env,
)


_FALLBACK_PATHS = [
    os.path.expanduser(r"~\.codex\.sandbox-bin\codex.exe"),
]

_TASKKILL_SUCCESS_PATTERNS = (
    re.compile(
        r"^\s*SUCCESS:\s+The process with PID\s+\d+\s+"
        r"\(child process of PID\s+\d+\)\s+has been terminated\.\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*\uc131\uacf5:\s+PID\s+\d+.*PID\s+\d+.*"
        r"(?:\uc885\ub8cc|\ud504\ub85c\uc138\uc2a4).*$"
    ),
    re.compile(r"^\s*\ufffd+:\s+PID\s+\d+.*PID\s+\d+.*\ufffd+.*$"),
    re.compile(r"^\s*:\s+PID\s+\d+.*\(PID\s+\d+.*$"),
)


def _find_codex() -> str | None:
    direct_exe = shutil.which("codex.exe")
    if direct_exe:
        return direct_exe

    cursor_ext_dir = Path.home() / ".cursor" / "extensions"
    if cursor_ext_dir.is_dir():
        candidates = sorted(
            cursor_ext_dir.glob("openai.chatgpt-*/bin/windows-x86_64/codex.exe"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            return str(candidates[0])

    for path in _FALLBACK_PATHS:
        if os.path.isfile(path):
            return path

    found = shutil.which("codex")
    if found:
        return found
    return None


class CodexRuntime(AIRuntime):
    def __init__(self, model: str, enable_web: bool, timeout: int):
        self._model = model
        self._enable_web = enable_web
        self._timeout = timeout

    def is_available(self) -> bool:
        return _find_codex() is not None

    def get_backend_name(self) -> str:
        return "codex-cli"

    def get_model_name(self) -> str:
        return self._model

    def run_prompt(self, prompt: str, options: AIPromptOptions | None = None) -> AIResult:
        timeout = options.timeout if options and options.timeout is not None else self._timeout
        use_web = options.use_web if options and options.use_web is not None else self._enable_web

        codex_cmd = _find_codex()
        if not codex_cmd:
            return AIResult(None, AIErrorKind.CLI_NOT_FOUND, "codex command not found", "codex-cli", self._model, 0.0)

        cmd = [codex_cmd, "exec", "-m", self._model, "--skip-git-repo-check"]
        if use_web:
            cmd += ["-c", 'sandbox_permissions=["network"]']
        cmd += ["-"]

        start = time.monotonic()
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                env=build_utf8_subprocess_env(),
            )
            elapsed = time.monotonic() - start
            stdout_text = _strip_windows_process_cleanup_noise(result.stdout or "")
            stderr_text = (result.stderr or "").strip()

            if result.returncode != 0:
                detail = stderr_text or stdout_text or f"codex exited with code {result.returncode}"
                return AIResult(None, _classify_error(detail), detail, "codex-cli", self._model, elapsed)

            if not stdout_text:
                return AIResult(None, AIErrorKind.PARSE_ERROR, stderr_text or "empty response", "codex-cli", self._model, elapsed)

            return AIResult(stdout_text, None, None, "codex-cli", self._model, elapsed)
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return AIResult(None, AIErrorKind.TIMEOUT, f"timed out after {timeout}s", "codex-cli", self._model, elapsed)
        except Exception as exc:
            elapsed = time.monotonic() - start
            return AIResult(None, AIErrorKind.UNKNOWN, str(exc), "codex-cli", self._model, elapsed)


def _classify_error(detail: str) -> AIErrorKind:
    detail_l = detail.lower()
    if "auth" in detail_l or "api key" in detail_l or "login" in detail_l:
        return AIErrorKind.AUTH_ERROR
    if "rate limit" in detail_l:
        return AIErrorKind.RATE_LIMIT
    return AIErrorKind.UNKNOWN


def _strip_windows_process_cleanup_noise(text: str) -> str:
    lines = [
        line
        for line in text.splitlines()
        if not any(pattern.match(line) for pattern in _TASKKILL_SUCCESS_PATTERNS)
    ]
    return "\n".join(lines).strip()
