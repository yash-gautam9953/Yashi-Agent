"""Controlled self-correction loop, attempt tracking, and failure recovery for generated tools."""

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from security.inspector import SecurityInspector
from security.policy import SENSITIVE_ENV_KEYS
from tools.custom_tool_manager import import_custom_tool, validate_tool_code
from tools.registry import ToolManifest, ToolRegistry
from tools.sandbox import ToolSandbox

MAX_CORRECTION_ATTEMPTS: int = 3


@dataclass
class AttemptRecord:
    """Stores in-memory debugging information for an individual tool generation attempt."""

    attempt_number: int
    tool_name: str
    code: str
    test_code: str
    code_hash: str
    status: str  # "registered", "test_failed", "security_violation", "denied", "max_attempts_exceeded"
    approved: bool = False
    security_safe: bool = True
    security_violations: List[str] = field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    analysis: Optional[str] = None
    duration: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def sanitize_error(error_str: str, extra_secrets: Optional[List[str]] = None) -> str:
    """Sanitize error messages and tracebacks to ensure no secrets or API keys are leaked."""
    if not error_str:
        return ""
    sanitized = str(error_str)

    # 1. Redact known sensitive environment variable values
    secrets_to_redact = set(extra_secrets or [])
    for key in SENSITIVE_ENV_KEYS:
        val = os.environ.get(key)
        if val and len(val.strip()) > 3:
            secrets_to_redact.add(val.strip())

    for val in os.environ.values():
        # Any value that looks like an API key or high-entropy secret token (>= 20 chars with alphanumeric)
        if len(val) >= 20 and any(c.isdigit() for c in val) and any(c.isalpha() for c in val):
            secrets_to_redact.add(val.strip())

    for s in secrets_to_redact:
        if s and len(s) > 3:
            sanitized = sanitized.replace(s, "[REDACTED_SECRET]")

    # 2. Redact pattern matches (Bearer tokens, api_key=..., sk-..., password=...)
    patterns = [
        (r"(Bearer\s+)[A-Za-z0-9\-_\.]+", r"\1[REDACTED_TOKEN]"),
        (r"(api[_-]?key[\s:=]+['\"]?)[A-Za-z0-9\-_\.]+(['\"]?)", r"\1[REDACTED_KEY]\2"),
        (r"(password[\s:=]+['\"]?)[^\s'\"]+(['\"]?)", r"\1[REDACTED_PASSWORD]\2"),
        (r"sk-[A-Za-z0-9]{20,}", "[REDACTED_KEY]"),
    ]
    for pattern, replacement in patterns:
        sanitized = re.sub(pattern, replacement, sanitized, flags=re.IGNORECASE)

    return sanitized


def parse_error_type(error_str: str) -> Tuple[str, str]:
    """Extract specific Python exception type name and a plain-English explanation."""
    known_exceptions = [
        ("FileNotFoundError", "The tool expected a file or directory path that does not exist on disk."),
        ("ModuleNotFoundError", "The tool attempted to import an unavailable or missing third-party module."),
        ("ImportError", "The tool attempted to import a symbol or module that could not be loaded."),
        ("AssertionError", "The tool test assertions failed because the function output did not match expected results."),
        ("KeyError", "The tool tried to access a dictionary key that was not present in the input or dataset."),
        ("TypeError", "The tool encountered a type mismatch in arguments, return values, or operations."),
        ("ValueError", "The tool received an argument with an invalid or unexpected value."),
        ("AttributeError", "The tool called a method or attribute that does not exist on the object."),
        ("IndexError", "The tool accessed a list or sequence index that is out of bounds."),
        ("ZeroDivisionError", "The tool attempted division by zero."),
        ("TimeoutError", "The tool test execution exceeded the sandbox time limit."),
        ("SyntaxError", "The tool code contains invalid Python syntax."),
    ]
    for exc_name, explanation in known_exceptions:
        if exc_name in error_str:
            return exc_name, explanation

    if "timed out" in error_str.lower():
        return "TimeoutError", "The tool test execution exceeded the sandbox time limit."

    return "ExecutionError", "The tool raised an unexpected error during execution."


