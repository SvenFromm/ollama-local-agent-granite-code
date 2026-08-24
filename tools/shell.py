from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


class ShellTools:
    def __init__(self, workspace: Path, timeout: int = 120, max_output_chars: int = 20000) -> None:
        self.workspace = workspace.resolve()
        self.timeout = timeout
        self.max_output_chars = max_output_chars

    def _limit(self, value: str) -> str:
        if len(value) <= self.max_output_chars:
            return value
        return value[: self.max_output_chars] + "\n...[SHELL OUTPUT TRUNCATED]..."

    def run_shell(self, command: str) -> dict[str, Any]:
        if not isinstance(command, str) or not command.strip():
            return {"ok": False, "error": "command must be a non-empty string"}
        try:
            process = subprocess.run(
                ["/bin/bash", "-lc", command],
                cwd=self.workspace,
                text=True,
                capture_output=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = self._limit(exc.stdout or "") if isinstance(exc.stdout, str) else ""
            stderr = self._limit(exc.stderr or "") if isinstance(exc.stderr, str) else ""
            return {
                "ok": False,
                "error": f"Command timed out after {self.timeout}s",
                "stdout": stdout,
                "stderr": stderr,
            }
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        return {
            "ok": process.returncode == 0,
            "returncode": process.returncode,
            "stdout": self._limit(process.stdout),
            "stderr": self._limit(process.stderr),
        }
