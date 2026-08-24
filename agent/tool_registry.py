from __future__ import annotations

import inspect
import json
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from agent.logging_setup import logger


@dataclass(frozen=True)
class ToolSpec:
    name: str
    function: Callable[..., Any]
    category: str
    description: str


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, name: str, function: Callable[..., Any], category: str, description: str) -> None:
        self._tools[name] = ToolSpec(name, function, category, description)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def _arguments(self, spec: ToolSpec) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for parameter in inspect.signature(spec.function).parameters.values():
            if parameter.name == "self":
                continue
            result.append(
                {
                    "name": parameter.name,
                    "required": parameter.default is inspect.Parameter.empty,
                    "default": None if parameter.default is inspect.Parameter.empty else parameter.default,
                    "annotation": str(parameter.annotation),
                }
            )
        return result

    def compact_catalog(self, allowed: Iterable[str] | None = None) -> list[dict[str, Any]]:
        allowed_set = set(allowed) if allowed is not None else set(self._tools)
        return [
            {
                "name": spec.name,
                "category": spec.category,
                "description": spec.description,
                "arguments": self._arguments(spec),
            }
            for name in sorted(allowed_set)
            if (spec := self._tools.get(name)) is not None
        ]

    def catalog_text(self) -> str:
        categories: dict[str, list[ToolSpec]] = {}
        for spec in self._tools.values():
            categories.setdefault(spec.category.upper(), []).append(spec)
        lines = ["", "=" * 72, " AVAILABLE TOOLS", "=" * 72]
        for category in sorted(categories):
            lines += ["", category]
            for spec in sorted(categories[category], key=lambda item: item.name):
                params = []
                for arg in self._arguments(spec):
                    suffix = "" if arg["required"] else f"={arg['default']!r}"
                    params.append(f"{arg['name']}{suffix}")
                lines.append(f"  {spec.name}({', '.join(params)})")
                lines.append(f"    {spec.description}")
        lines += ["", "Use: tool <name> for details", "=" * 72]
        return "\n".join(lines)

    def tool_text(self, name: str) -> str:
        spec = self._tools.get(name)
        if spec is None:
            return f"Unknown tool: {name}"
        lines = [spec.name, "-" * 72, spec.description, "", f"Category: {spec.category}", "Arguments:"]
        for arg in self._arguments(spec):
            requirement = "required" if arg["required"] else f"optional, default={arg['default']!r}"
            lines.append(f"  {arg['name']}: {requirement} ({arg['annotation']})")
        return "\n".join(lines)

    def _sanitize_arguments(self, spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        parameters = inspect.signature(spec.function).parameters
        allowed = {name for name in parameters if name != "self"}
        return {key: value for key, value in arguments.items() if key in allowed}

    def execute(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        spec = self._tools.get(name)
        if spec is None:
            return {"ok": False, "tool": name, "error": f"Unknown tool: {name}"}
        arguments = dict(arguments or {})
        for _ in range(8):
            if set(arguments) == {"arguments"} and isinstance(arguments["arguments"], dict):
                arguments = dict(arguments["arguments"])
            else:
                break
        arguments = self._sanitize_arguments(spec, arguments)
        logger.info("TOOL CALL: %s %s", name, json.dumps(arguments, ensure_ascii=False, default=str))
        try:
            result = spec.function(**arguments)
            if not isinstance(result, dict):
                result = {"ok": True, "result": result}
            result.setdefault("tool", name)
        except Exception as exc:
            logger.exception("Tool failure: %s", name)
            result = {"ok": False, "tool": name, "error": f"{type(exc).__name__}: {exc}"}
        logger.info("TOOL RESULT: %s | ok=%s", name, result.get("ok"))
        return result
