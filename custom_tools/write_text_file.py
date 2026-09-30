from pathlib import Path

def write_text_file(path: str, content: str) -> dict:
    """Write UTF-8 text content to a file and return confirmation."""
    target = Path(path)
    if target.is_absolute() or ".." in target.parts:
        return {"ok": False, "error": "Only relative paths within the working directory are allowed."}
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return {"ok": True, "path": str(target), "bytes_written": len(content.encode("utf-8"))}
