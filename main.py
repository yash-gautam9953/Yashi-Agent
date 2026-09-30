import json
import os
import sys
from functools import partial
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from tools.custom_tool_manager import (
    create_and_register_tool,
    load_custom_tools,
    validate_tool_name,
)
from ui.console import console


load_dotenv()

WORKSPACE = Path(__file__).parent.resolve()
MAX_TOOL_ROUNDS = 12

endpoint = os.getenv(
    "AZURE_OPENAI_ENDPOINT",
    "https://samjho-ai.services.ai.azure.com/openai/v1",
)
deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-5.6-terra")
api_key = os.getenv("AZURE_OPENAI_API_KEY")
if not api_key:
    raise RuntimeError("AZURE_OPENAI_API_KEY is not set in .env")

client = OpenAI(base_url=endpoint, api_key=api_key)

tools = json.loads((WORKSPACE / "tools.json").read_text(encoding="utf-8"))
tool_functions = {}


def approve(message):
    return console.approval(message)


def dynamic_register(name, schema, function):
    tool_functions[name] = function
    tools[:] = [tool for tool in tools if tool.get("name") != name]
    tools.append(schema)


def register_custom_tool(name, schema, function):
    validate_tool_name(name, {"create_and_register_tool"})
    dynamic_register(name, schema, function)


def show_tools():
    console.tools_panel(tools)


tool_functions["create_and_register_tool"] = partial(
    create_and_register_tool,
    WORKSPACE,
    approve,
    register_custom_tool,
    {"create_and_register_tool"},
)

load_custom_tools(WORKSPACE, tool_functions, tools)

AGENT_INSTRUCTIONS = (
    "You are a dynamic personal assistant. The only initially available tool "
    "is create_and_register_tool. If the user's request needs any other "
    "capability, create a narrowly scoped Python tool with a JSON schema and "
    "test_code. Ask for approval through the tool. After it returns registered, "
    "call the new tool in the next step to complete the user's request. "
    "For harmless underspecified requests, make a sensible minimal assumption "
    "instead of asking a clarification question: for 'create a Python file "
    "with some Python code', use example.py with a small runnable example and "
    "tell the user what assumption you made. "
    "Never pretend a task is complete before observing the tool result. "
    "Never create credential theft, secret exfiltration, security bypass, or "
    "destructive operating-system tools."
)


def ask_llm(user_input, previous_response_id=None):
    request = {
        "model": deployment_name,
        "instructions": AGENT_INSTRUCTIONS,
        "input": user_input,
        "tools": tools,
    }
    if previous_response_id:
        request["previous_response_id"] = previous_response_id
    console.thinking_start()
    try:
        return client.responses.create(**request)
    finally:
        console.thinking_stop()


def run_task(user_input, previous_response_id=None):
    response = ask_llm(user_input, previous_response_id)

    for _ in range(MAX_TOOL_ROUNDS):
        outputs = []

        for item in response.output:
            if item.type != "function_call":
                continue

            arguments = json.loads(item.arguments)
            console.tool_start(item.name, arguments)

            try:
                function = tool_functions[item.name]
                result = function(**arguments)
            except Exception as error:
                result = f"Tool error: {error}"

            if isinstance(result, (dict, list)):
                result_for_model = json.dumps(result, ensure_ascii=True)
            else:
                result_for_model = str(result)

            console.tool_result(result_for_model)
            outputs.append({
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": result_for_model,
            })

        if not outputs:
            if response.output_text:
                console.assistant(response.output_text)
            return response.id

        console.thinking_start()
        try:
            response = client.responses.create(
                model=deployment_name,
                instructions=(
                    "Use the newly registered tool if it is available. "
                    "Then give a concise final answer based on the observed result."
                ),
                previous_response_id=response.id,
                input=outputs,
                tools=tools,
            )
        finally:
            console.thinking_stop()

    console.error("Maximum tool rounds reached.")
    return response.id


console.banner()
print(console.color("  Only create_and_register_tool is active initially.", "dim"))
print(console.color("  Type 'help' for usage or 'exit' to stop.", "dim"))

session_response_id = None
while True:
    try:
        user_input = console.prompt()
    except (EOFError, KeyboardInterrupt):
        console.session_ended()
        break

    if not user_input:
        continue
    if user_input.lower() in {"exit", "quit", "q"}:
        console.session_ended()
        break
    if user_input.lower() in {"/tools", "tools"}:
        show_tools()
        continue
    if user_input.lower() in {"/help", "help"}:
        console.help_panel()
        print("\n  Ask for any capability. The agent will propose, test, approve, and use a tool.")
        continue

    try:
        session_response_id = run_task(user_input, session_response_id)
    except Exception as error:
        console.error(str(error))
