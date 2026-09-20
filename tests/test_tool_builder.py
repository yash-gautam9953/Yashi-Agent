import json
import tempfile
import unittest
from pathlib import Path

from tools.tool_builder import request_new_tool


class ToolBuilderTests(unittest.TestCase):
    def test_denied_proposal_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = json.loads(
                request_new_tool(
                    workspace,
                    lambda _: False,
                    "browser_open",
                    "Open a webpage",
                    "The user asked to open a website",
                )
            )

            self.assertFalse(result["ok"])
            self.assertFalse((workspace / "tool_proposals").exists())

    def test_approved_proposal_requires_review(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = json.loads(
                request_new_tool(
                    workspace,
                    lambda _: True,
                    "browser_open",
                    "Open a webpage",
                    "The user asked to open a website",
                    risk_level="approval",
                    suggested_inputs="url: validated HTTPS URL",
                )
            )
            proposal = workspace / result["proposal_path"]

            self.assertTrue(result["ok"])
            self.assertEqual(result["status"], "review_required")
            self.assertTrue(proposal.exists())
            self.assertEqual(
                json.loads(proposal.read_text(encoding="utf-8"))["status"],
                "review_required"
            )

    def test_invalid_tool_name_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                request_new_tool(
                    Path(directory),
                    lambda _: True,
                    "run-command",
                    "Run a command",
                    "Needed for a task",
                )


if __name__ == "__main__":
    unittest.main()
