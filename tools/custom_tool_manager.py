import ast
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

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
    script = code + "\n\n"
    if test_code and test_code.strip():
        script += "# Test execution\n" + test_code + "\n"
    else:
        script += "# Basic compilation check\n"

    try:
        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if proc.returncode != 0:
            return False, proc.stderr.strip() or proc.stdout.strip()
        return True, proc.stdout.strip()
    except subprocess.TimeoutExpired:
        return False, "Tool test timed out after 10 seconds"
    except Exception as error:
        return False, str(error)


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
) -> str:
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

    validate_tool_code(name, code)

    # Isolated test verification before asking user approval
    test_passed, test_msg = test_tool_code(code, test_code)
    if not test_passed:
        return json.dumps({
            "ok": False,
            "status": "test_failed",
            "name": name,
            "error": f"Tool test verification failed:\n{test_msg}",
        })

    # Interactive approval
    preview = code if len(code) <= 800 else code[:800] + "\n... [truncated]"
    approval_prompt = (
        f"Create and activate custom tool '{name}'?\n"
        f"Description: {description}\n"
        f"Code preview:\n{preview}\n"
        "Allow dynamic registration and execution?"
    )
    if not approve(approval_prompt):
        return json.dumps({
            "ok": False,
            "status": "denied",
            "name": name,
            "message": "User denied tool creation",
        })

    # Save to disk
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

    registry = _load_custom_tools_registry(workspace)
    registry[name] = {
        "schema": schema,
        "file": f"{name}.py",
        "function_name": name,
    }
    _save_custom_tools_registry(workspace, registry)

    # Dynamic import and hot-registration
    func = import_custom_tool(workspace, name)
    register_callback(name, schema, func)

    return json.dumps({
        "ok": True,
        "status": "registered",
        "name": name,
        "message": (
            f"Tool '{name}' created, verified, and hot-registered successfully! "
            f"You can now call '{name}' in your next step."
        ),
    })
