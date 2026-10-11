"""Security policies and rule definitions for YASHI Agent custom tools."""

from typing import Set

BLOCKED_MODULES: Set[str] = {
    # Shell, OS & Process Execution
    "os",
    "sys",
    "subprocess",
    "shutil",
    "commands",
    "pty",
    "multiprocessing",
    "threading",
    "signal",
    "posix",
    "nt",
    # Low-level & Memory Access
    "ctypes",
    "_ctypes",
    "cffi",
    # Network & Sockets
    "socket",
    "urllib",
    "requests",
    "http",
    "httpx",
    "aiohttp",
    "webbrowser",
    "ftplib",
    "poplib",
    "imaplib",
    "smtplib",
    "telnetlib",
    # Dynamic Code Execution & Serialization Escapes
    "importlib",
    "builtins",
    "__builtin__",
    "pickle",
    "shelve",
    "marshal",
    "code",
    "codeop",
    # Package Management
    "pip",
    "setuptools",
    "ensurepip",
}

BLOCKED_BUILTIN_CALLS: Set[str] = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "open",  # Restricts unrestricted arbitrary file operations
    "breakpoint",
}

BLOCKED_ATTRIBUTES: Set[str] = {
    "__subclasses__",
    "__globals__",
    "__code__",
    "__closure__",
    "__bases__",
    "__mro__",
    "__builtins__",
}

SENSITIVE_ENV_KEYS: Set[str] = {
    "AZURE_OPENAI_API_KEY",
    "AZURE_OPENAI_ENDPOINT",
    "AZURE_OPENAI_DEPLOYMENT",
    "AZURE_AUTH_URL",
    "OPENAI_API_KEY",
}

DEFAULT_SANDBOX_TIMEOUT_SECONDS: float = 5.0
DEFAULT_RUNTIME_TIMEOUT_SECONDS: float = 10.0
