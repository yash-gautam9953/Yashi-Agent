import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

from agent.orchestrator import AgentOrchestrator, DEFAULT_AGENT_INSTRUCTIONS
from agent.tool_builder import create_tool_builder_handler
from llm.base import BaseLLMClient
from llm.client import AzureOpenAIClient
from tools.dispatcher import ToolDispatcher
from tools.registry import ToolRegistry


class FakeLLMClient(BaseLLMClient):
    """Fake LLM client for testing agent orchestration without API calls."""

    def __init__(self, responses=None):
        self.responses = responses or []
        self.calls = []

    def create_response(self, instructions, input_data, tools=None, previous_response_id=None):
        self.calls.append({
            "instructions": instructions,
            "input_data": input_data,
            "tools": tools,
            "previous_response_id": previous_response_id,
        })
        if self.responses:
            return self.responses.pop(0)
        # Default empty text response
        mock_resp = MagicMock()
        mock_resp.id = "resp_default"
        mock_resp.output = []
        mock_resp.output_text = "Default response"
        return mock_resp


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tool_registry_and_dispatcher(self):
        registry = ToolRegistry()
        
        # Test base tools loading
        tools_file = self.workspace / "tools.json"
        tools_file.write_text(json.dumps([
            {"type": "function", "name": "base_tool", "description": "Base tool"}
        ]))
        registry.load_base_tools(tools_file)
        self.assertEqual(len(registry.schemas), 1)
        self.assertEqual(registry.schemas[0]["name"], "base_tool")

        # Test binding function
        registry.bind_function("base_tool", lambda x: f"base:{x}")
        self.assertTrue(registry.has_tool("base_tool"))

        # Test dispatcher
        dispatcher = ToolDispatcher(registry)
        result = dispatcher.dispatch("base_tool", {"x": "hello"})
        self.assertEqual(result, "base:hello")

        # Test dispatching non-existent tool
        err_result = dispatcher.dispatch("missing_tool", {})
        self.assertIn("Tool error: Tool 'missing_tool' not found.", err_result)

        # Test dispatching tool that returns dict
        registry.register_tool(
            "json_tool",
            {"type": "function", "name": "json_tool"},
            lambda: {"status": "ok", "value": 42},
        )
        json_result = dispatcher.dispatch("json_tool", {})
        self.assertEqual(json.loads(json_result), {"status": "ok", "value": 42})

        # Test tool error capture
        def broken_tool():
            raise ValueError("Something broke")
        registry.register_tool("broken", {"type": "function", "name": "broken"}, broken_tool)
        broken_result = dispatcher.dispatch("broken", {})
        self.assertIn("Tool error: Something broke", broken_result)

    def test_orchestrator_direct_text_response(self):
        mock_resp = MagicMock()
        mock_resp.id = "resp_1"
        mock_resp.output = []
        mock_resp.output_text = "Hello! How can I help you today?"

        fake_client = FakeLLMClient(responses=[mock_resp])
        registry = ToolRegistry()
        orchestrator = AgentOrchestrator(
            llm_client=fake_client,
            registry=registry,
            max_tool_rounds=3,
        )

        response_id = orchestrator.run_task("Hi")
        self.assertEqual(response_id, "resp_1")
        self.assertEqual(len(fake_client.calls), 1)
        self.assertEqual(fake_client.calls[0]["input_data"], "Hi")
        self.assertEqual(fake_client.calls[0]["instructions"], DEFAULT_AGENT_INSTRUCTIONS)

    def test_orchestrator_tool_calling_round(self):
        # 1st response: requests a tool call
        item = MagicMock()
        item.type = "function_call"
        item.name = "calculate"
        item.call_id = "call_abc"
        item.arguments = json.dumps({"a": 5, "b": 10})

        first_resp = MagicMock()
        first_resp.id = "resp_1"
        first_resp.output = [item]
        first_resp.output_text = None

        # 2nd response: final response after observing tool result
        second_resp = MagicMock()
        second_resp.id = "resp_2"
        second_resp.output = []
        second_resp.output_text = "The sum is 15."

        fake_client = FakeLLMClient(responses=[first_resp, second_resp])

        registry = ToolRegistry()
        registry.register_tool(
            "calculate",
            {"type": "function", "name": "calculate"},
            lambda a, b: a + b,
        )

        orchestrator = AgentOrchestrator(
            llm_client=fake_client,
            registry=registry,
            max_tool_rounds=5,
        )

        response_id = orchestrator.run_task("Add 5 and 10")
        self.assertEqual(response_id, "resp_2")
        self.assertEqual(len(fake_client.calls), 2)
        # Second call should contain the tool output
        second_call = fake_client.calls[1]
        self.assertEqual(second_call["previous_response_id"], "resp_1")
        self.assertEqual(second_call["input_data"][0]["type"], "function_call_output")
        self.assertEqual(second_call["input_data"][0]["output"], "15")

    def test_tool_builder_handler_integration(self):
        registry = ToolRegistry()
        handler = create_tool_builder_handler(
            self.workspace,
            lambda _: True,  # User approves
            registry.register_custom_tool,
            {"create_and_register_tool"},
        )
        registry.bind_function("create_and_register_tool", handler)

        code = "def sample_tool(msg: str) -> str:\n    return msg.strip()\n"
        test_code = "assert sample_tool(' hi ') == 'hi'"
        params = {"type": "object", "properties": {"msg": {"type": "string"}}}

        result = json.loads(handler(
            name="sample_tool",
            description="Sample tool",
            parameters=params,
            code=code,
            test_code=test_code,
        ))

        self.assertTrue(result["ok"])
        self.assertTrue(registry.has_tool("sample_tool"))
        self.assertEqual(registry.get_function("sample_tool")("  hello  "), "hello")

    def test_azure_openai_client_validation(self):
        with self.assertRaises(RuntimeError):
            AzureOpenAIClient(api_key="")


if __name__ == "__main__":
    unittest.main()
