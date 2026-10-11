import json
import os
import tempfile
import unittest
from pathlib import Path

from agent.correction import (
    MAX_CORRECTION_ATTEMPTS,
    SelfCorrectionLoop,
    SelfCorrectionManager,
    analyze_failure,
    sanitize_error,
)
from tools.custom_tool_manager import create_and_register_tool
from tools.registry import ToolRegistry


class SelfCorrectionTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        (self.workspace / "custom_tools").mkdir(parents=True, exist_ok=True)
        (self.workspace / "config").mkdir(parents=True, exist_ok=True)

        self.registry = ToolRegistry()
        self.manager = SelfCorrectionManager(max_attempts=3)
        self.loop = SelfCorrectionLoop(
            workspace=self.workspace,
            registry=self.registry,
            manager=self.manager,
            max_attempts=3,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_successful_first_attempt(self):
        """Test tool generated and validated successfully on attempt 1 without retry."""
        def generator(attempt, error_info):
            self.assertEqual(attempt, 1)
            self.assertIsNone(error_info)
            code = "def add_nums(a: int, b: int) -> int:\n    return a + b\n"
            test_code = "assert add_nums(2, 3) == 5\n"
            return code, test_code

        approvals = []

        def approve(report):
            approvals.append(report.name)
            return True

        result = self.loop.run(
            name="add_nums",
            description="Add two numbers together",
            parameters={"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}},
            code_generator=generator,
            approve_callback=approve,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["attempts_used"], 1)
        self.assertEqual(len(approvals), 1)

        # In-memory history check
        history = self.manager.get_history("add_nums")
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].attempt_number, 1)
        self.assertEqual(history[0].status, "registered")
        self.assertTrue(history[0].approved)
        self.assertTrue(history[0].security_safe)

        # File exists on disk
        self.assertTrue((self.workspace / "custom_tools" / "add_nums.py").exists())

    def test_failure_then_successful_retry(self):
        """Test sandbox failure on attempt 1 triggers analysis and successful attempt 2."""
        attempts_called = []

        def generator(attempt, error_info):
            attempts_called.append(attempt)
            if attempt == 1:
                self.assertIsNone(error_info)
                # Bug: returns 0 instead of sum
                code = "def multiply_nums(a: int, b: int) -> int:\n    return 0\n"
                test_code = "assert multiply_nums(3, 4) == 12\n"
                return code, test_code
            else:
                self.assertIsNotNone(error_info)
                self.assertEqual(error_info["status"], "test_failed")
                self.assertEqual(error_info["attempt"], 1)
                self.assertEqual(error_info["error_type"], "AssertionError")
                self.assertIn("AssertionError", error_info["error"])
                # Corrected implementation
                code = "def multiply_nums(a: int, b: int) -> int:\n    return a * b\n"
                test_code = "assert multiply_nums(3, 4) == 12\n"
                return code, test_code

        approvals = []

        def approve(report):
            approvals.append(report.code)
            return True

        result = self.loop.run(
            name="multiply_nums",
            description="Multiply two numbers",
            parameters={"type": "object", "properties": {}},
            code_generator=generator,
            approve_callback=approve,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "registered")
        self.assertEqual(result["attempts_used"], 2)
        self.assertEqual(attempts_called, [1, 2])
        # Approved both attempt 1 and modified attempt 2
        self.assertEqual(len(approvals), 2)

        # In-memory debugging history has both attempts
        history = self.manager.get_history("multiply_nums")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].attempt_number, 1)
        self.assertEqual(history[0].status, "test_failed")
        self.assertEqual(history[0].error_type, "AssertionError")
        self.assertEqual(history[1].attempt_number, 2)
        self.assertEqual(history[1].status, "registered")

    def test_three_failed_attempts(self):
        """Test maximum 3 attempts are executed and then halts with explanation."""
        attempts_called = []

        def generator(attempt, error_info):
            attempts_called.append(attempt)
            # Code continues to fail
            code = f"def always_fails(x: int) -> int:\n    raise FileNotFoundError('Directory missing for attempt {attempt}')\n"
            test_code = "always_fails(1)\n"
            return code, test_code

        result = self.loop.run(
            name="always_fails",
            description="Tool that always fails",
            parameters={"type": "object", "properties": {}},
            code_generator=generator,
            approve_callback=lambda _: True,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "max_attempts_exceeded")
        self.assertEqual(result["attempt"], 3)
        self.assertEqual(result["attempts_remaining"], 0)
        self.assertEqual(result["error_type"], "FileNotFoundError")
        self.assertIn("Maximum retry attempts", result["message"])
        self.assertIn("FileNotFoundError", result["error"])
        self.assertIn("yashi_explanation", result)
        self.assertEqual(attempts_called, [1, 2, 3])

        # Exactly 3 attempt records kept in memory
        history = self.manager.get_history("always_fails")
        self.assertEqual(len(history), 3)
        for idx, rec in enumerate(history, 1):
            self.assertEqual(rec.attempt_number, idx)
            self.assertEqual(rec.status, "test_failed")
            self.assertEqual(rec.error_type, "FileNotFoundError")

    def test_security_failure_during_retry(self):
        """Test security inspection is strictly enforced during retries and blocks violations."""
        def generator(attempt, error_info):
            if attempt == 1:
                # Safe, but test fails
                code = "def secure_calc():\n    return 1\n"
                test_code = "assert secure_calc() == 99\n"
                return code, test_code
            elif attempt == 2:
                # Attacker/hallucinated revision attempts blocked os/subprocess
                code = "import subprocess\ndef secure_calc():\n    return subprocess.run(['echo', '99'])\n"
                test_code = "assert True\n"
                return code, test_code
            else:
                return "def secure_calc(): return 99\n", "assert True\n"

        result = self.loop.run(
            name="secure_calc",
            description="Secure calculator",
            parameters={"type": "object", "properties": {}},
            code_generator=generator,
            approve_callback=lambda _: True,
        )

        history = self.manager.get_history("secure_calc")
        # Attempt 1 failed sandbox
        self.assertEqual(history[0].status, "test_failed")
        self.assertTrue(history[0].security_safe)

        # Attempt 2 failed static security inspection!
        self.assertEqual(history[1].status, "security_violation")
        self.assertFalse(history[1].security_safe)
        self.assertIn("subprocess", "; ".join(history[1].security_violations))

    def test_approval_after_modified_code(self):
        """Test approval is required again when code changes, and rejection halts execution."""
        code_v1 = "def prompt_test(): return 1\n"
        code_v2 = "def prompt_test(): return 2\n"

        approval_prompts = []

        def approve_callback(report):
            approval_prompts.append(report.code.strip())
            if len(approval_prompts) == 1:
                return True  # Approve attempt 1
            else:
                return False  # Reject attempt 2 (modified code)

        def generator(attempt, error_info):
            if attempt == 1:
                return code_v1, "assert prompt_test() == 999\n"
            return code_v2, "assert prompt_test() == 2\n"

        result = self.loop.run(
            name="prompt_test",
            description="Testing approval prompts",
            parameters={"type": "object", "properties": {}},
            code_generator=generator,
            approve_callback=approve_callback,
        )

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["attempt"], 2)
        # Verify approval prompt was called twice (once for code_v1, once for modified code_v2)
        self.assertEqual(len(approval_prompts), 2)
        self.assertIn("prompt_test(): return 1", approval_prompts[0])
        self.assertIn("prompt_test(): return 2", approval_prompts[1])

        history = self.manager.get_history("prompt_test")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1].status, "denied")
        self.assertFalse(history[1].approved)

    def test_no_infinite_loop(self):
        """Test system cannot be forced into an infinite loop beyond MAX_CORRECTION_ATTEMPTS."""
        manager = SelfCorrectionManager(max_attempts=3)

        # Directly invoke create_and_register_tool 5 times with a failing tool
        for attempt in range(1, 4):
            res_str = create_and_register_tool(
                workspace=self.workspace,
                approve=lambda _: True,
                register_callback=lambda *_: None,
                core_tools={"create_and_register_tool"},
                name="loop_breaker",
                description="Loop test tool",
                parameters={"type": "object", "properties": {}},
                code="def loop_breaker(): return 0\n",
                test_code="assert loop_breaker() == 1\n",
                correction_manager=manager,
            )
            data = json.loads(res_str)
            if attempt < 3:
                self.assertEqual(data["status"], "test_failed")
                self.assertEqual(data["attempt"], attempt)
            else:
                self.assertEqual(data["status"], "max_attempts_exceeded")
                self.assertEqual(data["attempt"], 3)

        # 4th and 5th call: immediately rejected without sandbox execution
        res_4 = json.loads(create_and_register_tool(
            workspace=self.workspace,
            approve=lambda _: True,
            register_callback=lambda *_: None,
            core_tools={"create_and_register_tool"},
            name="loop_breaker",
            description="Loop test tool",
            parameters={"type": "object", "properties": {}},
            code="def loop_breaker(): return 0\n",
            test_code="assert loop_breaker() == 1\n",
            correction_manager=manager,
        ))
        self.assertFalse(res_4["ok"])
        self.assertEqual(res_4["status"], "max_attempts_exceeded")
        self.assertIn("Maximum retry attempts", res_4["message"])

        # History is capped and preserved
        self.assertEqual(len(manager.get_history("loop_breaker")), 3)

    def test_secret_sanitization(self):
        """Test API keys and secrets are thoroughly redacted from sandbox error output."""
        os.environ["AZURE_OPENAI_API_KEY"] = "super-secret-key-1234567890abcdef"
        raw_error = (
            "Traceback (most recent call last):\n"
            "File 'test.py', line 2: AuthenticationFailed(api_key='super-secret-key-1234567890abcdef', "
            "token='Bearer sk-abcdef1234567890abcdef1234')\n"
        )
        sanitized = sanitize_error(raw_error)
        self.assertNotIn("super-secret-key-1234567890abcdef", sanitized)
        self.assertNotIn("sk-abcdef1234567890abcdef1234", sanitized)
        self.assertIn("[REDACTED_SECRET]", sanitized)

    def test_failure_analysis_phrasing(self):
        """Test specific failure phrasing matches requested pattern: I found the problem..."""
        analysis = analyze_failure("FileNotFoundError: [Errno 2] No such file or directory: 'data/test.txt'")
        self.assertEqual(analysis["error_type"], "FileNotFoundError")
        self.assertIn("I found the problem.", analysis["yashi_explanation"])
        self.assertIn("I can revise the tool.", analysis["yashi_explanation"])


if __name__ == "__main__":
    unittest.main()
