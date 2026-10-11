from pathlib import Path
from dotenv import load_dotenv

from agent.orchestrator import AgentOrchestrator
from agent.tool_builder import create_tool_builder_handler
from llm.client import AzureOpenAIClient
from memory.session_store import SessionStore
from tools.registry import ToolRegistry
from ui.console import console

load_dotenv()

WORKSPACE = Path(__file__).parent.resolve()
MAX_TOOL_ROUNDS = 12


def build_application(workspace: Path = WORKSPACE):
    """Wire application components together."""
    session_store = SessionStore(workspace / "sessions")
    registry = ToolRegistry()
    registry.load_base_tools(workspace / "tools.json")

    tool_builder_handler = create_tool_builder_handler(
        workspace,
        console.approval,
        registry.register_custom_tool,
        {"create_and_register_tool"},
        on_progress=console.step,
    )
    registry.bind_function("create_and_register_tool", tool_builder_handler)
    registry.load_custom_tools(workspace)

    llm_client = AzureOpenAIClient()
    orchestrator = AgentOrchestrator(
        llm_client=llm_client,
        registry=registry,
        console=console,
        max_tool_rounds=MAX_TOOL_ROUNDS,
        session_store=session_store,
    )
    return registry, orchestrator


def main():
    console.banner()
    print(console.color("  Only create_and_register_tool is active initially.", "dim"))
    print(console.color("  Type 'help' for usage or 'exit' to stop.", "dim"))

    try:
        registry, orchestrator = build_application()
    except Exception as error:
        console.error(f"Initialization error: {error}")
        return

    session_store = getattr(orchestrator, "session_store", None)
    session_response_id = session_store.response_id if session_store else None

    history_file = WORKSPACE / "sessions" / ".history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    while True:
        try:
            user_input = console.prompt(history_file=str(history_file))
        except (EOFError, KeyboardInterrupt):
            console.session_ended()
            break

        if not user_input:
            continue
        parts = user_input.strip().split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in {"exit", "quit", "q"}:
            console.session_ended()
            break

        if cmd in {"/tools", "tools"}:
            if args:
                tool_name = args[0]
                manifest = registry.manifests.get(tool_name)
                if manifest:
                    console.tool_details_panel(manifest.to_dict())
                else:
                    console.error(f"Tool '{tool_name}' not found.")
            else:
                console.tools_panel(registry.all_schemas, registry.manifests)
            continue

        if cmd == "/disable":
            if not args:
                console.error("Usage: /disable <tool_name>")
            else:
                tool_name = args[0]
                if registry.disable_tool(tool_name, WORKSPACE):
                    print(console.color(f"  Tool '{tool_name}' has been disabled.", "yellow"))
                else:
                    console.error(f"Failed to disable tool '{tool_name}'. Tool not found or cannot be disabled.")
            continue

        if cmd == "/enable":
            if not args:
                console.error("Usage: /enable <tool_name>")
            else:
                tool_name = args[0]
                if registry.enable_tool(tool_name, WORKSPACE):
                    print(console.color(f"  Tool '{tool_name}' has been enabled.", "green"))
                else:
                    console.error(f"Failed to enable tool '{tool_name}'. Tool not found.")
            continue

        if cmd == "/delete":
            if not args:
                console.error("Usage: /delete <tool_name>")
            else:
                tool_name = args[0]
                if tool_name not in registry.manifests:
                    console.error(f"Tool '{tool_name}' not found.")
                elif tool_name == "create_and_register_tool":
                    console.error("Cannot delete core system tool 'create_and_register_tool'.")
                else:
                    confirmed = console.confirm(f"Are you sure you want to permanently delete tool '{tool_name}'?")
                    if confirmed:
                        if registry.delete_tool(tool_name, WORKSPACE):
                            print(console.color(f"  Tool '{tool_name}' and its file have been permanently deleted.", "red"))
                        else:
                            console.error(f"Failed to delete tool '{tool_name}'.")
                    else:
                        print(console.color("  Deletion cancelled.", "dim"))
            continue

        if cmd == "/tool-history":
            if not args:
                console.error("Usage: /tool-history <tool_name>")
            else:
                tool_name = args[0]
                manifest = registry.manifests.get(tool_name)
                if not manifest:
                    console.error(f"Tool '{tool_name}' not found.")
                else:
                    console.tool_history_panel(tool_name, manifest.history, manifest.version)
            continue

        if cmd in {"/history", "history"}:
            if session_store:
                console.history_panel(session_store.get_messages(), session_store.get_tool_calls())
            else:
                console.error("Session store is not initialized.")
            continue

        if cmd in {"/new", "new"}:
            if session_store:
                new_sess = session_store.new_session()
                session_response_id = None
                print(console.color(f"  Started fresh session: {new_sess.session_id}", "green"))
            else:
                console.error("Session store is not initialized.")
            continue

        if cmd in {"/sessions", "sessions"}:
            if session_store:
                if args:
                    target_id = args[0]
                    loaded = session_store.load_session(target_id)
                    if loaded:
                        session_response_id = loaded.response_id
                        print(console.color(f"  Loaded session: {target_id} ({len(loaded.messages)} messages)", "green"))
                    else:
                        console.error(f"Session '{target_id}' not found.")
                else:
                    console.sessions_panel(session_store.list_sessions(), active_session_id=session_store.active_session_id)
            else:
                console.error("Session store is not initialized.")
            continue

        if cmd in {"/clear-history", "clear-history"}:
            if session_store:
                confirmed = console.confirm("Are you sure you want to clear the active session history?")
                if confirmed:
                    session_store.clear()
                    session_response_id = None
                    print(console.color("  Active session history cleared and reset.", "yellow"))
                else:
                    print(console.color("  Clear history cancelled.", "dim"))
            else:
                console.error("Session store is not initialized.")
            continue

        if cmd in {"/command-history", "command-history"}:
            print(f"\n{console.color('[ COMMAND HISTORY ]', 'cyan')} {console.color(f'{len(console.command_history)} items', 'dim')}")
            for idx, item in enumerate(console.command_history[-20:], 1):
                print(f"  {idx}. {item}")
            continue

        if cmd in {"/help", "help"}:
            console.help_panel()
            print("\n  Ask for any capability. The agent will propose, test, approve, and use a tool.")
            continue

        try:
            session_response_id = orchestrator.run_task(user_input, session_response_id)
        except KeyboardInterrupt:
            console.interrupted()
        except Exception as error:
            console.error(str(error))


if __name__ == "__main__":
    main()
