import json
from typing import Any, Optional

from llm.base import BaseLLMClient
from tools.dispatcher import ToolDispatcher
from tools.registry import ToolRegistry

DEFAULT_AGENT_INSTRUCTIONS = (
    "You are a dynamic personal assistant. The only initially available tool "
    "is create_and_register_tool. If the user's request needs any other "
    "capability, create a narrowly scoped Python tool with a JSON schema and "
    "test_code. Ask for approval through the tool. After it returns registered, "
    "call the new tool in the next step to complete the user's request. "
    "If create_and_register_tool fails due to a test error, analyze the failure, "
    "explain the issue to the user ('I found the problem. ... I can revise the tool.'), "
    "and call create_and_register_tool with corrected code. You may retry up to 3 times. "
    "Never create an infinite retry loop. If 3 attempts fail, stop and explain the failure. "
    "For harmless underspecified requests, make a sensible minimal assumption "
    "instead of asking a clarification question: for 'create a Python file "
    "with some Python code', use example.py with a small runnable example and "
    "tell the user what assumption you made. "
    "Never pretend a task is complete before observing the tool result. "
    "Never create credential theft, secret exfiltration, security bypass, or "
    "destructive operating-system tools."
)


class AgentOrchestrator:
    """Coordinates conversation turns, LLM calls, and tool execution rounds."""

    def __init__(
        self,
        llm_client: BaseLLMClient,
        registry: ToolRegistry,
        dispatcher: Optional[ToolDispatcher] = None,
        console: Optional[Any] = None,
        max_tool_rounds: int = 12,
        instructions: str = DEFAULT_AGENT_INSTRUCTIONS,
        session_store: Optional[Any] = None,
    ):
        self.llm_client = llm_client
        self.registry = registry
        self.dispatcher = dispatcher or ToolDispatcher(registry)
        self.console = console
        self.max_tool_rounds = max_tool_rounds
        self.instructions = instructions
        self.session_store = session_store

    def _thinking_start(self) -> None:
        if self.console and hasattr(self.console, "thinking_start"):
            self.console.thinking_start()

    def _thinking_stop(self) -> None:
        if self.console and hasattr(self.console, "thinking_stop"):
            self.console.thinking_stop()

    def _call_llm(
        self,
        instructions: str,
        input_data: Any,
        tools: Optional[list] = None,
        previous_response_id: Optional[str] = None,
        on_text_delta: Optional[Any] = None,
    ) -> Any:
        if on_text_delta is not None:
            try:
                return self.llm_client.create_response(
                    instructions=instructions,
                    input_data=input_data,
                    tools=tools,
                    previous_response_id=previous_response_id,
                    on_text_delta=on_text_delta,
                )
            except TypeError:
                pass
        return self.llm_client.create_response(
            instructions=instructions,
            input_data=input_data,
            tools=tools,
            previous_response_id=previous_response_id,
        )

    def ask_llm(self, user_input: str, previous_response_id: Optional[str] = None) -> Any:
        self._thinking_start()
        try:
            return self._call_llm(
                instructions=self.instructions,
                input_data=user_input,
                tools=self.registry.schemas,
                previous_response_id=previous_response_id,
            )
        finally:
            self._thinking_stop()

    def run_task(self, user_input: str, previous_response_id: Optional[str] = None) -> Optional[str]:
        if self.session_store:
            self.session_store.add_message("user", user_input)

        if self.console and hasattr(self.console, "step"):
            self.console.step("Planning")

        try:
            try:
                response = self.ask_llm(user_input, previous_response_id)
            except Exception as api_err:
                self._thinking_stop()
                if self.console and hasattr(self.console, "api_error"):
                    self.console.api_error(api_err)
                elif self.console and hasattr(self.console, "error"):
                    self.console.error(f"API Error: {api_err}")
                return previous_response_id

            for _ in range(self.max_tool_rounds):
                outputs = []

                for item in response.output:
                    if item.type != "function_call":
                        continue

                    try:
                        arguments = json.loads(item.arguments)
                    except Exception:
                        arguments = {}

                    if item.name != "create_and_register_tool":
                        if self.console and hasattr(self.console, "step"):
                            self.console.step(f"Executing {item.name}")

                    if self.console and hasattr(self.console, "tool_start"):
                        self.console.tool_start(item.name, arguments)

                    result_for_model = self.dispatcher.dispatch(item.name, arguments)

                    if self.session_store:
                        self.session_store.record_tool_call(item.name, arguments, result_for_model)

                    if self.console and hasattr(self.console, "tool_result"):
                        self.console.tool_result(result_for_model)

                    outputs.append({
                        "type": "function_call_output",
                        "call_id": item.call_id,
                        "output": result_for_model,
                    })

                if not outputs:
                    if response.output_text:
                        if self.session_store:
                            self.session_store.add_message("assistant", response.output_text)
                            self.session_store.update_response_id(getattr(response, "id", None))
                        if self.console and hasattr(self.console, "assistant"):
                            self.console.assistant(response.output_text)
                    return getattr(response, "id", None)

                self._thinking_start()
                try:
                    response = self._call_llm(
                        instructions=(
                            "Use the newly registered tool if it is available. "
                            "Then give a concise final answer based on the observed result."
                        ),
                        input_data=outputs,
                        tools=self.registry.schemas,
                        previous_response_id=response.id,
                    )
                except Exception as api_err:
                    self._thinking_stop()
                    if self.console and hasattr(self.console, "api_error"):
                        self.console.api_error(api_err)
                    elif self.console and hasattr(self.console, "error"):
                        self.console.error(f"API Error: {api_err}")
                    return getattr(response, "id", None) if 'response' in locals() else previous_response_id
                finally:
                    self._thinking_stop()

            if self.console and hasattr(self.console, "error"):
                self.console.error("Maximum tool rounds reached.")
            return getattr(response, "id", None)

        except KeyboardInterrupt:
            self._thinking_stop()
            if self.console and hasattr(self.console, "interrupted"):
                self.console.interrupted()
            return previous_response_id
