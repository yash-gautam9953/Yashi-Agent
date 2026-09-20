import json
import re
import shlex
import subprocess
import sys
from functools import partial
from pathlib import Path
from openai import OpenAI
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from security.secret_redaction import redact_sensitive
from tools.filesystem import (
    create_directory,
    create_file,
    delete_file,
    edit_file,
    file_metadata,
    list_directory,
    read_file,
    rename_file,
    search_files,
    search_media,
)
from tools.computer_files import (
    list_drives,
    list_location,
    read_external_file,
)
from tools.git import (
    git_branch,
    git_commit,
    git_create_branch,
    git_diff,
    git_log,
    git_push,
    git_pull,
    git_checkout,
    git_status,
)
from tools.tool_builder import request_new_tool
from tools.workflows import create_workflow, run_workflow
from tools.custom_tool_manager import (
    create_and_register_tool,
    load_custom_tools,
    reload_tools,
)
from ui.console import console


# -------------------------
# AZURE CONNECTION
# -------------------------

endpoint = "https://samjho-ai.services.ai.azure.com/openai/v1"
deployment_name = "gpt-5.6-terra"

token_provider = get_bearer_token_provider(
    DefaultAzureCredential(),
    "https://ai.azure.com/.default"
)

client = OpenAI(
    base_url=endpoint,
    api_key=token_provider
)


# -------------------------
# OUR TOOL
# -------------------------

WORKSPACE = Path(__file__).parent.resolve()
if str(WORKSPACE) not in sys.path:
    sys.path.insert(0, str(WORKSPACE))
MAX_TOOL_ROUNDS = 12
MAX_COMMAND_OUTPUT = 12000
SAFE_COMMANDS = {
    "python", "python.exe", "py", "py.exe", "pytest", "pytest.exe",
    "git", "git.exe", "npm", "npm.cmd", "node", "node.exe"
}
SAFE_GIT_COMMANDS = {"status", "diff", "log", "show"}
APPROVAL_COMMAND_MARKERS = {
    "-c", "install", "uninstall", "remove", "delete", "del", "rm",
    "reset", "checkout", "push", "commit"
}
COMMAND_META = re.compile(r"[&|<>;$`\n\r]")


def run_command(command):
    if COMMAND_META.search(command):
        raise PermissionError("Shell operators and multiple commands are blocked")

    command_parts = shlex.split(command, posix=False)
    if not command_parts:
        raise ValueError("Command cannot be empty")

    executable = Path(command_parts[0]).name.lower()
    command_requires_approval = (
        executable not in SAFE_COMMANDS
        or any(marker in command_parts[1:] for marker in APPROVAL_COMMAND_MARKERS)
    )

    if command_requires_approval:
        if not approve(f"Run command '{command}'?"):
            return json.dumps({"exit_code": -1, "stdout": "", "stderr": "Command denied by user"})

    if executable in {"git", "git.exe"}:
        if len(command_parts) < 2 or command_parts[1].lower() not in SAFE_GIT_COMMANDS:
            if not approve(f"Run potentially modifying Git command '{command}'?"):
                return json.dumps({"exit_code": -1, "stdout": "", "stderr": "Command denied by user"})

    completed = subprocess.run(
        command_parts,
        cwd=WORKSPACE,
        shell=False,
        capture_output=True,
        text=True,
        timeout=30
    )
    return json.dumps({
        "exit_code": completed.returncode,
        "stdout": redact_sensitive(completed.stdout)[:MAX_COMMAND_OUTPUT],
        "stderr": redact_sensitive(completed.stderr)[:MAX_COMMAND_OUTPUT]
    })


def approve(message):
    return console.approval(message)

# -------------------------
# TOOL DESCRIPTION
# -------------------------

tools = json.loads((WORKSPACE / "tools.json").read_text(encoding="utf-8"))
assistant_config = json.loads(
    (WORKSPACE / "config" / "assistant.json").read_text(encoding="utf-8")
)


