import json
import os
import shutil
import sys
import textwrap
import threading


class Console:
    def __init__(self):
        self.enabled = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        self.width = min(shutil.get_terminal_size((100, 24)).columns, 110)
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

    def prompt(self):
        label = self.color("you", "green")
        return input(f"\n{self.color('>>', 'green')} {label}: ").strip()

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
            print("\r" + (" " * (len("  YASHI is thinking....") + 1)) + "\r",
                  end="", flush=True)
        self._thinking_stop = None
        self._thinking_thread = None

    def session_ended(self):
        print(self.color("\n  [ session ended ]", "dim"))

    def tools_panel(self, tools):
        line = "-" * min(self.width, 68)
        print(f"\n{self.color('[ ACTIVE TOOLS ]', 'cyan')} {self.color(f'{len(tools)} loaded', 'dim')}")
        print(self.color(line, "dim"))
        for schema in tools:
            name = schema.get("name", "unknown")
            description = schema.get("description", "No description")
            available = self._fit(f"{name}  -  {description}")
            print(f"  {self.color('*', 'cyan')} {self.color(available, 'bold')}")
        print(self.color(line, "dim"))

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
        if isinstance(result, str):
            try:
                data = json.loads(result)
            except json.JSONDecodeError:
                data = None
            if isinstance(data, dict):
                if data.get("status") == "registered":
                    output = f"registered {data.get('name', 'tool')}"
                elif data.get("status") == "denied":
                    output = f"denied {data.get('name', 'tool')}"
                elif data.get("ok") and data.get("path"):
                    output = f"created {data['path']}"
                elif data.get("error"):
                    output = str(data["error"])
        if len(output) > 600:
            output = output[:597] + "..."
        print(f"  {self.color('[ done ]', 'green')} {output}")

    def assistant(self, message):
        print(f"\n{self.color('[ YASHI ]', 'blue')} {self.color('response', 'dim')}")
        for paragraph in message.splitlines() or [message]:
            if paragraph:
                print(textwrap.fill(paragraph, width=max(self.width - 4, 40),
                                    initial_indent="  | ",
                                    subsequent_indent="  | "))
            else:
                print(self.color("  |", "blue"))
        print(self.color("  +--", "blue"))

    def approval(self, message):
        print(f"\n{self.color('[ APPROVAL REQUIRED ]', 'yellow')}")
        print(textwrap.indent(message, "  | "))
        answer = input(f"  {self.color('Allow?', 'yellow')} [y/N]: ").strip().lower()
        granted = answer in {"y", "yes"}
        status = "approved" if granted else "denied"
        print(f"  {self.color('[ ' + status + ' ]', 'green' if granted else 'red')}")
        return granted

    def error(self, message):
        print(f"\n{self.color('[ ERROR ]', 'red')} {message}")

    def help_panel(self):
        print(f"\n{self.color('[ COMMANDS ]', 'cyan')}")
        print("  /tools   Show active tools")
        print("  /help    Show this panel")
        print("  exit     End the session")

console = Console()
