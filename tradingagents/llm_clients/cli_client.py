# Modified from the originally distributed TradingAgents project.
import json
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any, Iterable

from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.runnables import RunnableLambda

from tradingagents.ai_runtime import AIPromptOptions, AIErrorKind, RuntimeConfig, create_runtime

from .base_client import BaseLLMClient


class CLIChatModel:
    def __init__(
        self,
        runtime,
        provider: str,
        model: str,
        timeout: int | None = None,
        use_web: bool | None = None,
        fallback_mode: str = "none",
        fallback_backend: str | None = None,
        fallback_model: str | None = None,
        strict_backend: bool = True,
    ):
        self.runtime = runtime
        self.provider = provider
        self.model = model
        self.timeout = timeout
        self.use_web = use_web
        self.fallback_mode = fallback_mode
        self.fallback_backend = fallback_backend
        self.fallback_model = fallback_model
        self.strict_backend = strict_backend

    def invoke(self, input, config=None, **kwargs):
        prompt = self._serialize_input(input)
        return self._run(prompt)

    def bind_tools(self, tools, **kwargs):
        tool_specs = [_tool_to_spec(tool) for tool in tools]

        def invoke_with_tools(input, config=None):
            prompt = self._build_tool_prompt(input, tool_specs)
            response = self._run(prompt)
            return self._parse_tool_response(response.content, prompt)

        return RunnableLambda(invoke_with_tools)

    def _run(self, prompt: str) -> AIMessage:
        options = AIPromptOptions(timeout=self.timeout, use_web=self.use_web)
        result = self.runtime.run_prompt(prompt, options)
        if result.error in (AIErrorKind.TIMEOUT, AIErrorKind.RATE_LIMIT) or (
            result.error == AIErrorKind.PARSE_ERROR and result.error_detail == "empty response"
        ):
            if result.error == AIErrorKind.RATE_LIMIT:
                time.sleep(5)
            result = self.runtime.run_prompt(prompt, options)
        if result.error is not None and self._can_use_fallback():
            fallback_runtime = create_runtime(
                RuntimeConfig(
                    backend=self.fallback_backend or self.provider,
                    model=self.fallback_model or self.model,
                    enable_web=bool(self.use_web),
                    timeout=int(self.timeout or 600),
                )
            )
            result = fallback_runtime.run_prompt(prompt, options)
        if result.error is not None:
            detail = result.error_detail or result.error.value
            raise RuntimeError(f"{result.provider}/{result.model} failed: {detail}")
        return AIMessage(content=result.text or "")

    def _can_use_fallback(self) -> bool:
        return (
            self.fallback_mode == "secondary"
            and not self.strict_backend
            and bool(self.fallback_backend)
            and self.fallback_backend != self.provider
        )

    def _build_tool_prompt(self, input, tool_specs: list[dict[str, Any]]) -> str:
        conversation = self._serialize_input(input)
        return "\n\n".join(
            [
                conversation,
                "You may call tools, but you must respond with exactly one JSON object and no markdown.",
                "If you need tool data, respond as:",
                '{"type":"tool_call","tool_calls":[{"name":"tool_name","args":{"arg":"value"}}]}',
                "If you can answer without more tool data, respond as:",
                '{"type":"final","content":"your final answer"}',
                "Available tools:",
                json.dumps(tool_specs, ensure_ascii=False),
            ]
        )

    def _parse_tool_response(self, text: str, original_prompt: str) -> AIMessage:
        try:
            payload = _loads_json_object(text)
        except ValueError:
            retry_prompt = "\n\n".join(
                [
                    original_prompt,
                    "The previous response was not valid JSON. Reformat it as exactly one JSON object using the required schema.",
                    text,
                ]
            )
            try:
                retry = self._run(retry_prompt)
                payload = _loads_json_object(retry.content)
            except ValueError as exc:
                if not _contains_json_object(text) and not _contains_json_object(
                    retry.content
                ):
                    return AIMessage(content=text.strip())
                if self._can_use_fallback():
                    fallback_runtime = create_runtime(
                        RuntimeConfig(
                            backend=self.fallback_backend or self.provider,
                            model=self.fallback_model or self.model,
                            enable_web=_to_bool(self.use_web),
                            timeout=int(self.timeout or 600),
                        )
                    )
                    fallback_result = fallback_runtime.run_prompt(
                        retry_prompt,
                        AIPromptOptions(timeout=self.timeout, use_web=self.use_web),
                    )
                    if fallback_result.error is None:
                        try:
                            payload = _loads_json_object(fallback_result.text or "")
                        except ValueError as fallback_exc:
                            raise RuntimeError(
                                f"{fallback_result.provider}/{fallback_result.model} failed: "
                                f"{AIErrorKind.PARSE_ERROR.value}: {fallback_exc}"
                            ) from fallback_exc
                    else:
                        detail = fallback_result.error_detail or fallback_result.error.value
                        raise RuntimeError(
                            f"{fallback_result.provider}/{fallback_result.model} failed: {detail}"
                        ) from exc
                else:
                    raise RuntimeError(
                        f"{self.provider}/{self.model} failed: {AIErrorKind.PARSE_ERROR.value}: {exc}"
                    ) from exc
            except RuntimeError:
                raise

        payload_type = payload.get("type")
        if payload_type == "tool_call":
            try:
                tool_calls = _normalize_tool_calls(payload.get("tool_calls", []))
            except ValueError as exc:
                raise RuntimeError(
                    f"{self.provider}/{self.model} failed: {AIErrorKind.PARSE_ERROR.value}: {exc}"
                ) from exc
            return AIMessage(content="", tool_calls=tool_calls)
        if payload_type == "final":
            return AIMessage(content=str(payload.get("content", "")))
        raise RuntimeError(
            f"{self.provider}/{self.model} failed: {AIErrorKind.PARSE_ERROR.value}: "
            f"unsupported response type {payload_type}"
        )

    def _serialize_input(self, input) -> str:
        if hasattr(input, "to_messages"):
            return _serialize_messages(input.to_messages())
        if isinstance(input, str):
            return input
        if isinstance(input, BaseMessage):
            return _serialize_messages([input])
        if isinstance(input, Iterable):
            return _serialize_messages(input)
        return str(input)


