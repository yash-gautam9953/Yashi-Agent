import json
import tempfile
import unittest
from pathlib import Path

from tools.workflows import create_workflow, run_workflow


class WorkflowTests(unittest.TestCase):
    def test_workflow_creation_requires_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            result = json.loads(
                create_workflow(
                    workspace,
                    lambda _: False,
                    {"list_directory"},
                    "inspect_project",
                    "Inspect the project",
                    [{"tool": "list_directory", "arguments": {}}],
                )
            )

            self.assertFalse(result["ok"])
            self.assertFalse((workspace / "config" / "workflows.json").exists())

    def test_approved_workflow_runs_existing_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            tools = {"greet": lambda name: f"Hello {name}"}
            create_workflow(
                workspace,
                lambda _: True,
                set(tools),
                "greeting",
                "Say hello",
                [{"tool": "greet", "arguments": {"name": "user"}}],
            )

            result = json.loads(run_workflow(workspace, tools, "greeting"))

            self.assertTrue(result["ok"])
            self.assertEqual(result["steps"][0]["result"], "Hello user")

    def test_workflow_cannot_reference_unknown_tool(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                create_workflow(
                    Path(directory),
                    lambda _: True,
                    {"read_file"},
                    "unsafe_workflow",
                    "Try an unknown tool",
                    [{"tool": "execute_anything", "arguments": {}}],
                )


if __name__ == "__main__":
    unittest.main()
