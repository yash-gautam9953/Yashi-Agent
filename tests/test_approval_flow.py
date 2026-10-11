import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from security.inspector import SecurityInspector, ToolSecurityReport
from tools.custom_tool_manager import create_and_register_tool
from ui.console import Console


class ApprovalFlowTests(unittest.TestCase):
    def setUp(self):
        self.inspector = SecurityInspector()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.console = Console()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_full_source_display_never_truncated(self):
        # Generate code with 35 distinct lines
        code_lines = ["def multi_line_tool(x: int) -> int:"]
        for i in range(1, 30):
            code_lines.append(f"    x = x + {i}")
        code_lines.append("    return x")
        code = "\n".join(code_lines) + "\n"

        report = self.inspector.analyze_tool(
            name="multi_line_tool",
            description="A tool with many lines to test full display",
            code=code,
        )

        screen_output = report.format_screen()
        # Verify that all 30 generated lines exist completely in the screen
        for line in code_lines:
            self.assertIn(line, screen_output)

        # Verify no truncation ellipsis in code section
        self.assertNotIn("...", screen_output)

    def test_security_report_structure_and_details(self):
        code = (
            "from pathlib import Path\n"
            "def list_files(ext: str) -> list:\n"
            "    p = Path('.')\n"
            "    return [f.name for f in p.glob(f'*.{ext}')]\n"
        )
        report = self.inspector.analyze_tool(
            name="list_files",
            description="Find files with specified extension in workspace",
            code=code,
            target_file="custom_tools/list_files.py",
        )

        self.assertTrue(report.is_safe)
        self.assertEqual(report.risk_level, "LOW")
        self.assertIn("pathlib", report.detected_imports)
        self.assertIn("relative workspace", report.permissions["filesystem"])
        self.assertIn("Blocked", report.permissions["network"])
        self.assertIn("Blocked", report.permissions["environment"])
        self.assertIn("Blocked", report.permissions["shell"])

        detailed = report.format_detailed_report()
        self.assertIn("DETAILED SECURITY INSPECTION REPORT", detailed)
        self.assertIn("Target File:     custom_tools/list_files.py", detailed)
        self.assertIn("PASSED (0 violations detected)", detailed)
        self.assertIn("Process & Shell execution check", detailed)
        self.assertIn("Network & Socket check", detailed)

    def test_approval_granted_flow(self):
        code = "def double_val(n: int) -> int:\n    return n * 2\n"
        test_code = "assert double_val(4) == 8"

        approval_received_report = None

        def mock_approve(report_arg):
            nonlocal approval_received_report
            approval_received_report = report_arg
            return True

        registered = {}

        response = json.loads(
            create_and_register_tool(
                self.workspace,
                mock_approve,
                lambda name, schema, func: registered.update({name: func}),
                set(),
                "double_val",
                "Double an integer value",
                {"type": "object", "properties": {"n": {"type": "integer"}}},
                code,
                test_code=test_code,
            )
        )

        self.assertTrue(response["ok"])
        self.assertEqual(response["status"], "registered")
        self.assertIsNotNone(approval_received_report)
        self.assertIsInstance(approval_received_report, ToolSecurityReport)
        self.assertEqual(approval_received_report.tool_name, "double_val")
        self.assertTrue((self.workspace / "custom_tools" / "double_val.py").exists())
        self.assertIn("double_val", registered)
        self.assertEqual(registered["double_val"](10), 20)

    def test_rejection_flow(self):
        code = "def triple_val(n: int) -> int:\n    return n * 3\n"
        test_code = "assert triple_val(2) == 6"

        approval_called = False

        def mock_approve(report_arg):
            nonlocal approval_called
            approval_called = True
            return False  # User REJECTS

        registered = {}

        response = json.loads(
            create_and_register_tool(
                self.workspace,
                mock_approve,
                lambda name, schema, func: registered.update({name: func}),
                set(),
                "triple_val",
                "Triple an integer value",
                {"type": "object", "properties": {"n": {"type": "integer"}}},
                code,
                test_code=test_code,
            )
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["status"], "denied")
        self.assertTrue(approval_called)
        # Verify tool is NOT saved to disk
        self.assertFalse((self.workspace / "custom_tools" / "triple_val.py").exists())
        # Verify tool is NOT registered
        self.assertNotIn("triple_val", registered)

    def test_dangerous_tool_rejected_automatically(self):
        approval_called = False

        def mock_approve(_):
            nonlocal approval_called
            approval_called = True
            return True

        evil_code = "import shutil\ndef wipe():\n    pass\n"

        response = json.loads(
            create_and_register_tool(
                self.workspace,
                mock_approve,
                lambda *_: None,
                set(),
                "wipe",
                "Dangerous tool",
                {"type": "object", "properties": {}},
                evil_code,
            )
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["status"], "security_violation")
        # Critical: user prompt was NEVER called
        self.assertFalse(approval_called)
        # Critical: tool was NOT saved
        self.assertFalse((self.workspace / "custom_tools" / "wipe.py").exists())

    def test_failed_sandbox_test_after_approval(self):
        code = "def buggy_tool(x: int) -> int:\n    return x + 1\n"
        # Test assertion deliberately fails
        failing_test = "assert buggy_tool(5) == 999"

        approval_called = False

        def mock_approve(_):
            nonlocal approval_called
            approval_called = True
            return True  # User approves

        registered = {}

        response = json.loads(
            create_and_register_tool(
                self.workspace,
                mock_approve,
                lambda name, schema, func: registered.update({name: func}),
                set(),
                "buggy_tool",
                "Tool that fails its own assertions",
                {"type": "object", "properties": {"x": {"type": "integer"}}},
                code,
                test_code=failing_test,
            )
        )

        self.assertFalse(response["ok"])
        self.assertEqual(response["status"], "test_failed")
        self.assertTrue(approval_called)
        # Verify tool is NOT saved to disk despite user approval
        self.assertFalse((self.workspace / "custom_tools" / "buggy_tool.py").exists())
        # Verify tool is NOT registered
        self.assertNotIn("buggy_tool", registered)

    @patch("builtins.input", side_effect=["a"])
    def test_console_approval_prompt_approve(self, _):
        report = self.inspector.analyze_tool("dummy", "Dummy tool", "def dummy(): pass\n")
        result = self.console.approval(report)
        self.assertTrue(result)

    @patch("builtins.input", side_effect=["r"])
    def test_console_approval_prompt_reject(self, _):
        report = self.inspector.analyze_tool("dummy", "Dummy tool", "def dummy(): pass\n")
        result = self.console.approval(report)
        self.assertFalse(result)

    @patch("builtins.input", side_effect=["v", "a"])
    def test_console_approval_prompt_view_report_then_approve(self, _):
        report = self.inspector.analyze_tool("dummy", "Dummy tool", "def dummy(): pass\n")
        result = self.console.approval(report)
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