class CLIClient(BaseLLMClient):
    def __init__(self, model: str, base_url: str | None = None, provider: str = "claude-cli", **kwargs):
        super().__init__(model, base_url, **kwargs)
        self.provider = provider.lower()

    def get_llm(self) -> Any:
        timeout = self.kwargs.get("timeout", self.kwargs.get("ai_runtime_timeout_seconds", 600))
        use_web = self.kwargs.get("use_web", self.kwargs.get("ai_runtime_enable_web", False))
        fallback_mode = self.kwargs.get("ai_runtime_fallback_mode", "none")
        fallback_backend = self.kwargs.get("ai_runtime_fallback_backend")
        fallback_model = self.kwargs.get("ai_runtime_fallback_model")
        strict_backend = self.kwargs.get("ai_runtime_strict_backend", True)
        runtime = create_runtime(
            RuntimeConfig(
                backend=self.provider,
                model=self.model,
                enable_web=_to_bool(use_web),
                timeout=int(timeout),
            )
        )
        return CLIChatModel(
            runtime=runtime,
            provider=self.provider,
            model=self.model,
            timeout=int(timeout),
            use_web=_to_bool(use_web),
            fallback_mode=str(fallback_mode),
            fallback_backend=fallback_backend,
            fallback_model=fallback_model,
            strict_backend=_to_bool(strict_backend),
        )

    def validate_model(self) -> bool:
        return True


def _serialize_messages(messages) -> str:
    lines = []
    for message in messages:
        if isinstance(message, Mapping):
            role = message.get("role", "message")
            content = message.get("content", "")
        elif isinstance(message, tuple) and len(message) >= 2:
            role, content = message[0], message[1]
        else:
            role = getattr(message, "type", message.__class__.__name__)
            content = getattr(message, "content", message)
        lines.append(f"{role}: {_stringify_content(content)}")
        tool_calls = getattr(message, "tool_calls", None)
        if tool_calls:
            lines.append(f"{role}_tool_calls: {json.dumps(tool_calls, ensure_ascii=False)}")
    return "\n".join(lines)


def _stringify_content(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or item))
            else:
                parts.append(str(item))
        return "\n".join(parts)
    return str(content)


def _tool_to_spec(tool) -> dict[str, Any]:
    name = getattr(tool, "name", getattr(tool, "__name__", "tool"))
    description = getattr(tool, "description", getattr(tool, "__doc__", "") or "")
    args = getattr(tool, "args", None)
    if args is None:
        args_schema = getattr(tool, "args_schema", None)
        if args_schema and hasattr(args_schema, "model_json_schema"):
            args = args_schema.model_json_schema().get("properties", {})
        else:
            args = {}
    return {"name": name, "description": description, "args": args}


def _loads_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, re.DOTALL)
    if fenced:
        stripped = fenced.group(1)
    elif not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise ValueError("No JSON object found in CLI response")
        stripped = stripped[start : end + 1]
    loaded = json.loads(stripped)
    if not isinstance(loaded, dict):
        raise ValueError("CLI response JSON must be an object")
    return loaded


def _contains_json_object(text: str) -> bool:
    stripped = text.strip()
    if re.search(r"```(?:json)?\s*\{.*?\}\s*```", stripped, re.DOTALL):
        return True
    return stripped.find("{") != -1 and stripped.rfind("}") > stripped.find("{")


def _normalize_tool_calls(tool_calls) -> list[dict[str, Any]]:
    if not isinstance(tool_calls, list) or not tool_calls:
        raise ValueError("tool_calls must be a non-empty list")

    normalized = []
    for index, call in enumerate(tool_calls or []):
        if not isinstance(call, Mapping):
            raise ValueError("each tool call must be an object")
        name = call.get("name")
        args = call.get("args", {})
        if not isinstance(name, str) or not name:
            raise ValueError("each tool call must include a non-empty string name")
        if not isinstance(args, dict):
            raise ValueError("tool call args must be an object")
        normalized.append(
            {
                "name": name,
                "args": args,
                "id": call.get("id") or f"call_{uuid.uuid4().hex}_{index}",
            }
        )
    return normalized


def _to_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")
