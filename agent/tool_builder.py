from functools import partial
from pathlib import Path
from typing import Any, Callable, Optional, Set

from tools.custom_tool_manager import create_and_register_tool


def create_tool_builder_handler(
    workspace: Path,
    approve_callback: Callable[[str], bool],
    register_callback: Callable[[str, dict, Callable], None],
    core_tools: Optional[Set[str]] = None,
    correction_manager: Optional[Any] = None,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Callable:
    """Create the callable handler for the create_and_register_tool meta-tool."""
    if core_tools is None:
        core_tools = {"create_and_register_tool"}
    return partial(
        create_and_register_tool,
        workspace,
        approve_callback,
        register_callback,
        core_tools,
        correction_manager=correction_manager,
        on_progress=on_progress,
    )
