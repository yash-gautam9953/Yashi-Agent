import concurrent.futures
from typing import Any, Callable, Mapping

from security.policy import DEFAULT_RUNTIME_TIMEOUT_SECONDS


def execute_tool_safely(
    func: Callable[..., Any],
    arguments: Mapping[str, Any],
    timeout: float = DEFAULT_RUNTIME_TIMEOUT_SECONDS,
) -> Any:
    """Execute a callable tool with runtime timeout enforcement."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(func, **arguments)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise TimeoutError(f"Tool execution timed out after {timeout} seconds")
