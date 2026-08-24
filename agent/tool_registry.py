from __future__ import annotations
import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable
from agent.logging_setup import logger

@dataclass
class ToolSpec:
    name: str
    function: Callable[..., dict[str, Any]]
    category: str
    description: str

class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, function: Callable[..., dict[str, Any]], category: str, description: str) -> None:
        self._tools[name] = ToolSpec(name, function, category, description)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self._tools:
            return {"ok": False, "tool": name, "error": f"Unknown tool: {name}"}
        arguments = arguments or {}
        while set(arguments) == {"arguments"} and isinstance(arguments.get("arguments"), dict):
            arguments = arguments["arguments"]
        logger.info("TOOL CALL: %s %s", name, json.dumps(arguments, ensure_ascii=False, default=str))
        try:
            result = self._tools[name].function(**arguments)
            if not isinstance(result, dict):
                result = {"ok": True, "result": result}
            result.setdefault("tool", name)
        except Exception as exc:
            logger.exception("Tool failure: %s", name)
            result = {"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}
        logger.info("TOOL RESULT: %s | ok=%s", name, result.get("ok"))
        return result

    def compact_catalog(self, allowed: set[str] | None = None) -> str:
        lines = []
        for name in self.names():
            if allowed is not None and name not in allowed:
                continue
            spec = self._tools[name]
            sig = inspect.signature(spec.function)
            lines.append(f"- {name}{sig}: {spec.description}")
        return "\n".join(lines)

    def catalog_text(self) -> str:
        groups: dict[str, list[ToolSpec]] = {}
        for spec in self._tools.values():
            groups.setdefault(spec.category, []).append(spec)
        width = 72
        lines = ["=" * width, " AVAILABLE TOOLS", "=" * width]
        for category in sorted(groups):
            lines += ["", category.upper()]
            for spec in sorted(groups[category], key=lambda x: x.name):
                sig = inspect.signature(spec.function)
                lines.append(f"  {spec.name}{sig}")
                lines.append(f"      {spec.description}")
        lines += ["", "Use a tool by describing the task normally; direct commands such as", "read_file(path) and list_files(.) are routed without an LLM call.", "=" * width]
        return "\n".join(lines)
