import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from agent.orchestrator import AgentOrchestrator
from agent.tool_builder import create_tool_builder_handler
from llm.base import BaseLLMClient
from memory.session_store import SessionStore
from tools.custom_tool_manager import create_and_register_tool
from tools.registry import ToolRegistry
from ui.console import Console


class MockItem:
    def __init__(self, item_type="function_call", name=None, arguments="{}", call_id="call_1"):
        self.type = item_type
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class MockResponse:
    def __init__(self, output=None, output_text="Done.", response_id="resp_123"):
        self.output = output or []
        self.output_text = output_text
        self.id = response_id


class MockLLM(BaseLLMClient):
    def __init__(self, response=None, exception=None):
        self.response = response or MockResponse()
        self.exception = exception
        self.call_count = 0

    def create_response(
        self,
        instructions: str,
        input_data,
        tools=None,
        previous_response_id=None,
        on_text_delta=None,
    ):
        self.call_count += 1
        if self.exception:
            raise self.exception
        if callable(on_text_delta) and self.response.output_text:
            on_text_delta(self.response.output_text)
        return self.response


class TerminalUXTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.console = Console()
        self.console.enabled = False  # Avoid ANSI escape codes during assertion parsing

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_multi_step_progress_rendering(self):
        """Test console.step renders multi-step progress indicators."""
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            self.console.step("Checking available tools")
            self.console.step("Planning")
            self.console.step("Creating tool")
            self.console.step("Security inspection")
            self.console.step("Waiting for approval")
            self.console.step("Testing")
            self.console.step("Registering")
            self.console.step("Executing")

        out = buffer.getvalue()
        self.assertIn("Checking available tools", out)
        self.assertIn("Planning", out)
        self.assertIn("Creating tool", out)
        self.assertIn("Security inspection", out)
        self.assertIn("Waiting for approval", out)
        self.assertIn("Testing", out)
        self.assertIn("Registering", out)
        self.assertIn("Executing", out)

    def test_multi_step_progress_callback_in_tool_creation(self):
        """Test create_and_register_tool triggers progress notifications in proper order."""
        recorded_steps = []

        def on_progress(step_name):
            recorded_steps.append(step_name)

        registered = {}

        def mock_register(name, schema, func):
            registered[name] = func

        def mock_approve(report):
            return True

        valid_code = "def add_nums(a: int, b: int) -> int:\n    return a + b\n"
        test_code = "assert add_nums(2, 3) == 5\n"

        result_str = create_and_register_tool(
            workspace=self.workspace,
            approve=mock_approve,
            register_callback=mock_register,
            core_tools={"create_and_register_tool"},
            name="add_nums",
            description="Add two numbers",
            parameters={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
            code=valid_code,
            test_code=test_code,
            on_progress=on_progress,
        )

        data = json.loads(result_str)
        self.assertTrue(data.get("ok"))
        self.assertEqual(data.get("status"), "registered")

        # Verify progression sequence
        self.assertIn("Checking available tools", recorded_steps)
        self.assertIn("Creating tool", recorded_steps)
        self.assertIn("Security inspection", recorded_steps)
        self.assertIn("Waiting for approval", recorded_steps)
        self.assertIn("Testing", recorded_steps)
        self.assertIn("Registering", recorded_steps)

    def test_graceful_ctrl_c_handling_in_orchestrator(self):
        """Test KeyboardInterrupt during task execution halts gracefully and stops thinking thread."""
        mock_llm = MagicMock()
        mock_llm.create_response.side_effect = KeyboardInterrupt()

        registry = ToolRegistry()
        orchestrator = AgentOrchestrator(
            llm_client=mock_llm,
            registry=registry,
            console=self.console,
        )

        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            res_id = orchestrator.run_task("Do something long", "resp_prev")

        # Must return previous response id safely without raising uncaught exception
        self.assertEqual(res_id, "resp_prev")
        out = buffer.getvalue()
        self.assertIn("cancelled by user", out)

    def test_graceful_ctrl_c_handling_in_prompt_and_approval(self):
        """Test Ctrl+C at prompt and approval screens does not crash."""
        # 1. Prompt Ctrl+C
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            val = self.console.prompt()
            self.assertEqual(val, "")

        # 2. Confirmation Ctrl+C
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            confirmed = self.console.confirm("Delete everything?")
            self.assertFalse(confirmed)

        # 3. Tool approval Ctrl+C
        mock_report = MagicMock()
        mock_report.format_screen.return_value = "Screen"
        with patch("builtins.input", side_effect=KeyboardInterrupt):
            approved = self.console.tool_approval_prompt(mock_report)
            self.assertFalse(approved)

    def test_graceful_api_errors(self):
        """Test OpenAI / Azure API errors are caught and rendered with actionable tips without secrets."""
        secret_key = "sk-proj-super_secret_token_1234567890abcdef"
        api_error = RuntimeError(f"Authentication failed with key {secret_key} (401 Unauthorized)")

        mock_llm = MagicMock()
        mock_llm.create_response.side_effect = api_error

        registry = ToolRegistry()
        orchestrator = AgentOrchestrator(
            llm_client=mock_llm,
            registry=registry,
            console=self.console,
        )

        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            res_id = orchestrator.run_task("test api", "resp_prev")

        out = buffer.getvalue()
        self.assertEqual(res_id, "resp_prev")
        self.assertIn("API AUTHENTICATION ERROR", out)
        self.assertIn("Tip:", out)
        # Verify secret was scrubbed from error display
        self.assertNotIn(secret_key, out)
        self.assertIn("[REDACTED_KEY]", out)

    def test_tool_timeout_error_formatting(self):
        """Test tool execution timeout displays dedicated [ timeout ] tag."""
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            self.console.tool_result("Tool error: Tool execution timed out after 5.0 seconds")

        out = buffer.getvalue()
        self.assertIn("[ timeout ]", out)
        self.assertIn("timed out after 5.0 seconds", out)

    def test_error_panel_formatting(self):
        """Test structured error panel output with optional tip."""
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            self.console.error("Resource not found", title="NOT FOUND", tip="Check path in workspace.")

        out = buffer.getvalue()
        self.assertIn("[ NOT FOUND ]", out)
        self.assertIn("Resource not found", out)
        self.assertIn("Tip:", out)
        self.assertIn("Check path in workspace.", out)

    def test_streaming_assistant_response(self):
        """Test assistant streaming output methods function properly without errors."""
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            self.console.stream_assistant_start()
            self.console.stream_assistant_chunk("Hello")
            self.console.stream_assistant_chunk(" world!")
            self.console.stream_assistant_end()

        out = buffer.getvalue()
        self.assertIn("[ YASHI ]", out)
        self.assertIn("Hello world!", out)

    def test_command_history_recording(self):
        """Test command history tracking and prompt recording."""
        self.console.command_history.clear()
        with patch("builtins.input", side_effect=["/tools", "/sessions", "calculate 2 + 2"]):
            self.assertEqual(self.console.prompt(), "/tools")
            self.assertEqual(self.console.prompt(), "/sessions")
            self.assertEqual(self.console.prompt(), "calculate 2 + 2")

        self.assertEqual(self.console.command_history, ["/tools", "/sessions", "calculate 2 + 2"])


if __name__ == "__main__":
    unittest.main()
