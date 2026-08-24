from __future__ import annotations

import json
from typing import Any, Iterable

from agent.state import TaskState


# This prefix is intentionally stable across tasks. Ollama/llama.cpp can reuse
# a much larger prompt prefix when the objective and state are appended later.
ACTION_STATIC_PREFIX = """
You are the action-selection component of a local autonomous coding agent using IBM Granite Code.
Python owns workflow sequencing, execution, safety, verification, and completion.
Return exactly ONE JSON object. No Markdown. No prose outside JSON.

Tool action:
{"action":"TOOL_NAME","arguments":{"arg":"value"}}
Completion:
{"action":"complete","answer":"user-facing result","verification":"verified evidence"}

Rules:
- Use only ALLOWED TOOLS.
- Never invent results or verification.
- Never echo observations, previous errors, paths, or memory as a new action.
- Never nest arguments inside arguments.
- Never repeat a completed/non-progressing action.
- Current/external information uses curl_internet, never local files.
- If Python says WRITE, use the required write tool and exact target path.
- Prefer one action that advances the workflow.
""".strip()


def static_tool_schema(tool_catalog: Iterable[dict[str, Any]]) -> str:
    compact: list[dict[str, Any]] = []
    for item in tool_catalog:
        args = []
        for arg in item.get("arguments", []):
            args.append({"name": arg.get("name"), "required": arg.get("required", False)})
        compact.append({"name": item.get("name"), "arguments": args})
    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _compact_observations(state: TaskState) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in state.observations[-3:]:
        raw_result = item.get("result", {})
        meta: dict[str, Any] = {}
        if isinstance(raw_result, dict):
            for key in ("ok", "tool", "path", "url", "status", "has_more", "next_line", "error", "controller_blocked"):
                if key in raw_result:
                    meta[key] = raw_result[key]
        result.append({"tool": item.get("tool"), "arguments": item.get("arguments", {}), "result": meta})
    return result


def build_action_prompt(
    state: TaskState,
    full_tool_catalog: Any,
    allowed_tools: Iterable[str],
    memory: Any,
    controller_hint: str,
) -> str:
    # Keep everything before DYNAMIC STATE identical across tasks whenever the
    # registered tool set is unchanged; this maximizes llama.cpp prompt-cache reuse.
    stable = ACTION_STATIC_PREFIX + "\n\nREGISTERED TOOL SCHEMA:\n" + static_tool_schema(full_tool_catalog)
    dynamic = [
        "",
        "DYNAMIC STATE:",
        "ALLOWED TOOLS: " + json.dumps(sorted(allowed_tools), separators=(",", ":")),
        "OBJECTIVE: " + state.objective,
        "PHASE: " + state.phase,
        "CONTROLLER: " + controller_hint,
        "RECENT OBSERVATION METADATA: " + json.dumps(_compact_observations(state), ensure_ascii=False, separators=(",", ":")),
        "DURABLE MEMORY: " + json.dumps(memory, ensure_ascii=False, separators=(",", ":")),
        "Return one JSON action now.",
    ]
    return stable + "\n".join(dynamic)


def build_transform_prompt(objective: str, source_text: str | None = None) -> str:
    instruction = (
        "You are IBM Granite Code acting only as a text/code transformation engine.\n"
        "Return ONLY the requested output content. Do not return JSON, tool calls, Markdown fences, file paths, controller messages, or explanations unless the objective itself asks for them.\n"
        "Do not copy controller/error text from prior tasks.\n\n"
        f"OBJECTIVE:\n{objective}\n"
    )
    if source_text is not None:
        instruction += "\nVERIFIED SOURCE CONTENT:\n---BEGIN SOURCE---\n" + source_text + "\n---END SOURCE---\n"
    instruction += "\nOUTPUT CONTENT:\n"
    return instruction
