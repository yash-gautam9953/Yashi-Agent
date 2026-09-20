import json
from pathlib import Path
from typing import Callable

from security.path_policy import safe_path


Approval = Callable[[str], bool]
Redact = Callable[[str], str]


def list_directory(workspace: Path, directory: str = ".") -> str:
    path = safe_path(workspace, directory)
    if not path.is_dir():
        raise NotADirectoryError(directory)

    entries = [
        {
            "name": entry.name,
            "type": "directory" if entry.is_dir() else "file",
        }
        for entry in sorted(path.iterdir(), key=lambda item: item.name.lower())
        if entry.name not in {".git", "__pycache__"}
    ]
    return json.dumps(entries[:200])


def file_metadata(workspace: Path, file_path: str) -> str:
    path = safe_path(workspace, file_path)
    metadata = path.stat()
    return json.dumps({
        "path": path.relative_to(workspace).as_posix(),
        "type": "directory" if path.is_dir() else "file",
        "size_bytes": metadata.st_size,
        "modified_timestamp": metadata.st_mtime,
    })


def _allowed_media_root(workspace: Path, config: dict, directory: str) -> Path:
    configured_roots = config.get("media_roots", ["."])
    if not isinstance(configured_roots, list):
        raise ValueError("media_roots must be a list")

    allowed_roots = []
    for configured_root in configured_roots:
        root = Path(configured_root).expanduser()
        if not root.is_absolute():
            root = workspace / root
        allowed_roots.append(root.resolve())

    requested = Path(directory).expanduser()
    if not requested.is_absolute():
        requested = workspace / requested
    requested = requested.resolve()

    if not any(root == requested or root in requested.parents for root in allowed_roots):
        raise PermissionError("Media search path is not configured")
    if not requested.is_dir():
        raise NotADirectoryError(directory)
    return requested


def search_media(
    workspace: Path,
    config: dict,
    directory: str = ".",
    name_pattern: str = "*",
) -> str:
    root = _allowed_media_root(workspace, config, directory)
    extensions = config.get("media_extensions", [])
    max_results = config.get("max_media_results", 200)
    if not isinstance(extensions, list) or not isinstance(max_results, int):
        raise ValueError("Invalid media search configuration")

    allowed_extensions = {str(extension).lower() for extension in extensions}
    matches = []
    for path in root.rglob(name_pattern):
        if not path.is_file() or path.suffix.lower() not in allowed_extensions:
            continue
        matches.append({
            "name": path.name,
            "path": str(path),
            "size_bytes": path.stat().st_size,
        })
        if len(matches) >= max_results:
            break
    return json.dumps(matches)


def read_file(workspace: Path, redact: Redact, file_path: str) -> str:
    path = safe_path(workspace, file_path)
    return redact(path.read_text(encoding="utf-8"))


def search_files(
    workspace: Path,
    pattern: str,
    directory: str = "."
) -> str:
    root = safe_path(workspace, directory)
    if not root.is_dir():
        raise NotADirectoryError(directory)

    matches = []
    for path in root.rglob(pattern):
        try:
            safe_path(workspace, path.relative_to(workspace))
        except PermissionError:
            continue
        if path.is_file() or path.is_dir():
            matches.append(path.relative_to(workspace).as_posix())

    return json.dumps(sorted(matches))


def create_file(
    workspace: Path,
    approve: Approval,
    file_path: str,
    content: str
) -> str:
    path = safe_path(workspace, file_path)
    if path.exists():
        if not approve(f"Overwrite existing file '{path.relative_to(workspace)}'?"):
            return "File creation denied by user"
    path.write_text(content, encoding="utf-8")
    return f"Created {file_path}"


def edit_file(
    workspace: Path,
    approve: Approval,
    file_path: str,
    content: str
) -> str:
    path = safe_path(workspace, file_path)
    if path.exists() and not approve(
        f"Overwrite existing file '{path.relative_to(workspace)}'?"
    ):
        return "Edit denied by user"
    path.write_text(content, encoding="utf-8")
    return f"Updated {file_path}"


def delete_file(
    workspace: Path,
    approve: Approval,
    file_path: str,
) -> str:
    path = safe_path(workspace, file_path)
    if not path.exists():
        raise FileNotFoundError(file_path)
    if not path.is_file():
        raise IsADirectoryError(file_path)
    if not approve(
        f"Delete: {path.relative_to(workspace)}\n"
        "Reason: remove the requested workspace file\n"
        "Allow?"
    ):
        return "Delete denied by user"
    path.unlink()
    return f"Deleted {file_path}"


def rename_file(
    workspace: Path,
    approve: Approval,
    source: str,
    destination: str
) -> str:
    source_path = safe_path(workspace, source)
    destination_path = safe_path(workspace, destination)
    if not source_path.exists():
        raise FileNotFoundError(source)
    if destination_path.exists() and not approve(
        f"Overwrite existing path '{destination_path.relative_to(workspace)}'?"
    ):
        return "Rename denied by user"
    source_path.rename(destination_path)
    return f"Renamed {source} to {destination}"


def create_directory(workspace: Path, directory: str) -> str:
    path = safe_path(workspace, directory)
    if path.exists():
        if path.is_dir():
            return f"Directory already exists: {directory}"
        raise FileExistsError(directory)
    path.mkdir(parents=True)
    return f"Created directory {directory}"
