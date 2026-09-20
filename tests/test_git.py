import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.git import (
    git_branch,
    git_commit,
    git_create_branch,
    git_diff,
    git_checkout,
    git_log,
    git_pull,
    git_push,
    git_status,
)


class GitToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self._git("init", "-q")
        self._git("config", "user.email", "agent-test@example.invalid")
        self._git("config", "user.name", "Agent Test")
        (self.workspace / "README.md").write_text("initial\n", encoding="utf-8")
        self._git("add", "README.md")
        self._git("commit", "-q", "-m", "initial commit")

    def tearDown(self):
        self.temp_dir.cleanup()

    def _git(self, *arguments, cwd=None):
        return subprocess.run(
            ["git", *arguments],
            cwd=cwd or self.workspace,
            capture_output=True,
            text=True,
            check=True,
        )

    @staticmethod
    def _redact(value):
        return value

    def test_read_only_tools_return_structured_results(self):
        status = json.loads(git_status(self.workspace, self._redact))
        diff = json.loads(git_diff(self.workspace, self._redact))
        log = json.loads(git_log(self.workspace, self._redact, limit=5))
        branches = json.loads(git_branch(self.workspace, self._redact))

        self.assertTrue(status["ok"])
        self.assertIn("##", status["stdout"])
        self.assertTrue(diff["ok"])
        self.assertTrue(log["ok"])
        self.assertIn("initial commit", log["stdout"])
        self.assertTrue(branches["ok"])

    def test_repository_outside_workspace_is_rejected(self):
        child = self.workspace / "project"
        child.mkdir()

        with self.assertRaises(PermissionError):
            git_status(child, self._redact)

    def test_create_branch_requires_approval(self):
        denied = json.loads(
            git_create_branch(
                self.workspace,
                lambda _: False,
                self._redact,
                "feature/test"
            )
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["error"], "User denied")

        created = json.loads(
            git_create_branch(
                self.workspace,
                lambda _: True,
                self._redact,
                "feature/test"
            )
        )
        self.assertTrue(created["ok"])

    def test_commit_requires_approval(self):
        (self.workspace / "README.md").write_text("changed\n", encoding="utf-8")
        self._git("add", "README.md")

        denied = json.loads(
            git_commit(
                self.workspace,
                lambda _: False,
                self._redact,
                "change README"
            )
        )
        self.assertFalse(denied["ok"])

        committed = json.loads(
            git_commit(
                self.workspace,
                lambda _: True,
                self._redact,
                "change README"
            )
        )
        self.assertTrue(committed["ok"])

    def test_push_requires_approval_and_remote_is_validated(self):
        denied = json.loads(
            git_push(
                self.workspace,
                lambda _: False,
                self._redact,
                remote="origin",
                branch="main"
            )
        )
        self.assertFalse(denied["ok"])

        with self.assertRaises(ValueError):
            git_push(
                self.workspace,
                lambda _: True,
                self._redact,
                remote="../outside"
            )

    def test_pull_requires_approval(self):
        denied = json.loads(
            git_pull(
                self.workspace,
                lambda _: False,
                self._redact,
                remote="origin",
                branch="main"
            )
        )
        self.assertFalse(denied["ok"])
        self.assertEqual(denied["action"], "git_pull")

    def test_checkout_requires_approval(self):
        self._git("branch", "feature/test")

        denied = json.loads(
            git_checkout(
                self.workspace,
                lambda _: False,
                self._redact,
                "feature/test"
            )
        )
        self.assertFalse(denied["ok"])

        checked_out = json.loads(
            git_checkout(
                self.workspace,
                lambda _: True,
                self._redact,
                "feature/test"
            )
        )
        self.assertTrue(checked_out["ok"])


if __name__ == "__main__":
    unittest.main()