def analyze_failure(error_str: str) -> Dict[str, str]:
    """Produce structured diagnostic analysis and repair guidance for the failure."""
    sanitized = sanitize_error(error_str)
    exc_type, diagnosis = parse_error_type(sanitized)

    guidance_map = {
        "FileNotFoundError": "Ensure the tool creates necessary parent directories with exist_ok=True, checks os.path.exists/pathlib.Path.exists, or handles missing paths gracefully.",
        "ModuleNotFoundError": "Avoid importing non-standard packages; stick strictly to standard library modules (json, math, re, pathlib, etc.).",
        "ImportError": "Verify import names and utilize standard library alternatives.",
        "AssertionError": "Compare the function output format with the test assertions to ensure matching data types and structure.",
        "KeyError": "Use dict.get(key, default) or verify that input dictionaries contain all required keys before access.",
        "TypeError": "Verify argument types, type conversions (e.g. str vs int), or function parameter signatures.",
        "ValueError": "Validate input parameter constraints and handle edge cases gracefully.",
        "AttributeError": "Verify object types and ensure called attributes or methods are valid.",
        "IndexError": "Check list length before indexing or use slicing.",
        "ZeroDivisionError": "Add a guard check before dividing by variable numbers.",
        "TimeoutError": "Optimize algorithms or reduce workload to ensure completion within timeout limit.",
        "SyntaxError": "Ensure valid Python syntax, matching parentheses, and proper indentation.",
    }
    guidance = guidance_map.get(
        exc_type,
        "Review the stack trace, fix the issue in the code, and ensure all test assertions pass."
    )

    yashi_explanation = f"I found the problem. {diagnosis} I can revise the tool."

    return {
        "error_type": exc_type,
        "diagnosis": diagnosis,
        "guidance": guidance,
        "yashi_explanation": yashi_explanation,
        "sanitized_error": sanitized,
    }


class SelfCorrectionManager:
    """Tracks attempts, in-memory debugging history, and enforces retry boundaries."""

    def __init__(self, max_attempts: int = MAX_CORRECTION_ATTEMPTS):
        self.max_attempts = max_attempts
        self._history: Dict[str, List[AttemptRecord]] = {}
        self._last_approved_hashes: Dict[str, str] = {}

    def get_attempt_count(self, tool_name: str) -> int:
        return len(self._history.get(tool_name, []))

    def get_history(self, tool_name: str) -> List[AttemptRecord]:
        return list(self._history.get(tool_name, []))

    def has_exceeded_attempts(self, tool_name: str) -> bool:
        return len(self._history.get(tool_name, [])) >= self.max_attempts

    def reset(self, tool_name: Optional[str] = None) -> None:
        if tool_name:
            self._history.pop(tool_name, None)
            self._last_approved_hashes.pop(tool_name, None)
        else:
            self._history.clear()
            self._last_approved_hashes.clear()

    def record_approved_code(self, tool_name: str, code: str) -> None:
        self._last_approved_hashes[tool_name] = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

    def is_reapproval_required(self, tool_name: str, code: str) -> bool:
        current_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()
        last_hash = self._last_approved_hashes.get(tool_name)
        if last_hash is None:
            return True
        return current_hash != last_hash

    def record_attempt(self, record: AttemptRecord) -> None:
        if record.tool_name not in self._history:
            self._history[record.tool_name] = []
        self._history[record.tool_name].append(record)

    def create_failure_payload(
        self,
        tool_name: str,
        error: str,
        attempt: int,
    ) -> Dict[str, Any]:
        analysis = analyze_failure(error)
        attempts_remaining = max(0, self.max_attempts - attempt)
        exceeded = attempt >= self.max_attempts

        status = "max_attempts_exceeded" if exceeded else "test_failed"

        history_summary = [
            {
                "attempt": a.attempt_number,
                "status": a.status,
                "error_type": a.error_type,
                "approved": a.approved,
            }
            for a in self._history.get(tool_name, [])
        ]

        payload = {
            "ok": False,
            "status": status,
            "name": tool_name,
            "attempt": attempt,
            "max_attempts": self.max_attempts,
            "attempts_remaining": attempts_remaining,
            "error_type": analysis["error_type"],
            "error": analysis["sanitized_error"],
            "diagnosis": analysis["diagnosis"],
            "yashi_explanation": analysis["yashi_explanation"],
            "guidance": analysis["guidance"],
            "history_summary": history_summary,
        }

        if exceeded:
            payload["message"] = (
                f"Maximum retry attempts ({self.max_attempts}) reached for tool '{tool_name}'. "
                f"Self-correction stopped to prevent an infinite loop. "
                f"Final failure: {analysis['diagnosis']}"
            )
        else:
            payload["message"] = (
                f"Tool test failed on attempt {attempt}/{self.max_attempts}. "
                f"{analysis['yashi_explanation']} "
                f"{analysis['guidance']}"
            )

        return payload


