import os
import subprocess
import sys
import tempfile
import time
from typing import Any, Dict, Optional

from security.inspector import SecurityInspector
from security.policy import (
    DEFAULT_SANDBOX_TIMEOUT_SECONDS,
    SENSITIVE_ENV_KEYS,
)


class ToolSandbox:
    """Isolated environment for testing and verifying generated Python tools."""

    def __init__(
        self,
        timeout: float = DEFAULT_SANDBOX_TIMEOUT_SECONDS,
        inspector: Optional[SecurityInspector] = None,
    ):
        self.timeout = timeout
        self.inspector = inspector or SecurityInspector()

    def _build_clean_environment(self) -> Dict[str, str]:
        """Construct a minimal sanitized environment containing no project secrets."""
        allowed_keys = {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "PATHEXT",
            "TEMP",
            "TMP",
            "PYTHONPATH",
            "PYTHONHOME",
            "COMSPEC",
        }
        clean_env = {
            k: v for k, v in os.environ.items() if k.upper() in allowed_keys
        }
        # Explicitly ensure all sensitive keys are absent
        for sensitive in SENSITIVE_ENV_KEYS:
            clean_env.pop(sensitive, None)

        clean_env["PYTHONIOENCODING"] = "utf-8"
        # Invalidate network proxy configurations to hinder outbound requests
        clean_env["HTTP_PROXY"] = "http://127.0.0.1:0"
        clean_env["HTTPS_PROXY"] = "http://127.0.0.1:0"
        clean_env["NO_PROXY"] = ""
        return clean_env

    def run_test(self, code: str, test_code: str = "") -> Dict[str, Any]:
        """Execute tool validation and assertions inside an isolated sandbox.

        Returns:
            Structured dictionary with keys: success, stdout, stderr, error, duration, violations.
        """
        # 1. Pre-execution static security check
        inspection = self.inspector.inspect_code(code)
        if not inspection.is_safe:
            return {
                "success": False,
                "stdout": "",
                "stderr": "",
                "error": f"Security violation detected: {'; '.join(inspection.violations)}",
                "duration": 0.0,
                "violations": inspection.violations,
            }

        # Check test_code statically as well if provided
        if test_code and test_code.strip():
            test_inspection = self.inspector.inspect_code(test_code)
            if not test_inspection.is_safe:
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "",
                    "error": f"Security violation in test code: {'; '.join(test_inspection.violations)}",
                    "duration": 0.0,
                    "violations": test_inspection.violations,
                }

        # 2. Build isolated test script
        script = code + "\n\n"
        if test_code and test_code.strip():
            script += "# Test execution\n" + test_code + "\n"
        else:
            script += "# Basic compilation check\n"

        # 3. Execute in temporary isolated directory with clean environment
        clean_env = self._build_clean_environment()
        start_time = time.time()

        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                proc = subprocess.run(
                    [sys.executable, "-c", script],
                    cwd=temp_dir,
                    env=clean_env,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                )
                duration = time.time() - start_time
                success = proc.returncode == 0
                return {
                    "success": success,
                    "stdout": proc.stdout.strip(),
                    "stderr": proc.stderr.strip(),
                    "error": "" if success else (proc.stderr.strip() or proc.stdout.strip()),
                    "duration": duration,
                    "violations": [],
                }
            except subprocess.TimeoutExpired:
                duration = time.time() - start_time
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": "Execution timed out",
                    "error": f"Tool test timed out after {self.timeout} seconds",
                    "duration": duration,
                    "violations": ["timeout"],
                }
            except Exception as error:
                duration = time.time() - start_time
                return {
                    "success": False,
                    "stdout": "",
                    "stderr": str(error),
                    "error": str(error),
                    "duration": duration,
                    "violations": [str(error)],
                }
