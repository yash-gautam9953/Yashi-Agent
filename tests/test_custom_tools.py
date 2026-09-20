import json
import tempfile
import unittest
from pathlib import Path

from tools.custom_tool_manager import (
    create_and_register_tool,
    import_custom_tool,
    load_custom_tools,
    reload_tools,
    test_tool_code,
    validate_tool_code,
    validate_tool_name,
)


class CustomToolManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_tool_name_validation(self):
        validate_tool_name("calculate_sha256")
        validate_tool_name("fetch_data_v2")

        with self.assertRaises(ValueError):
            validate_tool_name("Invalid-Name")

        with self.assertRaises(ValueError):
            validate_tool_name("ab")  # too short

        with self.assertRaises(ValueError):
            validate_tool_name("read_file", core_tools={"read_file", "git_status"})

    def test_tool_code_syntax_and_structure_validation(self):
        valid_code = "def my_tool(text: str) -> str:\n    return text.upper()\n"
        validate_tool_code("my_tool", valid_code)

        syntax_error_code = "def my_tool(\n    missing closing paren"
        with self.assertRaises(ValueError):
            validate_tool_code("my_tool", syntax_error_code)

        missing_func_code = "def other_func():\n    return 42\n"
        with self.assertRaises(ValueError):
            validate_tool_code("my_tool", missing_func_code)

    def test_tool_code_isolated_testing(self):
        code = "def multiply(a: int, b: int) -> int:\n    return a * b\n"
        passing_test = "assert multiply(3, 4) == 12"
        failing_test = "assert multiply(3, 4) == 99"

        passed, _ = test_tool_code(code, passing_test)
        self.assertTrue(passed)

        failed, error_msg = test_tool_code(code, failing_test)
        self.assertFalse(failed)
        self.assertIn("AssertionError", error_msg)

    def test_create_tool_when_test_fails(self):
        code = "def broken_tool(x: int) -> int:\n    raise RuntimeError('boom')\n"
        test_code = "broken_tool(1)"

        result = json.loads(
            create_and_register_tool(
                self.workspace,
                lambda _: True,
                lambda *_: None,
                set(),
                "broken_tool",
                "A broken tool",
                {"type": "object", "properties": {}},
                code,
                test_code=test_code,
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "test_failed")

    def test_create_tool_denied_by_user(self):
        code = "def echo_value(val: str) -> str:\n    return val\n"

        result = json.loads(
            create_and_register_tool(
                self.workspace,
                lambda _: False,  # User says NO
                lambda *_: None,
                set(),
                "echo_value",
                "Echoes back the input value",
                {"type": "object", "properties": {"val": {"type": "string"}}},
                code,
            )
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "denied")
        self.assertFalse((self.workspace / "custom_tools" / "echo_value.py").exists())

    def test_create_register_and_execute_tool(self):
        code = (
            "def add_numbers(a: int, b: int) -> int:\n"
            "    return a + b\n"
        )
        test_code = "assert add_numbers(2, 3) == 5"
        params = {
            "type": "object",
            "properties": {
                "a": {"type": "integer"},
                "b": {"type": "integer"},
            },
            "required": ["a", "b"],
        }

        registered = {}

        def fake_register(name, schema, func):
            registered[name] = {"schema": schema, "func": func}

        result = json.loads(
            create_and_register_tool(
                self.workspace,
                lambda _: True,  # User approves
                fake_register,
                set(),
                "add_numbers",
                "Add two numbers together",
                params,
                code,
                test_code=test_code,
            )
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "registered")

        # Verify files created on disk
        tool_file = self.workspace / "custom_tools" / "add_numbers.py"
        self.assertTrue(tool_file.exists())
        config_file = self.workspace / "config" / "custom_tools.json"
        self.assertTrue(config_file.exists())

        # Verify registered callback was invoked
        self.assertIn("add_numbers", registered)
        tool_func = registered["add_numbers"]["func"]
        self.assertEqual(tool_func(4, 6), 10)

    def test_load_and_reload_persisted_custom_tools(self):
        code = (
            "def reverse_text(text: str) -> str:\n"
            "    return text[::-1]\n"
        )
        registered = {}

        create_and_register_tool(
            self.workspace,
            lambda _: True,
            lambda name, schema, func: registered.update({name: func}),
            set(),
            "reverse_text",
            "Reverses a string",
            {"type": "object", "properties": {"text": {"type": "string"}}},
            code,
        )

        # Now simulate a fresh restart by creating empty tool containers
        new_tool_functions = {}
        new_tools_list = []

        loaded = load_custom_tools(
            self.workspace, new_tool_functions, new_tools_list
        )
        self.assertEqual(loaded, ["reverse_text"])
        self.assertIn("reverse_text", new_tool_functions)
        self.assertEqual(len(new_tools_list), 1)
        self.assertEqual(new_tools_list[0]["name"], "reverse_text")
        self.assertEqual(new_tool_functions["reverse_text"]("hello"), "olleh")

        # Test reload_tools function
        reload_response = json.loads(
            reload_tools(self.workspace, new_tool_functions, new_tools_list)
        )
        self.assertTrue(reload_response["ok"])
        self.assertEqual(reload_response["count"], 1)


if __name__ == "__main__":
    unittest.main()
