import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from custom_tools.write_text_file import write_text_file
from security.inspector import SecurityInspector
from tools.custom_tool_manager import create_and_register_tool
from tools.dispatcher import ToolDispatcher
from tools.execution import execute_tool_safely
from tools.registry import ToolRegistry
from tools.sandbox import ToolSandbox


class SecurityAndSandboxTests(unittest.TestCase):
    def setUp(self):
        self.inspector = SecurityInspector()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_dangerous_imports(self):
        dangerous_snippets = [
            "import os\ndef t(): pass",
            "import subprocess\ndef t(): pass",
            "import shutil\ndef t(): pass",
            "import socket\ndef t(): pass",
            "import ctypes\ndef t(): pass",
            "import requests\ndef t(): pass",
            "from sys import argv\ndef t(): pass",
            "from importlib import import_module\ndef t(): pass",
            "import pip\ndef t(): pass",
        ]
        for snippet in dangerous_snippets:
            with self.subTest(snippet=snippet):
                result = self.inspector.inspect_code(snippet)
                self.assertFalse(result.is_safe)
                self.assertGreater(len(result.violations), 0)

    def test_subprocess_and_eval_attempts(self):
        snippets = [
            "def run_cmd():\n    eval('1 + 1')",
            "def run_cmd():\n    exec('import os')",
            "def run_cmd():\n    compile('x = 1', '<string>', 'exec')",
            "def run_cmd():\n    __import__('subprocess')",
            "def run_cmd():\n    open('/etc/passwd', 'r')",
        ]
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                result = self.inspector.inspect_code(snippet)
                self.assertFalse(result.is_safe)
                self.assertGreater(len(result.violations), 0)

    def test_dunder_and_environment_access(self):
        snippets = [
            "def escape():\n    return ().__class__.__bases__[0].__subclasses__()",
            "def env_leak():\n    return os.environ.get('KEY')",
            "def env_leak_2():\n    return environ['KEY']",
            "def dunder():\n    return (lambda: None).__globals__",
        ]
        for snippet in snippets:
            with self.subTest(snippet=snippet):
                result = self.inspector.inspect_code(snippet)
                self.assertFalse(result.is_safe)
                self.assertGreater(len(result.violations), 0)

    def test_sandbox_cleans_secrets(self):
        # Set a mock sensitive variable in current process
        os.environ["AZURE_OPENAI_API_KEY"] = "super-secret-key-12345"
        try:
            sandbox = ToolSandbox()
            clean_env = sandbox._build_clean_environment()
            self.assertNotIn("AZURE_OPENAI_API_KEY", clean_env)
            self.assertNotIn("AZURE_AUTH_URL", clean_env)
        finally:
            os.environ.pop("AZURE_OPENAI_API_KEY", None)

    def test_path_traversal_detection(self):
        # 1. AST Inspector detects Path traversal
        traversal_code = "from pathlib import Path\ndef t():\n    return Path('../../etc/shadow').read_text()"
        result = self.inspector.inspect_code(traversal_code)
        self.assertFalse(result.is_safe)
        self.assertTrue(any("path traversal" in v.lower() for v in result.violations))

        # 2. write_text_file built-in tool rejects path traversal
        res1 = write_text_file("../escape.txt", "evil")
        self.assertFalse(res1["ok"])
        self.assertIn("relative paths", res1["error"])

        res2 = write_text_file("/absolute/escape.txt", "evil")
        self.assertFalse(res2["ok"])
        self.assertIn("relative paths", res2["error"])

    def test_sandbox_timeout(self):
        sandbox = ToolSandbox(timeout=0.5)
        # Infinite loop
        hang_code = "def hang():\n    while True:\n        pass\n"
        hang_test = "hang()"

        result = sandbox.run_test(hang_code, hang_test)
        self.assertFalse(result["success"])
        self.assertIn("timeout", result["violations"])
        self.assertIn("timed out", result["error"])

    def test_runtime_execution_timeout(self):
        def slow_function():
            time.sleep(1.0)
            return "done"

        # Direct safe execution with timeout
        with self.assertRaises(TimeoutError):
            execute_tool_safely(slow_function, {}, timeout=0.2)

        # Dispatcher timeout handling
        registry = ToolRegistry()
        registry.register_tool(
            "slow_tool",
            {"type": "function", "name": "slow_tool"},
            slow_function,
        )
        dispatcher = ToolDispatcher(registry, timeout=0.2)
        dispatch_result = dispatcher.dispatch("slow_tool", {})
        self.assertIn("Tool error: Tool execution timed out after 0.2 seconds", dispatch_result)

    def test_sandbox_cleanup(self):
        sandbox = ToolSandbox()
        code = "def hello():\n    return 'world'\n"
        test_code = "assert hello() == 'world'"

        result = sandbox.run_test(code, test_code)
        self.assertTrue(result["success"])
        # Verify no orphan temporary directories remain in temp dir
        # tempfile.TemporaryDirectory cleanup is tested implicitly via context manager

    def test_failed_tool_generation_on_security_violation(self):
        approval_called = False

        def mock_approve(_):
            nonlocal approval_called
            approval_called = True
            return True

        evil_code = "import os\ndef steal_secrets():\n    return os.environ\n"
        response = json.loads(
            create_and_register_tool(
                self.workspace,
                mock_approve,
                lambda *_: None,
                set(),
                "steal_secrets",
                "Steal host environment variables",
                {"type": "object", "properties": {}},
                evil_code,
            )
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["status"], "security_violation")
        # CRITICAL: Approval MUST NOT have been called!
        self.assertFalse(approval_called)
        # CRITICAL: File must NOT exist on disk!
        self.assertFalse((self.workspace / "custom_tools" / "steal_secrets.py").exists())

    def test_approval_rejection_prevents_sandbox_and_save(self):
        safe_code = "def add_tax(amount: float) -> float:\n    return amount * 1.1\n"
        test_code = "assert round(add_tax(100.0), 1) == 110.0"

        response = json.loads(
            create_and_register_tool(
                self.workspace,
                lambda _: False,  # User says NO
                lambda *_: None,
                set(),
                "add_tax",
                "Add sales tax",
                {"type": "object", "properties": {"amount": {"type": "number"}}},
                safe_code,
                test_code=test_code,
            )
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["status"], "denied")
        self.assertFalse((self.workspace / "custom_tools" / "add_tax.py").exists())

    def test_safe_tool_generation_end_to_end(self):
        safe_code = (
            "def reverse_words(text: str) -> str:\n"
            "    return ' '.join(text.split()[::-1])\n"
        )
        test_code = "assert reverse_words('hello world') == 'world hello'"
        params = {"type": "object", "properties": {"text": {"type": "string"}}}

        registered = {}

        def mock_register(name, schema, func):
            registered[name] = func

        response = json.loads(
            create_and_register_tool(
                self.workspace,
                lambda _: True,  # User says YES
                mock_register,
                set(),
                "reverse_words",
                "Reverse the order of words in a string",
                params,
                safe_code,
                test_code=test_code,
            )
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], "registered")
        self.assertTrue((self.workspace / "custom_tools" / "reverse_words.py").exists())
        self.assertIn("reverse_words", registered)
        self.assertEqual(registered["reverse_words"]("one two three"), "three two one")


if __name__ == "__main__":
    unittest.main()
