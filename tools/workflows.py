import json
import re
from pathlib import Path
from typing import Callable, Mapping


Approval = Callable[[str], bool]
ToolFunction = Callable[..., str]
_NAME = re.compile(r"^[a-z][a-z0-9_]{2,40}$")
MAX_STEPS = 10


def _workflow_path(workspace: Path) -> Path:
    return workspace / "config" / "workflows.json"


def _load(workspace: Path) -> dict:
    path = _workflow_path(workspace)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Workflow registry must be a JSON object")
    return data


def create_workflow(
    workspace: Path,
    approve: Approval,
    available_tools: set[str],
    name: str,
    description: str,
    steps: list[dict],
) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError("Workflow name must be lowercase snake_case")
    if not description.strip() or len(description) > 1000:
        raise ValueError("Workflow description must be between 1 and 1000 characters")
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
        raise ValueError(f"Workflow must contain 1 to {MAX_STEPS} steps")

    normalized_steps = []
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each workflow step must be an object")
        tool_name = step.get("tool")
        arguments = step.get("arguments", {})
        if tool_name not in available_tools:
            raise ValueError(f"Workflow references unavailable tool: {tool_name}")
        if not isinstance(arguments, dict):
            raise ValueError("Workflow step arguments must be an object")
        normalized_steps.append({"tool": tool_name, "arguments": arguments})

    if not approve(
        f"Create workflow '{name}' with {len(normalized_steps)} steps?\n"
        f"Reason: {description}\n"
        "It will use existing permission-checked tools.\n"
        "Allow?"
    ):
        return json.dumps({"ok": False, "status": "denied", "name": name})

    workflows = _load(workspace)
    workflows[name] = {
        "description": description,
        "steps": normalized_steps,
    }
    path = _workflow_path(workspace)
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(workflows, indent=2) + "\n", encoding="utf-8")
    return json.dumps({
        "ok": True,
        "status": "active",
        "name": name,
        "message": "Workflow created and available through run_workflow.",
    })


def run_workflow(
    workspace: Path,
    tool_functions: Mapping[str, ToolFunction],
    name: str,
) -> str:
    workflow = _load(workspace).get(name)
    if not isinstance(workflow, dict):
        raise ValueError(f"Workflow not found: {name}")

    results = []
    for step in workflow["steps"]:
        tool_name = step["tool"]
        if tool_name not in tool_functions:
            raise ValueError(f"Workflow tool is no longer available: {tool_name}")
        result = tool_functions[tool_name](**step["arguments"])
        results.append({"tool": tool_name, "result": result})

    return json.dumps({"ok": True, "workflow": name, "steps": results})
