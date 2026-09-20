import json
import re
import subprocess
from pathlib import Path
from typing import Callable


Approval = Callable[[str], bool]
Redact = Callable[[str], str]

_SAFE_NAME = re.compile(r"^[A-Za-z0-9._/-]+$")
_SAFE_REMOTE = re.compile(r"^[A-Za-z0-9._-]+$")


def _repo_root(workspace: Path) -> Path:
    completed = subprocess.run(
        ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if completed.returncode != 0:
        raise ValueError("Workspace is not a Git repository")

    root = Path(completed.stdout.strip()).resolve()
    if root != workspace.resolve():
        raise PermissionError("Git repository root must be the workspace")
    return root


def _run_git(
    workspace: Path,
    arguments: list[str],
    redact: Redact,
) -> str:
    _repo_root(workspace)
    completed = subprocess.run(
        ["git", "-C", str(workspace), *arguments],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.dumps({
        "ok": completed.returncode == 0,
        "command": ["git", *arguments],
        "exit_code": completed.returncode,
        "stdout": redact(completed.stdout),
        "stderr": redact(completed.stderr),
    })


def _validate_name(value: str, label: str) -> None:
    if not value or not _SAFE_NAME.fullmatch(value) or value.startswith("-"):
        raise ValueError(f"Invalid Git {label}")


def _validate_remote(value: str) -> None:
    if not value or not _SAFE_REMOTE.fullmatch(value) or value.startswith("-"):
        raise ValueError("Invalid Git remote name")


def git_status(workspace: Path, redact: Redact) -> str:
    return _run_git(workspace, ["status", "--short", "--branch"], redact)


def git_diff(workspace: Path, redact: Redact, cached: bool = False) -> str:
    arguments = ["diff"]
    if cached:
        arguments.append("--cached")
    return _run_git(workspace, arguments, redact)


def git_log(workspace: Path, redact: Redact, limit: int = 10) -> str:
    if not 1 <= limit <= 50:
        raise ValueError("Git log limit must be between 1 and 50")
    return _run_git(
        workspace,
        ["log", f"-{limit}", "--oneline", "--decorate"],
        redact,
    )


def git_branch(workspace: Path, redact: Redact) -> str:
    return _run_git(
        workspace,
        ["branch", "--list", "--format=%(refname:short)"],
        redact,
    )


def git_create_branch(
    workspace: Path,
    approve: Approval,
    redact: Redact,
    name: str,
) -> str:
    _validate_name(name, "branch name")
    if not approve(
        f"Run: git branch {name}\nReason: create a local branch\nAllow?"
    ):
        return json.dumps({"ok": False, "action": "git_create_branch", "error": "User denied"})
    return _run_git(workspace, ["branch", name], redact)


def git_commit(
    workspace: Path,
    approve: Approval,
    redact: Redact,
    message: str,
) -> str:
    if not message.strip() or "\n" in message or "\r" in message:
        raise ValueError("Commit message must be a non-empty single line")
    if not approve(
        f"Run: git commit -m {message!r}\n"
        "Reason: create a permanent local commit from staged changes\n"
        "Allow?"
    ):
        return json.dumps({"ok": False, "action": "git_commit", "error": "User denied"})
    return _run_git(workspace, ["commit", "-m", message], redact)


def git_push(
    workspace: Path,
    approve: Approval,
    redact: Redact,
    remote: str = "origin",
    branch: str = "",
) -> str:
    _validate_remote(remote)
    if branch:
        _validate_name(branch, "branch name")
    arguments = ["push", remote]
    if branch:
        arguments.append(branch)
    command = "git " + " ".join(arguments)
    if not approve(
        f"Run: {command}\n"
        "Reason: send commits to a remote repository\n"
        "Allow?"
    ):
        return json.dumps({"ok": False, "action": "git_push", "error": "User denied"})
    return _run_git(workspace, arguments, redact)


def git_pull(
    workspace: Path,
    approve: Approval,
    redact: Redact,
    remote: str = "origin",
    branch: str = "",
) -> str:
    _validate_remote(remote)
    if branch:
        _validate_name(branch, "branch name")
    arguments = ["pull", "--ff-only", remote]
    if branch:
        arguments.append(branch)
    command = "git " + " ".join(arguments)
    if not approve(
        f"Run: {command}\n"
        "Reason: bring remote changes into the workspace\n"
        "Allow?"
    ):
        return json.dumps({"ok": False, "action": "git_pull", "error": "User denied"})
    return _run_git(workspace, arguments, redact)


def git_checkout(
    workspace: Path,
    approve: Approval,
    redact: Redact,
    branch: str,
) -> str:
    _validate_name(branch, "branch name")
    if not approve(
        f"Run: git checkout {branch}\n"
        "Reason: change the active workspace branch\n"
        "Allow?"
    ):
        return json.dumps({"ok": False, "action": "git_checkout", "error": "User denied"})
    return _run_git(workspace, ["checkout", branch], redact)
