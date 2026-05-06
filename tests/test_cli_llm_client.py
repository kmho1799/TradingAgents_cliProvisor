# Modified from the originally distributed TradingAgents project.
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import tool

from tradingagents.ai_runtime.base import AIResult
from tradingagents.ai_runtime.providers import codex_runtime
from tradingagents.llm_clients.cli_client import CLIChatModel, CLIClient
from tradingagents.llm_clients.factory import create_llm_client


class FakeRuntime:
    def __init__(self, text):
        self.text = text
        self.prompts = []

    def run_prompt(self, prompt, options=None):
        self.prompts.append(prompt)
        return AIResult(
            text=self.text,
            error=None,
            error_detail=None,
            provider="fake-cli",
            model="fake-model",
            elapsed_seconds=0.1,
        )


@tool
def lookup_price(symbol: str) -> str:
    """Look up a stock price."""
    return f"{symbol}: 1"


class CLIChatModelTests(unittest.TestCase):
    def test_invoke_returns_ai_message_content_from_runtime_text(self):
        runtime = FakeRuntime("plain response")
        model = CLIChatModel(runtime=runtime, provider="claude-cli", model="claude-test")

        response = model.invoke([HumanMessage(content="hello")])

        self.assertIsInstance(response, AIMessage)
        self.assertEqual(response.content, "plain response")
        self.assertIn("hello", runtime.prompts[0])

    def test_invoke_preserves_dict_message_roles(self):
        runtime = FakeRuntime("plain response")
        model = CLIChatModel(runtime=runtime, provider="claude-cli", model="claude-test")

        model.invoke(
            [
                {"role": "system", "content": "follow rules"},
                {"role": "user", "content": "analyze NVDA"},
            ]
        )

        self.assertIn("system: follow rules", runtime.prompts[0])
        self.assertIn("user: analyze NVDA", runtime.prompts[0])
        self.assertNotIn("dict:", runtime.prompts[0])

    def test_bind_tools_converts_tool_call_json_to_ai_message_tool_calls(self):
        runtime = FakeRuntime(
            '{"type":"tool_call","tool_calls":[{"name":"lookup_price","args":{"symbol":"NVDA"}}]}'
        )
        model = CLIChatModel(runtime=runtime, provider="codex-cli", model="gpt-test")

        response = model.bind_tools([lookup_price]).invoke([HumanMessage(content="price?")])

        self.assertEqual(response.content, "")
        self.assertEqual(response.tool_calls[0]["name"], "lookup_price")
        self.assertEqual(response.tool_calls[0]["args"], {"symbol": "NVDA"})
        self.assertIn("lookup_price", runtime.prompts[0])

    def test_bind_tools_converts_final_json_to_ai_message_content(self):
        runtime = FakeRuntime('{"type":"final","content":"final report"}')
        model = CLIChatModel(runtime=runtime, provider="claude-cli", model="claude-test")

        response = model.bind_tools([lookup_price]).invoke([HumanMessage(content="done?")])

        self.assertEqual(response.content, "final report")
        self.assertEqual(response.tool_calls, [])

    def test_bind_tools_rejects_malformed_tool_call_json(self):
        runtime = FakeRuntime('{"type":"tool_call","tool_calls":[{"args":{}}]}')
        model = CLIChatModel(runtime=runtime, provider="claude-cli", model="claude-test")

        with self.assertRaisesRegex(RuntimeError, "parse_error"):
            model.bind_tools([lookup_price]).invoke([HumanMessage(content="price?")])

    def test_bind_tools_treats_natural_language_response_as_final_content(self):
        runtime = FakeRuntime("Here is the market analysis without a tool call.")
        model = CLIChatModel(runtime=runtime, provider="claude-cli", model="claude-test")

        response = model.bind_tools([lookup_price]).invoke([HumanMessage(content="analyze")])

        self.assertEqual(response.content, "Here is the market analysis without a tool call.")
        self.assertEqual(response.tool_calls, [])

    def test_factory_creates_cli_client_for_cli_providers(self):
        client = create_llm_client("claude-cli", "claude-sonnet-4-6")

        self.assertIsInstance(client, CLIClient)

    def test_codex_discovery_prefers_real_extension_exe_over_launcher(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            codex_exe = (
                root
                / ".cursor"
                / "extensions"
                / "openai.chatgpt-test"
                / "bin"
                / "windows-x86_64"
                / "codex.exe"
            )
            codex_exe.parent.mkdir(parents=True)
            codex_exe.write_text("", encoding="utf-8")

            with patch.object(codex_runtime.Path, "home", return_value=root), patch(
                "tradingagents.ai_runtime.providers.codex_runtime.shutil.which",
                side_effect=lambda name: "C:\\Users\\test\\.local\\bin\\codex.cmd"
                if name == "codex"
                else None,
            ):
                self.assertEqual(codex_runtime._find_codex(), str(codex_exe))


class CodexRuntimeOutputTests(unittest.TestCase):
    def test_strip_windows_taskkill_noise_from_stdout(self):
        raw = "\n".join(
            [
                "SUCCESS: The process with PID 50440 (child process of PID 47168) has been terminated.",
                "\uc131\uacf5: PID 23860\uc778 \ud504\ub85c\uc138\uc2a4(PID 47168\uc758 \uc790\uc2dd \ud504\ub85c\uc138\uc2a4)\uac00 \uc885\ub8cc\ub418\uc5c8\uc2b5\ub2c8\ub2e4.",
                "\ufffd\ufffd\ufffd\ufffd: PID 17316\ufffd\ufffd \ufffd\ufffd\ufffd\u03bc\ufffd\ufffd(PID 47168\ufffd\ufffd \ufffd\u06bd\ufffd \ufffd\ufffd\ufffd\u03bc\ufffd\ufffd)\ufffd\ufffd \ufffd\ufffd\ufffd\ufffd\u01fe\u03f4\ufffd\ufffd\ufffd\ufffd.",
                ": PID 33496 \u03bc(PID 47168 \u06bd \u03bc) \u01fe\u03f4.",
                "# Final report",
                "This analysis mentions PID 123 once and should remain.",
            ]
        )

        cleaned = codex_runtime._strip_windows_process_cleanup_noise(raw)

        self.assertEqual(
            cleaned,
            "# Final report\nThis analysis mentions PID 123 once and should remain.",
        )


if __name__ == "__main__":
    unittest.main()
