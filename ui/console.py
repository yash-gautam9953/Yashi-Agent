import json
import os
import shutil
import sys
import textwrap
import threading
import time
from typing import Any, List, Optional

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.formatted_text import ANSI
    from prompt_toolkit.history import FileHistory, InMemoryHistory
    _PROMPT_TOOLKIT_AVAILABLE = True
except ImportError:
    _PROMPT_TOOLKIT_AVAILABLE = False


class Console:
    def __init__(self, history_file: Optional[str] = None):
        self.enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        self.width = min(shutil.get_terminal_size((100, 24)).columns, 110)
        self.supports_unicode = (
            sys.stdout.encoding is not None and "utf" in sys.stdout.encoding.lower()
        )
        self.colors = {
            "cyan": "\033[36m",
            "green": "\033[32m",
            "yellow": "\033[33m",
            "red": "\033[31m",
            "blue": "\033[34m",
            "magenta": "\033[35m",
            "dim": "\033[2m",
            "bold": "\033[1m",
            "reset": "\033[0m",
        }
        self._thinking_stop = None
        self._thinking_thread = None
        self.history_file = history_file
        self.command_history: List[str] = []
        self._prompt_session: Optional[Any] = None

    def color(self, text, name):
        if not self.enabled:
            return text
        return f"{self.colors[name]}{text}{self.colors['reset']}"

    def _content_width(self):
        return max(min(self.width, 68) - 4, 40)

    def _fit(self, text):
        text = " ".join(str(text).split())
        limit = self._content_width()
        return text if len(text) <= limit else text[:limit - 3] + "..."

    def banner(self):
        width = min(self.width, 68)
        line = "=" * width
        print(self.color("\n  +" + line + "+", "cyan"))
        print(self.color("  |", "cyan") + self.color("  [ YASHI ]  ", "magenta") +
              self.color("PERSONAL AI AGENT", "bold") + self.color(" " * (width - 29) + "|", "cyan"))
        print(self.color("  |  dynamic tools  |  secure approvals  |  ready".ljust(width + 2) + "|", "dim"))
        print(self.color("  +" + line + "+", "cyan"))
        print(self.color("  /tools  active tools     /help  commands     exit  quit", "dim"))

    def step(self, name: str) -> None:
        """Render a clear multi-step progress indicator."""
        if self._thinking_stop is not None:
            self.thinking_stop()
        arrow = "→" if self.supports_unicode else "->"
        print(f"  {self.color(arrow, 'cyan')} {self.color(name, 'bold')}", flush=True)

    def prompt(self, history_file: Optional[str] = None) -> str:
        """Prompt user with command history and graceful Ctrl+C handling."""
        if history_file and history_file != self.history_file:
            self.history_file = history_file
            self._prompt_session = None

        raw_label = f"\n{self.color('>>', 'green')} {self.color('you', 'green')}: "

        if _PROMPT_TOOLKIT_AVAILABLE and sys.stdin.isatty():
            if self._prompt_session is None:
                if self.history_file:
                    hist = FileHistory(str(self.history_file))
                else:
                    hist = InMemoryHistory()
                self._prompt_session = PromptSession(history=hist)

            try:
                line = self._prompt_session.prompt(ANSI(raw_label)).strip()
                if line:
                    self.command_history.append(line)
                return line
            except KeyboardInterrupt:
                print()
                return ""
            except EOFError:
                raise
        else:
            try:
                line = input(raw_label).strip()
                if line:
                    self.command_history.append(line)
                return line
            except KeyboardInterrupt:
                print()
                return ""

    def thinking_start(self):
        if self._thinking_stop is not None:
            return

        stop_event = threading.Event()
        self._thinking_stop = stop_event

        if not self.enabled:
            print("\nYASHI is thinking...", flush=True)
            return

        def animate():
            frames = (".", "..", "...", "....")
            index = 0
            while not stop_event.is_set():
                print(f"\r  {self.color('YASHI is thinking' + frames[index], 'dim')}",
                      end="", flush=True)
                index = (index + 1) % len(frames)
                stop_event.wait(0.25)

        self._thinking_thread = threading.Thread(target=animate, daemon=True)
        self._thinking_thread.start()

    def thinking_stop(self):
        if self._thinking_stop is None:
            return

        self._thinking_stop.set()
        if self._thinking_thread is not None:
            self._thinking_thread.join()
        if self.enabled:
            print("\r" + (" " * (len("  YASHI is thinking....") + 4)) + "\r",
                  end="", flush=True)
        self._thinking_stop = None
        self._thinking_thread = None

    def session_ended(self):
        print(self.color("\n  [ session ended ]", "dim"))

    def interrupted(self):
        self.thinking_stop()
        print(self.color("\n  [ cancelled by user (Ctrl+C) ]", "yellow"))

    def tools_panel(self, tools, manifests=None):
        line = "-" * min(self.width, 68)
        print(f"\n{self.color('[ ACTIVE TOOLS ]', 'cyan')} {self.color(f'{len(tools)} available', 'dim')}")
        print(self.color(line, "dim"))
        for schema in tools:
            name = schema.get("name", "unknown")
            description = schema.get("description", "No description")
            version_str = ""
            status_str = ""
            if manifests and name in manifests:
                m = manifests[name]
                ver = m.version if hasattr(m, "version") else m.get("version", "1.0.0")
                version_str = f" v{ver}"
                if hasattr(m, "enabled") and not m.enabled:
                    status_str = " (disabled)"
            available = self._fit(f"{name}{version_str}{status_str}  -  {description}")
            print(f"  {self.color('*', 'cyan')} {self.color(available, 'bold')}")
        print(self.color(line, "dim"))

    def tool_details_panel(self, m: dict):
        line = "-" * min(self.width, 68)
        print(f"\n{self.color('[ TOOL MANIFEST ]', 'cyan')} {self.color(m.get('name', 'unknown'), 'bold')}")
        print(self.color(line, "dim"))
        print(f"  {self.color('Name:', 'bold')}         {m.get('name')}")
        print(f"  {self.color('Version:', 'bold')}      {m.get('version', '1.0.0')}")
        status_color = "green" if m.get("enabled", True) else "red"
        status_text = "Enabled / Active" if m.get("enabled", True) else "Disabled"
        print(f"  {self.color('Status:', 'bold')}       {self.color(status_text, status_color)}")
        print(f"  {self.color('Risk Level:', 'bold')}   {m.get('risk_level', 'low').upper()}")
        print(f"  {self.color('Author:', 'bold')}       {m.get('author', 'agent')}")
        print(f"  {self.color('File Path:', 'bold')}    custom_tools/{m.get('file', m.get('name') + '.py')}")
        print(f"  {self.color('Checksum:', 'bold')}     {m.get('checksum', 'N/A')}")
        print(f"  {self.color('Created At:', 'bold')}   {m.get('created_at', 'N/A')}")
        print(f"  {self.color('Updated At:', 'bold')}   {m.get('updated_at', 'N/A')}")
        perms = m.get("permissions")
        perms_str = ", ".join(perms) if isinstance(perms, list) and perms else "None"
        print(f"  {self.color('Permissions:', 'bold')}  {perms_str}")
        deps = m.get("dependencies")
        deps_str = ", ".join(deps) if isinstance(deps, list) and deps else "None"
        print(f"  {self.color('Dependencies:', 'bold')} {deps_str}")
        print(f"\n  {self.color('Description:', 'bold')}\n    {m.get('description')}")
        print(self.color(line, "dim"))

    def tool_history_panel(self, name: str, history: list, current_version: str = "1.0.0"):
        line = "-" * min(self.width, 68)
        print(f"\n{self.color('[ TOOL REVISION HISTORY ]', 'cyan')} {self.color(name, 'bold')}")
        print(self.color(line, "dim"))
        print(f"  Current active version: {self.color('v' + current_version, 'bold')}")
        if not history:
            print(f"  {self.color('No prior revisions recorded (initial release).', 'dim')}")
        else:
            for idx, rev in enumerate(history, 1):
                ver = rev.get("version", "unknown")
                updated = rev.get("updated_at", "unknown")
                csum = rev.get("checksum", "unknown")
                desc = rev.get("description", "")
                print(f"  {idx}. v{ver} | updated: {updated} | hash: {csum}")
                if desc:
                    print(f"     desc: {desc}")
        print(self.color(line, "dim"))

    def confirm(self, prompt: str) -> bool:
        print(f"\n{self.color('[ CONFIRMATION REQUIRED ]', 'yellow')}")
        print(f"  {prompt}")
        try:
            answer = input(f"  {self.color('Proceed? [y/N]:', 'yellow')} ").strip().lower()
            return answer in {"y", "yes"}
        except (KeyboardInterrupt, EOFError):
            print(self.color(" [ cancelled ]", "dim"))
            return False

    def tool_start(self, name, arguments):
        if name == "create_and_register_tool":
            compact = (
                f"name={arguments.get('name', 'unknown')} "
                f"| tests={'yes' if arguments.get('test_code') else 'no'}"
            )
            status = "creating and testing tool..."
        else:
            compact = json.dumps(arguments, ensure_ascii=True)
            if len(compact) > 120:
                compact = compact[:117] + "..."
            status = "running..."
        print(f"\n{self.color('[ TOOL ]', 'cyan')} {self.color(name, 'bold')}")
        print(f"  {self.color('input', 'dim')}  {compact}")
        print(f"  {self.color('status', 'dim')} {status}")

    def tool_result(self, result):
        output = result.strip() if isinstance(result, str) else str(result)
        status_tag = self.color('[ done ]', 'green')
        if isinstance(result, str):
            try:
                data = json.loads(result)
            except json.JSONDecodeError:
                data = None

            if isinstance(data, dict):
                st = data.get("status")
                if st == "registered":
                    attempts = data.get("attempts_used", 1)
                    att_str = f" (attempt {attempts})" if attempts > 1 else ""
                    output = f"registered {data.get('name', 'tool')}{att_str}"
                elif st == "test_failed":
                    status_tag = self.color('[ retry ]', 'yellow')
                    att = data.get("attempt", 1)
                    max_att = data.get("max_attempts", 3)
                    output = f"test failed [attempt {att}/{max_att}]: {data.get('error_type', 'Error')} - {data.get('diagnosis', data.get('error', ''))}"
                elif st == "max_attempts_exceeded":
                    status_tag = self.color('[ failed ]', 'red')
                    output = f"max attempts exceeded ({data.get('max_attempts', 3)}): {data.get('error_type', 'Error')}"
                elif st == "security_violation":
                    status_tag = self.color('[ blocked ]', 'red')
                    output = f"security violation: {data.get('error', '')}"
                elif st == "timeout":
                    status_tag = self.color('[ timeout ]', 'red')
                    output = f"timeout: {data.get('error', 'Tool execution exceeded limit')}"
                elif st == "denied":
                    status_tag = self.color('[ denied ]', 'red')
                    output = f"denied {data.get('name', 'tool')}"
                elif st == "duplicate_found":
                    status_tag = self.color('[ reuse ]', 'cyan')
                    output = f"duplicate detected: reuse '{data.get('existing_tool')}'"
                elif data.get("ok") and data.get("path"):
                    output = f"created {data['path']}"
                elif data.get("error"):
                    output = str(data["error"])
            elif "timed out after" in output.lower():
                status_tag = self.color('[ timeout ]', 'red')
        if len(output) > 600:
            output = output[:597] + "..."
        print(f"  {status_tag} {output}")

    def stream_assistant_start(self):
        """Prepare console for streaming assistant response tokens."""
        self.thinking_stop()
        print(f"\n{self.color('[ YASHI ]', 'blue')} {self.color('response', 'dim')}")
        print(self.color("  | ", "blue"), end="", flush=True)

    def stream_assistant_chunk(self, chunk: str):
        """Output streamed token chunk cleanly within assistant borders."""
        if not chunk:
            return
        formatted = chunk.replace("\n", "\n" + self.color("  | ", "blue"))
        print(formatted, end="", flush=True)

    def stream_assistant_end(self):
        """Close streamed assistant response box."""
        print(self.color("\n  +--", "blue"))

    def assistant(self, message: str, stream: bool = True):
        self.thinking_stop()
        if stream and self.enabled and sys.stdout.isatty():
            self.stream_assistant_start()
            words = message.split(" ")
            for i, word in enumerate(words):
                chunk = word if i == len(words) - 1 else word + " "
                self.stream_assistant_chunk(chunk)
                time.sleep(0.008)
            self.stream_assistant_end()
        else:
            print(f"\n{self.color('[ YASHI ]', 'blue')} {self.color('response', 'dim')}")
            for paragraph in message.splitlines() or [message]:
                if paragraph:
                    print(textwrap.fill(paragraph, width=max(self.width - 4, 40),
                                        initial_indent="  | ",
                                        subsequent_indent="  | "))
                else:
                    print(self.color("  |", "blue"))
            print(self.color("  +--", "blue"))

    def approval(self, message_or_report):
        if hasattr(message_or_report, "format_screen"):
            return self.tool_approval_prompt(message_or_report)

        print(f"\n{self.color('[ APPROVAL REQUIRED ]', 'yellow')}")
        print(textwrap.indent(str(message_or_report), "  | "))
        try:
            answer = input(f"  {self.color('Allow?', 'yellow')} [y/N]: ").strip().lower()
            granted = answer in {"y", "yes"}
        except (KeyboardInterrupt, EOFError):
            print()
            granted = False
        status = "approved" if granted else "denied"
        print(f"  {self.color('[ ' + status + ' ]', 'green' if granted else 'red')}")
        return granted

    def tool_approval_prompt(self, report):
        print(report.format_screen(self))
        while True:
            try:
                choice = input(f"\n  {self.color('Choice [A/R/V]:', 'yellow')} ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print(f"\n  {self.color('[ cancelled ]', 'red')}\n")
                return False

            if choice in {"a", "approve", "y", "yes"}:
                print(f"  {self.color('[ approved ]', 'green')}\n")
                return True
            elif choice in {"r", "reject", "n", "no"}:
                print(f"  {self.color('[ rejected ]', 'red')}\n")
                return False
            elif choice in {"v", "view", "report"}:
                print(report.format_detailed_report(self))
            else:
                print(self.color("  Please enter 'A' to Approve, 'R' to Reject, or 'V' to View security report.", "dim"))

    def error(self, message: str, title: str = "ERROR", tip: Optional[str] = None):
        """Render a structured, formatted error panel with optional guidance tip."""
        self.thinking_stop()
        width = min(self.width, 68)
        line = "-" * width
        print(f"\n{self.color('[ ' + title.upper() + ' ]', 'red')}")
        print(self.color(line, "dim"))
        for msg_line in str(message).splitlines():
            print(f"  {self.color('!', 'red')} {msg_line}")
        if tip:
            print(f"\n  {self.color('Tip:', 'yellow')} {self.color(tip, 'dim')}")
        print(self.color(line, "dim"))

    def warning(self, message: str):
        self.thinking_stop()
        print(f"\n{self.color('[ WARNING ]', 'yellow')} {message}")

    def api_error(self, error: Exception):
        """Format Azure OpenAI API errors gracefully with actionable troubleshooting advice."""
        self.thinking_stop()
        err_type = type(error).__name__
        err_str = str(error)

        if "AuthenticationError" in err_type or "401" in err_str:
            title = "API AUTHENTICATION ERROR"
            tip = "Check your AZURE_OPENAI_API_KEY and endpoint URL in .env."
        elif "RateLimitError" in err_type or "429" in err_str:
            title = "API RATE LIMIT EXCEEDED"
            tip = "The Azure OpenAI quota or rate limit was reached. Please wait a moment and retry."
        elif "APIConnectionError" in err_type:
            title = "API CONNECTION FAILED"
            tip = "Unable to connect to Azure OpenAI service. Check your network or DNS connection."
        elif "APITimeoutError" in err_type or "Timeout" in err_type:
            title = "API REQUEST TIMEOUT"
            tip = "Azure OpenAI took too long to respond. The service might be temporarily slow."
        elif "BadRequestError" in err_type or "400" in err_str:
            title = "API BAD REQUEST"
            tip = "The request parameters or content filter rejected the prompt."
        else:
            title = f"API ERROR ({err_type})"
            tip = "Review request parameters or check Azure OpenAI service status."

        from memory.session_store import sanitize_text
        clean_msg = sanitize_text(err_str)
        self.error(clean_msg, title=title, tip=tip)

    def history_panel(self, messages: list, tool_calls: list = None):
        line = "-" * min(self.width, 68)
        print(f"\n{self.color('[ SESSION CONVERSATION HISTORY ]', 'cyan')} {self.color(f'{len(messages)} messages', 'dim')}")
        print(self.color(line, "dim"))
        if not messages:
            print(f"  {self.color('No messages recorded in current session.', 'dim')}")
        else:
            for item in messages:
                role = item.get("role", "unknown").upper()
                content = item.get("content", "")
                ts = item.get("timestamp", "")
                role_color = "green" if role == "USER" else "blue"
                print(f"  {self.color(f'[{role}]', role_color)} {self.color(ts, 'dim')}")
                if isinstance(content, str):
                    for line_str in content.splitlines():
                        print(f"    {line_str}")
                else:
                    print(f"    {content}")
                print()

        if tool_calls:
            print(f"{self.color('[ TOOL EXECUTION HISTORY ]', 'cyan')} {self.color(f'{len(tool_calls)} calls', 'dim')}")
            print(self.color(line, "dim"))
            for tc in tool_calls:
                name = tc.get("tool_name", "unknown")
                status = tc.get("status", "success")
                summary = tc.get("output_summary", "")
                st_color = "green" if status == "success" else "yellow"
                print(f"  * {self.color(name, 'bold')} [{self.color(status, st_color)}]: {summary}")
        print(self.color(line, "dim"))

    def sessions_panel(self, sessions: list, active_session_id: str = ""):
        line = "-" * min(self.width, 68)
        print(f"\n{self.color('[ SAVED SESSIONS ]', 'cyan')} {self.color(f'{len(sessions)} total', 'dim')}")
        print(self.color(line, "dim"))
        if not sessions:
            print(f"  {self.color('No saved sessions found.', 'dim')}")
        else:
            for s in sessions:
                sid = s.get("session_id", "unknown")
                created = s.get("created_at", "unknown")
                msgs = s.get("messages_count", 0)
                tools = s.get("tool_calls_count", 0)
                is_active = (sid == active_session_id) or s.get("active", False)
                active_badge = f" {self.color('(ACTIVE)', 'green')}" if is_active else ""
                print(f"  * {self.color(sid, 'bold')}{active_badge}")
                print(f"    created: {created} | messages: {msgs} | tools: {tools}")
        print(self.color(line, "dim"))

    def help_panel(self):
        print(f"\n{self.color('[ COMMANDS ]', 'cyan')}")
        print("  /tools               Show all registered tools and their status")
        print("  /tools <name>        Show detailed manifest for a specific tool")
        print("  /disable <name>      Disable a tool (excludes it from agent execution)")
        print("  /enable <name>       Enable a disabled tool")
        print("  /delete <name>       Delete a custom tool (requires confirmation)")
        print("  /tool-history <name> Show revision history and hashes for a tool")
        print("  /history             Show conversation and tool usage history for active session")
        print("  /new                 Start a fresh conversation session")
        print("  /sessions            List all saved sessions")
        print("  /sessions <id>       Load a specific previous session")
        print("  /clear-history       Clear active session history (requires confirmation)")
        print("  /command-history     Show recent command history")
        print("  /help                Show this command panel")
        print("  exit                 End the session")

console = Console()

