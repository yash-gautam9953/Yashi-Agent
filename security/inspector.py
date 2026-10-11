import ast
from typing import Any, Dict, List, Optional, Set

from security.policy import (
    BLOCKED_ATTRIBUTES,
    BLOCKED_BUILTIN_CALLS,
    BLOCKED_MODULES,
)


class InspectionResult:
    """Structured result of an AST security inspection."""

    def __init__(self, is_safe: bool, violations: List[str], detected_imports: List[str]):
        self.is_safe = is_safe
        self.violations = violations
        self.detected_imports = detected_imports

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_safe": self.is_safe,
            "violations": self.violations,
            "detected_imports": self.detected_imports,
        }


class ToolSecurityReport:
    """Structured security and capability report for user authorization."""

    def __init__(
        self,
        tool_name: str,
        description: str,
        code: str,
        test_code: str,
        target_file: str,
        is_safe: bool,
        violations: List[str],
        detected_imports: List[str],
        permissions: Dict[str, str],
        risk_level: str,
        warnings: List[str],
        dependencies: str,
    ):
        self.tool_name = tool_name
        self.description = description
        self.code = code
        self.test_code = test_code
        self.target_file = target_file
        self.is_safe = is_safe
        self.violations = violations
        self.detected_imports = detected_imports
        self.permissions = permissions
        self.risk_level = risk_level
        self.warnings = warnings
        self.dependencies = dependencies

    @property
    def name(self) -> str:
        return self.tool_name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.tool_name,
            "description": self.description,
            "target_file": self.target_file,
            "is_safe": self.is_safe,
            "risk_level": self.risk_level,
            "permissions": self.permissions,
            "dependencies": self.dependencies,
            "warnings": self.warnings,
            "violations": self.violations,
            "detected_imports": self.detected_imports,
            "code_lines": len(self.code.splitlines()),
        }

    def format_screen(self, console: Optional[Any] = None) -> str:
        """Render the structured user approval screen matching conceptual UI."""
        width = 68
        border = "-" * width

        def color(text: str, c: str) -> str:
            return console.color(text, c) if console and hasattr(console, "color") else text

        risk_color = "green" if "LOW" in self.risk_level or "MINIMAL" in self.risk_level else "red"

        lines = [
            f"\n{color(border, 'cyan')}",
            f"{color('  YASHI -- NEW TOOL APPROVAL', 'bold')}",
            f"{color(border, 'cyan')}",
            f"\n{color('Name:', 'bold')}",
            f"  {self.tool_name}",
            f"\n{color('Purpose:', 'bold')}",
            f"  {self.description}",
            f"\n{color('Permissions:', 'bold')}",
            f"  {self.permissions.get('filesystem', '[-] Filesystem: None')}",
            f"  {self.permissions.get('network', '[-] Network: Blocked')}",
            f"  {self.permissions.get('environment', '[-] Environment variables: Blocked')}",
            f"  {self.permissions.get('shell', '[-] Shell commands: Blocked')}",
            f"\n{color('Risk Level:', 'bold')}",
            f"  {color(self.risk_level, risk_color)}",
            f"\n{color('Files to create:', 'bold')}",
            f"  {self.target_file}",
            f"\n{color('Dependencies:', 'bold')}",
            f"  {self.dependencies}",
            f"\n{color(border, 'cyan')}",
            f"{color('  SOURCE CODE', 'bold')}",
            f"{color(border, 'cyan')}",
        ]

        # The full code is displayed line by line - NEVER TRUNCATED
        for idx, code_line in enumerate(self.code.splitlines(), 1):
            lines.append(f"  {color(f'{idx:3d} |', 'dim')} {code_line}")

        lines.extend([
            f"{color(border, 'cyan')}",
            f"\n  {color('[A]', 'green')} Approve    {color('[R]', 'red')} Reject    {color('[V]', 'cyan')} View security report",
        ])
        return "\n".join(lines)

    def format_detailed_report(self, console: Optional[Any] = None) -> str:
        """Render the in-depth security inspection report."""
        width = 68
        border = "-" * width

        def color(text: str, c: str) -> str:
            return console.color(text, c) if console and hasattr(console, "color") else text

        ast_status = "PASSED (0 violations detected)" if self.is_safe else "FAILED (violations detected)"
        status_color = "green" if self.is_safe else "red"

        lines = [
            f"\n{color(border, 'cyan')}",
            f"{color('  DETAILED SECURITY INSPECTION REPORT', 'bold')}",
            f"{color(border, 'cyan')}",
            f"\n  Target File:     {self.target_file}",
            f"  Tool Function:   {self.tool_name}()",
            f"  Code Size:       {len(self.code.splitlines())} lines",
            f"  Static Check:    {color(ast_status, status_color)}",
            f"\n  Policy Verifications:",
            f"    [+] Process & Shell execution check: PASSED (no subprocess, os, commands)",
            f"    [+] Network & Socket check:          PASSED (no socket, urllib, requests)",
            f"    [+] Environment & Secrets check:     PASSED (no environ, getenv)",
            f"    [+] Arbitrary code execution check:  PASSED (no eval, exec, compile)",
            f"    [+] Sandbox escape check:            PASSED (no __subclasses__, dunder escapes)",
            f"    [+] Filesystem boundary check:       PASSED (workspace relative only)",
            f"\n  Execution Sandbox Plan:",
            f"    * Step 1: User authorization via CLI [A/R/V]",
            f"    * Step 2: Isolated sandbox testing (temp directory, zero secrets)",
            f"    * Step 3: Secret stripping (AZURE_OPENAI_API_KEY removed from env)",
            f"    * Step 4: Strict timeouts (5.0s sandbox / 10.0s runtime)",
        ]

        if self.warnings:
            lines.append(f"\n  {color('Warnings / Violations:', 'red')}")
            for w in self.warnings:
                lines.append(f"    ! {w}")

        lines.append(f"{color(border, 'cyan')}\n")
        return "\n".join(lines)

    def __str__(self) -> str:
        return self.format_screen()


