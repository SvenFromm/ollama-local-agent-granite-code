from __future__ import annotations

from pathlib import Path
from typing import Any


class FileTools:
    def __init__(self, workspace: Path) -> None:
        self.workspace = workspace.resolve()

    def safe_path(self, path: str) -> Path:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.workspace / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.workspace)
        except ValueError as exc:
            raise PermissionError(f"Path outside workspace: {resolved}") from exc
        return resolved

    def list_files(self, path: str = ".", recursive: bool = False) -> dict[str, Any]:
        target = self.safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"Path does not exist: {path}"}
        if not target.is_dir():
            return {"ok": False, "error": f"Not a directory: {path}"}
        items = target.rglob("*") if recursive else target.iterdir()
        files: list[str] = []
        for item in items:
            try:
                relative = item.resolve().relative_to(self.workspace)
            except (ValueError, OSError):
                continue
            text = str(relative)
            if item.is_dir():
                text += "/"
            files.append(text)
        files.sort()
        return {"ok": True, "path": path, "count": len(files), "files": files[:2000]}

    def read_file(self, path: str, start_line: int = 1, end_line: int = 800) -> dict[str, Any]:
        target = self.safe_path(path)
        if not target.exists():
            return {"ok": False, "error": f"File does not exist: {path}"}
        if not target.is_file():
            return {"ok": False, "error": f"Not a file: {path}"}
        content = target.read_text(encoding="utf-8", errors="replace")
        lines = content.splitlines()
        if start_line < 1:
            return {"ok": False, "error": "start_line must be >= 1"}
        if end_line < start_line:
            return {"ok": False, "error": "end_line must be >= start_line"}
        selected = lines[start_line - 1 : end_line]
        actual_end = min(end_line, len(lines))
        numbered = "\n".join(
            f"{number:6d} | {line}"
            for number, line in enumerate(selected, start=start_line)
        )
        return {
            "ok": True,
            "path": path,
            "total_lines": len(lines),
            "start_line": start_line,
            "end_line": actual_end,
            "has_more": actual_end < len(lines),
            "next_line": actual_end + 1 if actual_end < len(lines) else None,
            "content": numbered,
        }

    def write_file(self, path: str, content: str) -> dict[str, Any]:
        target = self.safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"ok": True, "path": path, "bytes": len(content.encode("utf-8"))}

    def append_file(self, path: str, content: str) -> dict[str, Any]:
        target = self.safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(content)
        return {"ok": True, "path": path, "bytes_appended": len(content.encode("utf-8"))}
