"""Persistent session memory store with security, privacy, and corruption recovery."""

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from security.policy import SENSITIVE_ENV_KEYS

SENSITIVE_KEY_NAMES = {
    "api_key",
    "apikey",
    "secret",
    "password",
    "token",
    "auth",
    "azure_openai_api_key",
    "openai_api_key",
    "access_token",
    "private_key",
    "secret_key",
}


@dataclass
class SessionData:
    """Container for an individual session's conversation and tool execution history."""

    session_id: str
    created_at: str
    updated_at: str
    response_id: Optional[str] = None
    messages: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    tool_metadata: List[Dict[str, Any]] = field(default_factory=list)
    debug_rejected_attempts: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionData":
        return cls(
            session_id=data.get("session_id", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            response_id=data.get("response_id"),
            messages=list(data.get("messages", [])),
            tool_calls=list(data.get("tool_calls", [])),
            tool_metadata=list(data.get("tool_metadata", [])),
            debug_rejected_attempts=list(data.get("debug_rejected_attempts", [])),
        )


def sanitize_text(text: str, extra_secrets: Optional[List[str]] = None) -> str:
    """Redact API keys, passwords, bearer tokens, and raw .env contents from text."""
    if not isinstance(text, str) or not text:
        return text

    sanitized = text

    # 1. Redact known sensitive environment variable values
    secrets_to_redact = set(extra_secrets or [])
    for key in SENSITIVE_ENV_KEYS:
        val = os.environ.get(key)
        if val and len(val.strip()) > 3:
            secrets_to_redact.add(val.strip())

    for val in os.environ.values():
        if len(val) >= 20 and any(c.isdigit() for c in val) and any(c.isalpha() for c in val):
            secrets_to_redact.add(val.strip())

    for s in secrets_to_redact:
        if s and len(s) > 3:
            sanitized = sanitized.replace(s, "[REDACTED_SECRET]")

    # 2. Redact patterns: raw .env assignments, Bearer tokens, OpenAI keys, passwords
    patterns = [
        (r"(?i)(api[_-]?key|secret|password|token|auth[_-]?token)\s*=\s*[^\r\n]+", r"\1=[REDACTED_SECRET]"),
        (r"(Bearer\s+)[A-Za-z0-9\-_\.]+", r"\1[REDACTED_TOKEN]"),
        (r"(api[_-]?key[\s:=]+['\"]?)[A-Za-z0-9\-_\.]+(['\"]?)", r"\1[REDACTED_KEY]\2"),
        (r"(password[\s:=]+['\"]?)[^\s'\"]+(['\"]?)", r"\1[REDACTED_PASSWORD]\2"),
        (r"sk-[A-Za-z0-9_\-]{20,}", "[REDACTED_KEY]"),
    ]
    for pattern, replacement in patterns:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    return sanitized


def sanitize_for_storage(data: Any, extra_secrets: Optional[List[str]] = None) -> Any:
    """Recursively filter secrets, API keys, passwords, and sensitive keys from any data structure."""
    if isinstance(data, str):
        return sanitize_text(data, extra_secrets)
    elif isinstance(data, dict):
        cleaned = {}
        for k, v in data.items():
            k_lower = str(k).lower()
            if any(s in k_lower for s in SENSITIVE_KEY_NAMES):
                cleaned[k] = "[REDACTED_SECRET]"
            else:
                cleaned[k] = sanitize_for_storage(v, extra_secrets)
        return cleaned
    elif isinstance(data, (list, tuple)):
        return [sanitize_for_storage(item, extra_secrets) for item in data]
    return data


class SessionStore:
    """Manages persistent session memory, conversation history, and tool records with privacy protection."""

    def __init__(self, storage_dir: Optional[Path] = None, auto_init: bool = True):
        self.storage_dir = storage_dir or (Path.cwd() / "sessions")
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.current_session: Optional[SessionData] = None
        if auto_init:
            self._init_or_load_default()

    @property
    def active_session_id(self) -> str:
        return self.current_session.session_id if self.current_session else ""

    @property
    def response_id(self) -> Optional[str]:
        return self.current_session.response_id if self.current_session else None

    @property
    def history(self) -> List[Dict[str, Any]]:
        """Backwards compatibility property returning messages."""
        return self.current_session.messages if self.current_session else []

    def update_response_id(self, response_id: Optional[str]) -> None:
        if self.current_session:
            self.current_session.response_id = response_id
            self.current_session.updated_at = datetime.now(timezone.utc).isoformat()
            self.save()

    def new_session(self, session_id: Optional[str] = None) -> SessionData:
        now = datetime.now(timezone.utc).isoformat()
        if not session_id:
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            short_id = uuid.uuid4().hex[:6]
            session_id = f"session_{ts}_{short_id}"

        self.current_session = SessionData(
            session_id=session_id,
            created_at=now,
            updated_at=now,
        )
        self.save()
        return self.current_session

    def add_message(self, role: str, content: Any) -> None:
        if not self.current_session:
            self.new_session()
        sanitized_content = sanitize_for_storage(content)
        now = datetime.now(timezone.utc).isoformat()
        self.current_session.messages.append({
            "role": role,
            "content": sanitized_content,
            "timestamp": now,
        })
        self.current_session.updated_at = now
        self.save()

    def add_turn(self, role: str, content: Any) -> None:
        """Backwards compatibility alias for add_message."""
        self.add_message(role, content)

    def record_tool_call(
        self,
        tool_name: str,
        arguments: Any,
        output: Any,
        status: str = "success",
    ) -> None:
        if not self.current_session:
            self.new_session()
        now = datetime.now(timezone.utc).isoformat()
        clean_args = sanitize_for_storage(arguments)
        clean_output = sanitize_for_storage(output)
        if isinstance(clean_output, str) and len(clean_output) > 500:
            clean_output = clean_output[:497] + "..."

        self.current_session.tool_calls.append({
            "tool_name": tool_name,
            "arguments": clean_args,
            "output_summary": clean_output,
            "status": status,
            "timestamp": now,
        })
        self.current_session.updated_at = now
        self.save()

    def record_approved_tool(
        self,
        name: str,
        version: str = "1.0.0",
        permissions: Optional[List[str]] = None,
        risk_level: str = "low",
    ) -> None:
        if not self.current_session:
            self.new_session()
        now = datetime.now(timezone.utc).isoformat()
        self.current_session.tool_metadata.append({
            "name": name,
            "version": version,
            "status": "approved",
            "permissions": permissions or [],
            "risk_level": risk_level,
            "timestamp": now,
        })
        self.current_session.updated_at = now
        self.save()

    def record_rejected_attempt(
        self,
        tool_name: str,
        attempt: int,
        reason: str,
        error_type: Optional[str] = None,
    ) -> None:
        """Store minimal debugging record for rejected tool attempts, zero secrets."""
        if not self.current_session:
            self.new_session()
        now = datetime.now(timezone.utc).isoformat()
        clean_reason = sanitize_for_storage(reason)
        self.current_session.debug_rejected_attempts.append({
            "tool_name": tool_name,
            "attempt": attempt,
            "reason": clean_reason,
            "error_type": error_type or "Rejected",
            "timestamp": now,
        })
        self.current_session.updated_at = now
        self.save()

    def save(self) -> Path:
        """Persist current active session to a local inspectable JSON file."""
        if not self.current_session:
            self.new_session()
        session_file = self.storage_dir / f"{self.current_session.session_id}.json"
        data = self.current_session.to_dict()
        sanitized_data = sanitize_for_storage(data)
        session_file.write_text(json.dumps(sanitized_data, indent=2) + "\n", encoding="utf-8")
        return session_file

    def load_session(self, session_id: str) -> Optional[SessionData]:
        """Load previous session when explicitly requested, with corruption recovery."""
        session_file = self.storage_dir / f"{session_id}.json"
        if not session_file.exists():
            return None

        try:
            content = session_file.read_text(encoding="utf-8")
            raw = json.loads(content)
            if not isinstance(raw, dict) or "session_id" not in raw:
                raise ValueError("Invalid session schema")
            self.current_session = SessionData.from_dict(raw)
            return self.current_session
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError, OSError) as exc:
            # Corrupted storage recovery: safely preserve corrupt file and recover
            backup_path = self.storage_dir / f"{session_id}.corrupted"
            try:
                session_file.rename(backup_path)
            except OSError:
                pass

            now = datetime.now(timezone.utc).isoformat()
            self.current_session = SessionData(
                session_id=session_id,
                created_at=now,
                updated_at=now,
                messages=[{"role": "system", "content": f"Session recovered from corrupted storage: {exc}"}],
            )
            self.save()
            return self.current_session

    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all saved sessions with summary statistics."""
        summaries = []
        for file in sorted(self.storage_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                content = file.read_text(encoding="utf-8")
                raw = json.loads(content)
                if isinstance(raw, dict):
                    summaries.append({
                        "session_id": raw.get("session_id", file.stem),
                        "created_at": raw.get("created_at", "unknown"),
                        "updated_at": raw.get("updated_at", "unknown"),
                        "messages_count": len(raw.get("messages", [])),
                        "tool_calls_count": len(raw.get("tool_calls", [])),
                        "active": raw.get("session_id") == self.active_session_id,
                        "file_path": str(file),
                    })
            except (json.JSONDecodeError, OSError):
                summaries.append({
                    "session_id": file.stem,
                    "created_at": "corrupted",
                    "updated_at": "corrupted",
                    "messages_count": 0,
                    "tool_calls_count": 0,
                    "active": False,
                    "corrupted": True,
                    "file_path": str(file),
                })
        return summaries

    def clear(self) -> None:
        """Clear the current active session in memory and on disk."""
        if self.current_session:
            session_file = self.storage_dir / f"{self.current_session.session_id}.json"
            if session_file.exists():
                session_file.unlink()
        self.new_session()

    def clear_all(self) -> int:
        """Delete all saved sessions from disk and start fresh."""
        count = 0
        for file in self.storage_dir.glob("*.json"):
            try:
                file.unlink()
                count += 1
            except OSError:
                pass
        for file in self.storage_dir.glob("*.corrupted"):
            try:
                file.unlink()
            except OSError:
                pass
        self.new_session()
        return count

    def get_messages(self) -> List[Dict[str, Any]]:
        return list(self.current_session.messages) if self.current_session else []

    def get_tool_calls(self) -> List[Dict[str, Any]]:
        return list(self.current_session.tool_calls) if self.current_session else []

    def _init_or_load_default(self) -> None:
        sessions = sorted(self.storage_dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        if sessions:
            try:
                raw = json.loads(sessions[0].read_text(encoding="utf-8"))
                if isinstance(raw, dict) and "session_id" in raw:
                    self.current_session = SessionData.from_dict(raw)
                    return
            except (json.JSONDecodeError, OSError):
                pass
        self.new_session()