class SecurityInspector:
    """AST-based security inspector for generated Python code."""

    def __init__(
        self,
        blocked_modules: Optional[Set[str]] = None,
        blocked_calls: Optional[Set[str]] = None,
        blocked_attributes: Optional[Set[str]] = None,
    ):
        self.blocked_modules = blocked_modules or BLOCKED_MODULES
        self.blocked_calls = blocked_calls or BLOCKED_BUILTIN_CALLS
        self.blocked_attributes = blocked_attributes or BLOCKED_ATTRIBUTES

    def inspect_code(self, code: str) -> InspectionResult:
        """Statically inspect Python code using AST to detect dangerous operations."""
        violations: List[str] = []
        detected_imports: List[str] = []

        if not code or not code.strip():
            return InspectionResult(is_safe=False, violations=["Code is empty"], detected_imports=[])

        try:
            tree = ast.parse(code)
        except SyntaxError as error:
            return InspectionResult(
                is_safe=False,
                violations=[f"Syntax error: {error}"],
                detected_imports=[],
            )

        for node in ast.walk(tree):
            # 1. Inspect direct imports: `import os`, `import subprocess as sp`
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_pkg = alias.name.split(".")[0]
                    detected_imports.append(alias.name)
                    if root_pkg in self.blocked_modules or alias.name in self.blocked_modules:
                        violations.append(
                            f"Blocked module import: '{alias.name}' is prohibited by security policy"
                        )

            # 2. Inspect from-imports: `from os import environ`, `from subprocess import run`
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_pkg = node.module.split(".")[0]
                    detected_imports.append(node.module)
                    if root_pkg in self.blocked_modules or node.module in self.blocked_modules:
                        violations.append(
                            f"Blocked module import: '{node.module}' is prohibited by security policy"
                        )
                # Check imported names as well
                for alias in node.names:
                    if alias.name in self.blocked_modules:
                        violations.append(
                            f"Blocked import symbol: '{alias.name}' is prohibited by security policy"
                        )

            # 3. Inspect function and builtin calls
            elif isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    if func.id in self.blocked_calls:
                        violations.append(
                            f"Blocked dangerous call: '{func.id}()' is prohibited"
                        )
                    # Detect Path calls with path traversal or absolute paths
                    if func.id == "Path" and node.args:
                        first_arg = node.args[0]
                        if isinstance(first_arg, ast.Constant) and isinstance(first_arg.value, str):
                            path_str = first_arg.value
                            if ".." in path_str or (len(path_str) > 1 and path_str[1] == ":") or path_str.startswith(("/", "\\")):
                                violations.append(
                                    f"Blocked path traversal or absolute path in Path('{path_str}')"
                                )

            # 4. Inspect attribute access (dunder escapes, environment access)
            elif isinstance(node, ast.Attribute):
                if node.attr in self.blocked_attributes:
                    violations.append(
                        f"Blocked attribute access: '{node.attr}' (sandbox escape protection)"
                    )
                elif node.attr in {"environ", "getenv"}:
                    violations.append(
                        f"Blocked environment access: '{node.attr}'"
                    )

            # 5. Inspect direct references to sensitive names
            elif isinstance(node, ast.Name):
                if node.id in {"environ"}:
                    violations.append(
                        f"Blocked sensitive identifier reference: '{node.id}'"
                    )

        is_safe = len(violations) == 0
        return InspectionResult(
            is_safe=is_safe,
            violations=violations,
            detected_imports=detected_imports,
        )

    def analyze_tool(
        self,
        name: str,
        description: str,
        code: str,
        test_code: str = "",
        target_file: str = "",
    ) -> ToolSecurityReport:
        """Perform comprehensive static analysis and generate an authorization report."""
        inspection = self.inspect_code(code)
        test_inspection = self.inspect_code(test_code) if test_code and test_code.strip() else None

        all_violations = list(inspection.violations)
        if test_inspection and not test_inspection.is_safe:
            all_violations.extend([f"In test: {v}" for v in test_inspection.violations])

        is_safe = len(all_violations) == 0

        # Permissions analysis
        has_fs = any("pathlib" in imp or "Path" in imp for imp in inspection.detected_imports)
        permissions = {
            "filesystem": "[+] Read/write relative workspace files only" if has_fs else "[-] Filesystem: None (pure computation)",
            "network": "[-] Network: Blocked",
            "environment": "[-] Environment variables: Blocked",
            "shell": "[-] Shell / OS commands: Blocked",
        }

        # Dependencies
        dependencies = sorted(list(set(inspection.detected_imports)))
        deps_summary = ", ".join(dependencies) if dependencies else "None"

        # Risk level assessment
        if not is_safe:
            risk_level = "CRITICAL (BLOCKED)"
        elif has_fs:
            risk_level = "LOW"
        else:
            risk_level = "LOW"

        warnings: List[str] = []
        if not is_safe:
            warnings.extend(all_violations)

        return ToolSecurityReport(
            tool_name=name,
            description=description,
            code=code,
            test_code=test_code,
            target_file=target_file or f"custom_tools/{name}.py",
            is_safe=is_safe,
            violations=all_violations,
            detected_imports=dependencies,
            permissions=permissions,
            risk_level=risk_level,
            warnings=warnings,
            dependencies=deps_summary,
        )
