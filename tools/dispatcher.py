import json
from typing import Any, Callable, Mapping, Optional

from security.policy import DEFAULT_RUNTIME_TIMEOUT_SECONDS
from tools.execution import execute_tool_safely
from tools.registry import ToolRegistry


class ToolDispatcher:
    """Dispatches tool calls and formats execution results."""

    def __init__(self, registry: ToolRegistry, timeout: float = DEFAULT_RUNTIME_TIMEOUT_SECONDS):
        self.registry = registry
        self.timeout = timeout

    def dispatch(self, name: str, arguments: Mapping[str, Any]) -> str:
        """Execute a tool by name with arguments, returning a serialized string result."""
        function = self.registry.get_function(name)
        if function is None:
            return f"Tool error: Tool '{name}' not found."

        try:
            if name == "create_and_register_tool":
                result = function(**arguments)
            else:
                result = execute_tool_safely(function, arguments, timeout=self.timeout)
        except Exception as error:
            result = f"Tool error: {error}"

        if isinstance(result, (dict, list)):
            return json.dumps(result, ensure_ascii=True)
        return str(result)
