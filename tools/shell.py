from __future__ import annotations
import subprocess
from pathlib import Path
from typing import Any

class ShellTools:
    def __init__(self, workspace: Path, timeout: int = 120) -> None:
        self.workspace = workspace
        self.timeout = timeout

    def run_shell(self, command: str) -> dict[str, Any]:
        try:
            process = subprocess.run(command, shell=True, cwd=self.workspace, text=True,
                                     capture_output=True, timeout=self.timeout)
            return {"ok": process.returncode == 0, "returncode": process.returncode,
                    "stdout": process.stdout[-20000:], "stderr": process.stderr[-20000:]}
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"Command timed out after {self.timeout}s"}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
