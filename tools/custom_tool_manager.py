import ast
import hashlib
import importlib.util
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from security.inspector import SecurityInspector
from tools.sandbox import ToolSandbox

Approval = Callable[[str], bool]
RegisterCallback = Callable[[str, dict, Callable], None]

_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")


def validate_tool_name(name: str, core_tools: set[str] | None = None) -> None:
    if not name or not _TOOL_NAME.fullmatch(name):
        raise ValueError("Tool name must be lowercase snake_case (3-41 characters)")
    if core_tools and name in core_tools:
        raise ValueError(f"Tool name '{name}' conflicts with a core system tool")


def validate_tool_code(name: str, code: str) -> None:
    if not code or not code.strip():
        raise ValueError("Tool code cannot be empty")
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        raise ValueError(f"Syntax error in tool code: {error}") from error

    has_function = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
        for node in tree.body
    )
    if not has_function:
        raise ValueError(f"Code must define a function named '{name}' at module level")


def test_tool_code(code: str, test_code: str = "") -> tuple[bool, str]:
    """Execute tool tests inside the isolated ToolSandbox."""
    sandbox = ToolSandbox()
    result = sandbox.run_test(code, test_code)
    if not result["success"]:
        return False, result["error"] or result["stderr"]
    return True, result["stdout"]


