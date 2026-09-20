import json
import os
import shutil
import sys
import textwrap


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
            "dim": "\033[2m",
            "bold": "\033[1m",
            "reset": "\033[0m",
        }

    def color(self, text, name):
        if not self.enabled:
            return text
        return f"{self.colors[name]}{text}{self.colors['reset']}"

    def banner(self):
        title = "PERSONAL AGENT"
        line = "=" * min(self.width, 72)
        print(self.color(line, "cyan"))
        print(self.color(f"  {title}  |  secure multi-tool session", "bold"))
        print(self.color("  Type 'help' for commands, 'exit' to stop.", "dim"))
        print(self.color(line, "cyan"))

    def prompt(self):
        label = self.color("You", "green")
        return input(f"{label} {self.color('>', 'dim')} ").strip()

    def session_ended(self):
        print(self.color("\nSession ended.", "dim"))

    def tool_start(self, name, arguments):
        compact = json.dumps(arguments, ensure_ascii=True)
        if len(compact) > 180:
            compact = compact[:177] + "..."
        print(f"\n{self.color('>', 'cyan')} {self.color(name, 'bold')} {self.color(compact, 'dim')}")

    def tool_result(self, result):
        output = result.strip() if isinstance(result, str) else str(result)
        if len(output) > 600:
            output = output[:597] + "..."
        print(f"  {self.color('ok', 'green')} {output}")

    def assistant(self, message):
        print(f"\n{self.color('Agent', 'blue')}")
        for paragraph in message.splitlines() or [message]:
            if paragraph:
                print(textwrap.fill(paragraph, width=max(self.width - 4, 40),
                                    initial_indent="  ",
                                    subsequent_indent="  "))
            else:
                print()

    def approval(self, message):
        print(f"\n{self.color('APPROVAL REQUIRED', 'yellow')}")
        print(textwrap.indent(message, "  "))
        answer = input(f"  {self.color('Allow?', 'yellow')} [y/N] ").strip().lower()
        granted = answer in {"y", "yes"}
        status = "approved" if granted else "denied"
        print(f"  {self.color(status, 'green' if granted else 'red')}")
        return granted

    def error(self, message):
        print(f"{self.color('Error:', 'red')} {message}")


console = Console()
