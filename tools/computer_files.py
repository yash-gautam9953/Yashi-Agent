import ctypes
import json
from pathlib import Path
from typing import Callable

from security.path_policy import is_sensitive_path


Approval = Callable[[str], bool]
Redact = Callable[[str], str]
MAX_DIRECTORY_ENTRIES = 200
MAX_FILE_OUTPUT = 12000


def list_drives() -> str:
    if hasattr(ctypes, "windll"):
        mask = ctypes.windll.kernel32.GetLogicalDrives()
        drives = [
            {"path": f"{chr(65 + index)}:\\", "type": "drive"}
            for index in range(26)
            if mask & (1 << index)
        ]
    else:
        drives = [{"path": "/", "type": "filesystem"}]
    return json.dumps(drives)


def _resolve_location(workspace: Path, location: str) -> Path:
    path = Path(location).expanduser()
    if not path.is_absolute():
        path = workspace / path
    path = path.resolve()
    if is_sensitive_path(path):
        raise PermissionError("Access to sensitive locations is blocked")
    return path


def _approve_external_read(
    workspace: Path,
    path: Path,
    approve: Approval,
    action: str,
) -> None:
    if workspace == path or workspace in path.parents:
        return
    if not approve(
        f"Read: {path}\n"
        f"Reason: {action} outside the workspace\n"
        "Allow?"
    ):
        raise PermissionError("External read denied by user")


def list_location(
    workspace: Path,
    approve: Approval,
    location: str,
) -> str:
    path = _resolve_location(workspace, location)
    if not path.is_dir():
        raise NotADirectoryError(location)
    _approve_external_read(workspace, path, approve, "list directory contents")

    entries = [
        {
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
        }
        for entry in sorted(path.iterdir(), key=lambda item: item.name.lower())
        if not is_sensitive_path(entry)
    ]
    return json.dumps(entries[:MAX_DIRECTORY_ENTRIES])


def read_external_file(
    workspace: Path,
    approve: Approval,
    redact: Redact,
    file_path: str,
) -> str:
    path = _resolve_location(workspace, file_path)
    if not path.is_file():
        raise FileNotFoundError(file_path)
    _approve_external_read(workspace, path, approve, "read file contents")
    if path.stat().st_size > MAX_FILE_OUTPUT:
        raise ValueError("File is too large to read through the agent")
    return redact(path.read_text(encoding="utf-8"))