base_tool_functions = {
    "read_file": partial(read_file, WORKSPACE, redact_sensitive),
    "search_files": partial(search_files, WORKSPACE),
    "list_directory": partial(list_directory, WORKSPACE),
    "file_metadata": partial(file_metadata, WORKSPACE),
    "search_media": partial(search_media, WORKSPACE, assistant_config),
    "list_drives": list_drives,
    "list_location": partial(list_location, WORKSPACE, approve),
    "read_external_file": partial(
        read_external_file, WORKSPACE, approve, redact_sensitive
    ),
    "create_file": partial(create_file, WORKSPACE, approve),
    "delete_file": partial(delete_file, WORKSPACE, approve),
    "edit_file": partial(edit_file, WORKSPACE, approve),
    "rename_file": partial(rename_file, WORKSPACE, approve),
    "create_directory": partial(create_directory, WORKSPACE),
    "git_status": partial(git_status, WORKSPACE, redact_sensitive),
    "git_diff": partial(git_diff, WORKSPACE, redact_sensitive),
    "git_log": partial(git_log, WORKSPACE, redact_sensitive),
    "git_branch": partial(git_branch, WORKSPACE, redact_sensitive),
    "git_create_branch": partial(
        git_create_branch, WORKSPACE, approve, redact_sensitive
    ),
    "git_commit": partial(git_commit, WORKSPACE, approve, redact_sensitive),
    "git_push": partial(git_push, WORKSPACE, approve, redact_sensitive),
    "git_pull": partial(git_pull, WORKSPACE, approve, redact_sensitive),
    "git_checkout": partial(git_checkout, WORKSPACE, approve, redact_sensitive),
    "request_new_tool": partial(request_new_tool, WORKSPACE, approve),
    "run_command": run_command
}

def dynamic_register(name, schema, func):
    tool_functions[name] = func
    for idx, existing_tool in enumerate(tools):
        if existing_tool.get("name") == name:
            tools[idx] = schema
            break
    else:
        tools.append(schema)


tool_functions = dict(base_tool_functions)
tool_functions.update({
    "create_workflow": partial(
        create_workflow,
        WORKSPACE,
        approve,
        set(base_tool_functions),
    ),
    "run_workflow": partial(
        run_workflow,
        WORKSPACE,
        base_tool_functions,
    ),
    "create_and_register_tool": partial(
        create_and_register_tool,
        WORKSPACE,
        approve,
        dynamic_register,
        set(base_tool_functions),
    ),
    "reload_tools": partial(
        reload_tools,
        WORKSPACE,
        tool_functions,
        tools,
    ),
})

# Load persisted custom tools on startup
load_custom_tools(WORKSPACE, tool_functions, tools)

AGENT_INSTRUCTIONS = (
    "Answer the user clearly. "
    "When fixing code, first read the file, then edit it, then run "
    "a relevant command to verify the fix. Use relative workspace paths. "
    "Never access secrets or files outside the workspace. "
    "For computer navigation, use list_drives, list_location, and "
    "read_external_file; external reads require approval. "
    "If a required capability is unavailable, use create_and_register_tool "
    "to write, test, and dynamically register the tool into the runtime. "
    "Once registered, call the new tool in your next step to complete the task."
)


def start_response(user_input, previous_response_id=None):
    request = {
        "model": deployment_name,
        "instructions": AGENT_INSTRUCTIONS,
        "input": user_input,
        "tools": tools,
    }
    if previous_response_id:
        request["previous_response_id"] = previous_response_id
    return client.responses.create(**request)


def run_task(user_input, previous_response_id=None):
    response = start_response(user_input, previous_response_id)

    for tool_round in range(MAX_TOOL_ROUNDS):
        tool_outputs = []

        for item in response.output:

            if item.type != "function_call":
                continue

            arguments = json.loads(item.arguments)
            console.tool_start(item.name, arguments)

            try:
                result = tool_functions[item.name](**arguments)
            except Exception as error:
                result = f"Tool error: {error}"

            if item.name == "run_command":
                try:
                    command_result = json.loads(result)
                    output = command_result["stdout"] or command_result["stderr"]
                    console.tool_result(output.strip() or "Command completed")
                except json.JSONDecodeError:
                    console.tool_result(result)
            elif item.name not in {"read_file", "read_external_file"}:
                console.tool_result(result)
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": item.call_id,
                "output": result
            })

        if not tool_outputs:
            if response.output_text:
                console.assistant(response.output_text)
            return response.id

        response = client.responses.create(
            model=deployment_name,
            instructions=(
                "Give the user a concise final answer. Explain what was fixed "
                "and include verification output when code was changed."
            ),
            previous_response_id=response.id,
            input=tool_outputs,
            tools=tools
        )

    print("Agent stopped: maximum tool rounds reached.")
    return response.id


console.banner()
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

    if user_input.lower() == "help":
        print("\n  Ask for file, project, Git, drive, media, or workflow tasks.")
        print("  Examples: 'list my Y drive', 'run tests', 'show Git changes'.")
        continue

    try:
        session_response_id = run_task(user_input, session_response_id)
    except Exception as error:
        console.error(str(error))