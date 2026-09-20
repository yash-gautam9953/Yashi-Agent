import json
import tempfile
import unittest
from pathlib import Path

from security.path_policy import safe_path
from tools.filesystem import (
    create_directory,
    create_file,
    delete_file,
    edit_file,
    file_metadata,
    list_directory,
    rename_file,
    search_files,
    search_media,
)


class FilesystemTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_workspace_escape_is_blocked(self):
        with self.assertRaises(ValueError):
            safe_path(self.workspace, "../outside.txt")

    def test_sensitive_file_is_blocked(self):
        (self.workspace / ".env").write_text("API_KEY=hidden", encoding="utf-8")

        with self.assertRaises(PermissionError):
            safe_path(self.workspace, ".env")

    def test_overwrite_requires_approval(self):
        target = self.workspace / "app.py"
        target.write_text("old", encoding="utf-8")

        result = edit_file(self.workspace, lambda _: False, "app.py", "new")

        self.assertEqual(result, "Edit denied by user")
        self.assertEqual(target.read_text(encoding="utf-8"), "old")

    def test_delete_requires_approval(self):
        target = self.workspace / "remove.txt"
        target.write_text("remove", encoding="utf-8")

        denied = delete_file(self.workspace, lambda _: False, "remove.txt")

        self.assertEqual(denied, "Delete denied by user")
        self.assertTrue(target.exists())

        deleted = delete_file(self.workspace, lambda _: True, "remove.txt")

        self.assertEqual(deleted, "Deleted remove.txt")
        self.assertFalse(target.exists())

    def test_delete_does_not_remove_directories(self):
        (self.workspace / "folder").mkdir()

        with self.assertRaises(IsADirectoryError):
            delete_file(self.workspace, lambda _: True, "folder")

    def test_rename_file_moves_source(self):
        source = self.workspace / "before.py"
        source.write_text("print('ok')", encoding="utf-8")

        result = rename_file(
            self.workspace,
            lambda _: True,
            "before.py",
            "after.py"
        )

        self.assertEqual(result, "Renamed before.py to after.py")
        self.assertFalse(source.exists())
        self.assertEqual(
            (self.workspace / "after.py").read_text(encoding="utf-8"),
            "print('ok')"
        )

    def test_create_search_and_directory_tools(self):
        self.assertEqual(
            create_directory(self.workspace, "src"),
            "Created directory src"
        )
        self.assertEqual(
            create_file(
                self.workspace,
                lambda _: True,
                "src/app.py",
                "print('ok')"
            ),
            "Created src/app.py"
        )

        matches = json.loads(search_files(self.workspace, "*.py"))

        self.assertEqual(matches, ["src/app.py"])

    def test_directory_listing_and_metadata(self):
        (self.workspace / "movie.mp4").write_bytes(b"video")

        entries = json.loads(list_directory(self.workspace))
        metadata = json.loads(file_metadata(self.workspace, "movie.mp4"))

        self.assertEqual(entries, [{"name": "movie.mp4", "type": "file"}])
        self.assertEqual(metadata["type"], "file")
        self.assertEqual(metadata["size_bytes"], 5)

    def test_media_search_filters_extensions_and_roots(self):
        (self.workspace / "movie.mp4").write_bytes(b"video")
        (self.workspace / "notes.txt").write_text("not a movie", encoding="utf-8")
        config = {
            "media_roots": ["."],
            "media_extensions": [".mp4"],
            "max_media_results": 10,
        }

        matches = json.loads(search_media(self.workspace, config))

        self.assertEqual(matches[0]["name"], "movie.mp4")
        with self.assertRaises(PermissionError):
            search_media(self.workspace, config, "../")


if __name__ == "__main__":
    unittest.main()
