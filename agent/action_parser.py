from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable


COMPLETION_ALIASES = {
    "done",
    "finish",
    "finished",
    "final",
    "return",
    "respond",
    "response",
    "answer",
}


@dataclass(frozen=True)
class ParsedAction:
    action: str
    arguments: dict[str, Any]
    answer: str = ""
    verification: str = ""

    @property
    def is_complete(self) -> bool:
        return self.action == "complete"


class GraniteActionParser:
    def __init__(self, tool_names: Iterable[str]) -> None:
        self.tool_names = set(tool_names)

    @staticmethod
    def extract_json(text: str) -> dict[str, Any] | None:
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            value = json.loads(cleaned)
            return value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()
        for index, character in enumerate(cleaned):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(cleaned[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                return value
        return None

    @staticmethod
    def _flatten_arguments(arguments: Any) -> dict[str, Any]:
        if not isinstance(arguments, dict):
            return {}
        result = dict(arguments)
        for _ in range(8):
            if set(result) == {"arguments"} and isinstance(result["arguments"], dict):
                result = dict(result["arguments"])
            else:
                break
        nested = result.pop("arguments", None)
        if isinstance(nested, dict):
            for key, value in nested.items():
                result.setdefault(key, value)
        return result

    def normalize(self, raw: dict[str, Any] | None) -> ParsedAction | None:
        if not isinstance(raw, dict):
            return None

        # Previous tool observations are evidence, not executable actions.
        if "action" not in raw and "tool" in raw and "result" in raw:
            return None
        if "action" not in raw and isinstance(raw.get("controller"), str):
            return None

        action = raw.get("action") or raw.get("tool")
        if not isinstance(action, str):
            return None
        action = action.strip().lower()

        if action == "tool" and isinstance(raw.get("tool"), str):
            action = raw["tool"].strip().lower()
        if action in COMPLETION_ALIASES:
            action = "complete"

        if action == "complete":
            answer = str(
                raw.get("answer")
                or raw.get("result")
                or raw.get("summary")
                or raw.get("content")
                or ""
            )
            verification = str(raw.get("verification") or raw.get("verified") or "")
            return ParsedAction("complete", {}, answer, verification)

        if action not in self.tool_names:
            return None

        arguments = self._flatten_arguments(raw.get("arguments", {}))
        if not arguments:
            excluded = {
                "action",
                "tool",
                "result",
                "verification",
                "answer",
                "description",
                "parameters",
                "properties",
                "required",
                "type",
            }
            arguments = {key: value for key, value in raw.items() if key not in excluded}
        return ParsedAction(action, arguments)

    def parse(self, text: str) -> ParsedAction | None:
        return self.normalize(self.extract_json(text))
