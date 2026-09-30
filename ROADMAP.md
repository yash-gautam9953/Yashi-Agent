# Personal Agent

## Current architecture

- `main.py`: Azure Responses API session and bounded dynamic-tool loop.
- `tools/custom_tool_manager.py`: validates, tests, approves, saves, and hot-registers tools.
- `tools.json`: contains only `create_and_register_tool`.
- `custom_tools/`: approved generated tools.
- `ui/`: dependency-free interactive console UI.
- `tests/test_custom_tools.py`: standard-library tests without an LLM/API call.

## Current behavior

The model starts with exactly one tool: `create_and_register_tool`.
For a missing capability it must generate a narrowly scoped tool, provide test
code, pass validation, receive user approval, register the tool, and use it in
the current session.

Browser, desktop, clipboard, cloud, Docker, MCP, and memory capabilities are
not currently implemented.