class SelfCorrectionLoop:
    """Coordinates the full tool lifecycle self-correction loop up to MAX_CORRECTION_ATTEMPTS."""

    def __init__(
        self,
        workspace: Path,
        registry: ToolRegistry,
        inspector: Optional[SecurityInspector] = None,
        sandbox: Optional[ToolSandbox] = None,
        manager: Optional[SelfCorrectionManager] = None,
        max_attempts: int = MAX_CORRECTION_ATTEMPTS,
    ):
        self.workspace = workspace
        self.registry = registry
        self.inspector = inspector or SecurityInspector()
        self.sandbox = sandbox or ToolSandbox(inspector=self.inspector)
        self.manager = manager or SelfCorrectionManager(max_attempts=max_attempts)
        self.max_attempts = max_attempts

    def run(
        self,
        name: str,
        description: str,
        parameters: dict,
        code_generator: Callable[[int, Optional[Dict[str, Any]]], Tuple[str, str]],
        approve_callback: Callable[[Any], bool],
        register_callback: Optional[Callable[[str, dict, Callable], None]] = None,
    ) -> Dict[str, Any]:
        """Executes the controlled self-correction flow.

        Flow:
            1. Duplicate check against existing tools
            2. Loop (up to max_attempts):
               a. Generate tool code & test
               b. Static AST security inspection (NEVER bypassed)
               c. User authorization (re-prompt if code changed)
               d. Sandbox test execution
               e. If failure: analyze failure, sanitize error, record attempt, retry
               f. If success: persist file, register tool, return success
            3. If still failing after max_attempts: stop and explain failure (no infinite loop)
        """
        if register_callback is None:
            register_callback = self.registry.register_custom_tool

        # Duplicate check against active tools
        dup = self.registry.find_duplicate(name, description)
        if dup and dup.get("tool") != name:
            return {
                "ok": False,
                "status": "duplicate_found",
                "name": name,
                "existing_tool": dup["tool"],
                "message": f"A suitable tool '{dup['tool']}' already exists: {dup['reason']}",
                "suggestion": f"Call existing tool '{dup['tool']}' directly.",
                "details": dup,
            }

        last_error_info: Optional[Dict[str, Any]] = None

        while not self.manager.has_exceeded_attempts(name):
            attempt_number = self.manager.get_attempt_count(name) + 1

            # a. Generate tool code & test code
            code, test_code = code_generator(attempt_number, last_error_info)
            code_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

            # b. Static AST Security Inspection (NEVER BYPASSED)
            report = self.inspector.analyze_tool(
                name=name,
                description=description,
                code=code,
                test_code=test_code,
                target_file=f"custom_tools/{name}.py",
            )

            if not report.is_safe:
                record = AttemptRecord(
                    attempt_number=attempt_number,
                    tool_name=name,
                    code=code,
                    test_code=test_code,
                    code_hash=code_hash,
                    status="security_violation",
                    approved=False,
                    security_safe=False,
                    security_violations=report.violations,
                    error_type="SecurityViolation",
                    error_message=f"Security violation: {'; '.join(report.violations)}",
                    analysis="Code attempted blocked modules or dangerous capabilities.",
                )
                self.manager.record_attempt(record)

                if attempt_number >= self.max_attempts:
                    return {
                        "ok": False,
                        "status": "security_violation",
                        "name": name,
                        "attempt": attempt_number,
                        "max_attempts": self.max_attempts,
                        "error": f"Security violation detected: {'; '.join(report.violations)}",
                        "violations": report.violations,
                        "message": "Maximum retry attempts reached with security violation. Self-correction stopped.",
                    }

                last_error_info = {
                    "error_type": "SecurityViolation",
                    "error": f"Security violation detected: {'; '.join(report.violations)}",
                    "violations": report.violations,
                }
                continue

            # c. User Authorization (Never silently change approved code)
            reapproval_needed = self.manager.is_reapproval_required(name, code)
            if reapproval_needed:
                approved = approve_callback(report)
                if not approved:
                    record = AttemptRecord(
                        attempt_number=attempt_number,
                        tool_name=name,
                        code=code,
                        test_code=test_code,
                        code_hash=code_hash,
                        status="denied",
                        approved=False,
                        security_safe=True,
                        error_type="UserDenied",
                        error_message="User denied tool creation or revision.",
                    )
                    self.manager.record_attempt(record)
                    return {
                        "ok": False,
                        "status": "denied",
                        "name": name,
                        "attempt": attempt_number,
                        "message": "User denied tool creation or revision.",
                    }
                self.manager.record_approved_code(name, code)

            # d. Sandbox Test Execution (Only runs after approval and static check)
            test_result = self.sandbox.run_test(code, test_code)
            duration = test_result.get("duration", 0.0)

            if not test_result["success"]:
                raw_error = test_result.get("error") or test_result.get("stderr") or "Test failed"
                sanitized_error = sanitize_error(raw_error)
                analysis = analyze_failure(sanitized_error)

                record = AttemptRecord(
                    attempt_number=attempt_number,
                    tool_name=name,
                    code=code,
                    test_code=test_code,
                    code_hash=code_hash,
                    status="test_failed",
                    approved=True,
                    security_safe=True,
                    error_type=analysis["error_type"],
                    error_message=sanitized_error,
                    analysis=analysis["diagnosis"],
                    duration=duration,
                )
                self.manager.record_attempt(record)

                last_error_info = self.manager.create_failure_payload(name, raw_error, attempt_number)

                if attempt_number >= self.max_attempts:
                    return last_error_info

                continue

            # e. Success! Persist to disk and register tool
            record = AttemptRecord(
                attempt_number=attempt_number,
                tool_name=name,
                code=code,
                test_code=test_code,
                code_hash=code_hash,
                status="registered",
                approved=True,
                security_safe=True,
                duration=duration,
            )
            self.manager.record_attempt(record)

            custom_tools_dir = self.workspace / "custom_tools"
            custom_tools_dir.mkdir(parents=True, exist_ok=True)
            tool_file = custom_tools_dir / f"{name}.py"
            tool_file.write_text(code, encoding="utf-8")

            schema = {
                "type": "function",
                "name": name,
                "description": description,
                "parameters": parameters,
            }
            manifest = ToolManifest(
                name=name,
                description=description,
                schema=schema,
                function_name=name,
                file=f"{name}.py",
                version="1.0.0",
                author="agent",
                dependencies=report.detected_imports,
                permissions=[k for k, v in report.permissions.items() if "[+]" in v],
                risk_level=report.risk_level.lower(),
                enabled=True,
                status="approved",
                checksum=hashlib.sha256(code.encode("utf-8")).hexdigest()[:16],
            )
            func = import_custom_tool(self.workspace, name)
            register_callback(name, schema, func, manifest=manifest)
            self.registry.save_manifests_to_disk(self.workspace)

            return {
                "ok": True,
                "status": "registered",
                "name": name,
                "attempts_used": attempt_number,
                "message": f"Tool '{name}' created and registered successfully on attempt {attempt_number}!",
            }

        # Terminal state: max attempts exceeded
        last_err = last_error_info.get("error", "Maximum attempts exceeded") if last_error_info else "Maximum attempts exceeded"
        return self.manager.create_failure_payload(name, last_err, self.max_attempts)
