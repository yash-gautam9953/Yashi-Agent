import json
import tempfile
import unittest
from pathlib import Path

from tools.computer_files import (
    list_drives,
    list_location,
    read_external_file,
)


class ComputerFileTests(unittest.TestCase):
    def test_list_drives_returns_structured_locations(self):
        drives = json.loads(list_drives())

        self.assertIsInstance(drives, list)
        self.assertTrue(all("path" in drive for drive in drives))

    def test_external_directory_requires_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            external = Path(directory) / "external"
            workspace.mkdir()
            external.mkdir()
            (external / "movie.txt").write_text("movie", encoding="utf-8")

            with self.assertRaises(PermissionError):
                list_location(workspace, lambda _: False, str(external))

            entries = json.loads(
                list_location(workspace, lambda _: True, str(external))
            )

            self.assertEqual(entries, [{"name": "movie.txt", "type": "file"}])

    def test_external_file_requires_approval_and_redacts(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            external = Path(directory) / "notes.txt"
            workspace.mkdir()
            external.write_text("token=secret-value", encoding="utf-8")

            with self.assertRaises(PermissionError):
                read_external_file(
                    workspace,
                    lambda _: False,
                    lambda value: value,
                    str(external)
                )

            content = read_external_file(
                workspace,
                lambda _: True,
                lambda value: value.replace("secret-value", "[REDACTED]"),
                str(external)
            )

            self.assertEqual(content, "token=[REDACTED]")

    def test_sensitive_external_file_is_always_blocked(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / "workspace"
            secret = Path(directory) / ".env"
            workspace.mkdir()
            secret.write_text("TOKEN=secret", encoding="utf-8")

            with self.assertRaises(PermissionError):
                read_external_file(
                    workspace,
                    lambda _: True,
                    lambda value: value,
                    str(secret)
                )


if __name__ == "__main__":
    unittest.main()
