from pathlib import Path


SENSITIVE_NAMES = {
    ".env",
    ".env.local",
    ".git-credentials",
    "credentials.json",
    "id_rsa",
    "id_ed25519",
}
SENSITIVE_SUFFIXES = {".key", ".pem", ".p12", ".pfx"}


def is_sensitive_path(path: Path) -> bool:
    return (
        any(part.lower() in SENSITIVE_NAMES for part in path.parts)
        or path.suffix.lower() in SENSITIVE_SUFFIXES
    )


def safe_path(workspace, file_path):
    path = (workspace / file_path).resolve()
    if path != workspace and workspace not in path.parents:
        raise ValueError("File path must stay inside the workspace")

    if is_sensitive_path(path):
        raise PermissionError("Access to sensitive files is blocked")

    return path