def import_custom_tool(workspace: Path, name: str) -> Callable[..., Any]:
    tool_file = workspace / "custom_tools" / f"{name}.py"
    if not tool_file.exists():
        raise FileNotFoundError(f"Custom tool file not found: {tool_file}")

    module_name = f"custom_tools.{name}"
    spec = importlib.util.spec_from_file_location(module_name, tool_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load module spec for {tool_file}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    func = getattr(module, name, None)
    if not callable(func):
        raise AttributeError(
            f"Module {module_name} does not have a callable attribute '{name}'"
        )
    return func


def _load_custom_tools_registry(workspace: Path) -> dict:
    config_file = workspace / "config" / "custom_tools.json"
    if not config_file.exists():
        return {}
    try:
        data = json.loads(config_file.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _save_custom_tools_registry(workspace: Path, registry: dict) -> None:
    config_file = workspace / "config" / "custom_tools.json"
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(registry, indent=2) + "\n", encoding="utf-8")


def load_custom_tools(
    workspace: Path,
    tool_functions: dict[str, Callable],
    tools_list: list[dict],
) -> list[str]:
    registry = _load_custom_tools_registry(workspace)
    loaded_tools = []

    for name, item in registry.items():
        if not isinstance(item, dict):
            continue
        if item.get("enabled") is False:
            continue
        schema = item.get("schema")
        if not schema or not isinstance(schema, dict):
            continue

        try:
            func = import_custom_tool(workspace, name)
            tool_functions[name] = func

            # Update or append schema in tools_list
            for index, existing_tool in enumerate(tools_list):
                if existing_tool.get("name") == name:
                    tools_list[index] = schema
                    break
            else:
                tools_list.append(schema)

            loaded_tools.append(name)
        except Exception as error:
            print(f"Warning: Failed to load custom tool '{name}': {error}")

    return loaded_tools


def reload_tools(
    workspace: Path,
    tool_functions: dict[str, Callable],
    tools_list: list[dict],
) -> str:
    loaded = load_custom_tools(workspace, tool_functions, tools_list)
    return json.dumps({
        "ok": True,
        "reloaded_tools": loaded,
        "count": len(loaded),
        "message": f"Successfully reloaded {len(loaded)} custom tools.",
    })


_default_correction_manager = None


def get_default_correction_manager():
    global _default_correction_manager
    if _default_correction_manager is None:
        from agent.correction import SelfCorrectionManager
        _default_correction_manager = SelfCorrectionManager()
    return _default_correction_manager


def create_and_register_tool(
    workspace: Path,
    approve: Approval,
    register_callback: RegisterCallback,
    core_tools: set[str],
    name: str,
    description: str,
    parameters: dict | str,
    code: str,
    test_code: str = "",
    correction_manager: Optional[Any] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> str:
    from agent.correction import AttemptRecord, analyze_failure, sanitize_error
    if correction_manager is None:
        correction_manager = get_default_correction_manager()

    validate_tool_name(name, core_tools)
    if not description or not description.strip():
        raise ValueError("Description cannot be empty")

    if isinstance(parameters, str):
        try:
            parameters = json.loads(parameters)
        except json.JSONDecodeError as error:
            raise ValueError(f"Parameters must be valid JSON: {error}") from error

    if not isinstance(parameters, dict):
        raise ValueError("Parameters must be a JSON object schema")

    parameters.setdefault("type", "object")
    parameters.setdefault("properties", {})

    # Guard against infinite retry loops
    if correction_manager.has_exceeded_attempts(name):
        last_history = correction_manager.get_history(name)
        last_err = last_history[-1].error_message if last_history else "Max attempts reached"
        payload = correction_manager.create_failure_payload(
            name,
            last_err,
            correction_manager.max_attempts,
        )
        return json.dumps(payload)

    attempt_number = correction_manager.get_attempt_count(name) + 1
    code_hash = hashlib.sha256(code.strip().encode("utf-8")).hexdigest()

    # 1. Duplicate detection against existing tools
    if callable(on_progress):
        on_progress("Checking available tools")

    from tools.registry import ToolManifest, ToolRegistry

    reg_data = _load_custom_tools_registry(workspace)
    temp_registry = ToolRegistry()
    for reg_name, item in reg_data.items():
        if isinstance(item, dict):
            temp_registry._manifests[reg_name] = ToolManifest.from_dict(item)

    dup = temp_registry.find_duplicate(name, description)
    if dup and dup.get("tool") != name:
        return json.dumps({
            "ok": False,
            "status": "duplicate_found",
            "name": name,
            "existing_tool": dup["tool"],
            "message": (
                f"A suitable existing tool '{dup['tool']}' already exists: {dup['reason']} "
                f"Reusing existing tool '{dup['tool']}' instead of generating a duplicate."
            ),
            "suggestion": f"Call existing tool '{dup['tool']}' directly.",
            "details": dup,
        })

    # 2. Creating tool & Static AST Security Inspection (NEVER BYPASSED ON RETRIES)
    if callable(on_progress):
        on_progress("Creating tool")

    if callable(on_progress):
        on_progress("Security inspection")

    inspector = SecurityInspector()
    report = inspector.analyze_tool(
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
            error_message=f"Security violation detected: {'; '.join(report.violations)}",
            analysis="Code attempted blocked modules or dangerous capabilities.",
        )
        correction_manager.record_attempt(record)

        return json.dumps({
            "ok": False,
            "status": "security_violation",
            "name": name,
            "attempt": attempt_number,
            "max_attempts": correction_manager.max_attempts,
            "error": f"Security violation detected: {'; '.join(report.violations)}",
            "violations": report.violations,
        })

    validate_tool_code(name, code)

    # 3. Interactive user authorization (If code materially changes, require approval again)
    reapproval_required = correction_manager.is_reapproval_required(name, code)
    if reapproval_required:
        if callable(on_progress):
            on_progress("Waiting for approval")

        if not approve(report):
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
                error_message="User denied tool creation",
            )
            correction_manager.record_attempt(record)
            return json.dumps({
                "ok": False,
                "status": "denied",
                "name": name,
                "attempt": attempt_number,
                "message": "User denied tool creation",
            })
        correction_manager.record_approved_code(name, code)

    # 4. Isolated Sandbox Test Execution (Only runs AFTER approval and inside sandbox)
    if callable(on_progress):
        on_progress("Testing")

    sandbox = ToolSandbox(inspector=inspector)
    test_result = sandbox.run_test(code, test_code)
    duration = test_result.get("duration", 0.0)

    if not test_result["success"]:
        raw_error = test_result.get("error") or test_result.get("stderr") or "Tool test failed"
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
        correction_manager.record_attempt(record)

        payload = correction_manager.create_failure_payload(name, raw_error, attempt_number)
        return json.dumps(payload)

    # 5. Success! Record attempt, persist to disk, and update registry manifest
    if callable(on_progress):
        on_progress("Registering")

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
    correction_manager.record_attempt(record)

    # 5. Save to disk and update registry manifest
    custom_tools_dir = workspace / "custom_tools"
    custom_tools_dir.mkdir(parents=True, exist_ok=True)
    init_py = custom_tools_dir / "__init__.py"
    if not init_py.exists():
        init_py.touch()

    tool_file = custom_tools_dir / f"{name}.py"
    tool_file.write_text(code, encoding="utf-8")

    schema = {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
    }

    now = datetime.now(timezone.utc).isoformat()
    created_at = now
    version = "1.0.0"
    history = []
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()[:16]

    if name in reg_data and isinstance(reg_data[name], dict):
        existing = reg_data[name]
        created_at = existing.get("created_at", now)
        old_version = existing.get("version", "1.0.0")
        history = list(existing.get("history", []))
        history.append({
            "version": old_version,
            "updated_at": existing.get("updated_at", now),
            "checksum": existing.get("checksum", ""),
            "description": existing.get("description", description),
        })
        parts = old_version.split(".")
        if len(parts) == 3 and parts[1].isdigit():
            version = f"{parts[0]}.{int(parts[1]) + 1}.0"
        else:
            version = f"{old_version}.1"

    manifest_dict = {
        "name": name,
        "version": version,
        "description": description,
        "file": f"{name}.py",
        "function_name": name,
        "author": "agent",
        "dependencies": report.detected_imports if report else [],
        "permissions": [k for k, v in report.permissions.items() if "[+]" in v] if report else [],
        "risk_level": report.risk_level.lower() if report else "low",
        "enabled": True,
        "status": "approved",
        "created_at": created_at,
        "updated_at": now,
        "checksum": code_hash,
        "history": history,
        "schema": schema,
    }
    reg_data[name] = manifest_dict
    _save_custom_tools_registry(workspace, reg_data)

    # Dynamic import and hot-registration
    func = import_custom_tool(workspace, name)
    register_callback(name, schema, func)

    return json.dumps({
        "ok": True,
        "status": "registered",
        "name": name,
        "attempts_used": attempt_number,
        "message": (
            f"Tool '{name}' created, verified, and hot-registered successfully on attempt {attempt_number}! "
            f"You can now call '{name}' in your next step."
        ),
    })
