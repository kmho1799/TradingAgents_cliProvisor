import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

from tradingagents.ai_runtime.base import (
    AIErrorKind,
    AIPromptOptions,
    AIResult,
    AIRuntime,
    build_utf8_subprocess_env,
)


_FALLBACK_PATH = os.path.expanduser(r"~\AppData\Local\agy\bin\agy.exe")

# Isolated helper: runs inside a child python process so the ConPTY
# does not interfere with the parent terminal.
_HELPER = r"""
import sys, re, json, winpty

_ANSI = re.compile(
    r'\x1b(?:[@-Z\\-_]|\[[0-9;?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))'
)

data = json.loads(sys.stdin.buffer.read().decode('utf-8'))
cmd  = data['cmd']

proc = winpty.PtyProcess.spawn(cmd, dimensions=(50, 220))
chunks = []
while True:
    try:
        chunk = proc.read(4096)
        if chunk:
            chunks.append(chunk)
    except EOFError:
        break

raw   = ''.join(chunks)
clean = _ANSI.sub('', raw).strip()
sys.stdout.buffer.write(clean.encode('utf-8'))
"""


def _find_agy() -> str | None:
    found = shutil.which("agy")
    if found:
        return found
    if os.path.isfile(_FALLBACK_PATH):
        return _FALLBACK_PATH
    return None


# Windows CreateProcess command-line limit is 32767 chars.
# Reserve ~100 chars for agy path + flags.
_MAX_PROMPT_CHARS = 28_000


def _truncate_prompt(prompt: str, agy_cmd: str) -> str:
    """Truncate prompt if it would exceed Windows command-line limit.

    Keeps the start (system instructions) and end (current task/recent context),
    removing the middle (accumulated tool results).
    """
    limit = _MAX_PROMPT_CHARS - len(agy_cmd)
    if len(prompt) <= limit:
        return prompt
    keep_start = limit // 3
    keep_end = limit - keep_start
    notice = "\n\n[... 중간 내용 길이 초과로 생략됨 ...]\n\n"
    return prompt[:keep_start] + notice + prompt[-keep_end:]


class AgyRuntime(AIRuntime):
    def __init__(self, model: str, enable_web: bool, timeout: int):
        self._model = model
        self._enable_web = enable_web
        self._timeout = timeout

    def is_available(self) -> bool:
        return _find_agy() is not None

    def get_backend_name(self) -> str:
        return "agy-cli"

    def get_model_name(self) -> str:
        return self._model or "agy-default"

    def run_prompt(self, prompt: str, options: AIPromptOptions | None = None) -> AIResult:
        timeout = options.timeout if options and options.timeout is not None else self._timeout

        agy_cmd = _find_agy()
        if not agy_cmd:
            return AIResult(
                None, AIErrorKind.CLI_NOT_FOUND, "agy command not found",
                "agy-cli", self.get_model_name(), 0.0,
            )

        prompt = _truncate_prompt(prompt, agy_cmd)
        payload = json.dumps({"cmd": [agy_cmd, "-p", prompt]}, ensure_ascii=False)

        start = time.monotonic()
        try:
            result = subprocess.run(
                [sys.executable, "-c", _HELPER],
                input=payload.encode("utf-8"),
                capture_output=True,
                timeout=timeout,
                env=build_utf8_subprocess_env(),
            )
            elapsed = time.monotonic() - start

            output_text = result.stdout.decode("utf-8", errors="replace").strip()

            if result.returncode != 0 and not output_text:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                detail = detail or f"helper exited {result.returncode}"
                return AIResult(
                    None, _classify_error(detail), detail,
                    "agy-cli", self.get_model_name(), elapsed,
                )

            if not output_text:
                return AIResult(
                    None, AIErrorKind.PARSE_ERROR, "empty response",
                    "agy-cli", self.get_model_name(), elapsed,
                )

            return AIResult(output_text, None, None, "agy-cli", self.get_model_name(), elapsed)

        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            return AIResult(
                None, AIErrorKind.TIMEOUT, f"timed out after {timeout}s",
                "agy-cli", self.get_model_name(), elapsed,
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return AIResult(
                None, AIErrorKind.UNKNOWN, str(exc),
                "agy-cli", self.get_model_name(), elapsed,
            )


def _classify_error(detail: str) -> AIErrorKind:
    detail_l = detail.lower()
    if "auth" in detail_l or "api key" in detail_l or "login" in detail_l:
        return AIErrorKind.AUTH_ERROR
    if "rate limit" in detail_l:
        return AIErrorKind.RATE_LIMIT
    return AIErrorKind.UNKNOWN
