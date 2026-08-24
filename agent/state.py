from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskState:
    objective: str
    phase: str = "planning"
    iteration: int = 0
    tool_calls: int = 0
    completed: bool = False
    final_answer: str = ""
    verification: str = ""
    observations: list[dict[str, Any]] = field(default_factory=list)
    read_paths: list[str] = field(default_factory=list)
    written_paths: list[str] = field(default_factory=list)
    fetched_urls: list[str] = field(default_factory=list)

    @staticmethod
    def _truncate_result(result: dict[str, Any], max_result_chars: int) -> dict[str, Any]:
        stored = dict(result)
        for field_name in ("content", "body", "stdout", "stderr"):
            value = stored.get(field_name)
            if isinstance(value, str) and len(value) > max_result_chars:
                stored[field_name] = value[:max_result_chars] + "\n...[RESULT TRUNCATED BY CONTROLLER]..."
        return stored

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        max_result_chars: int,
    ) -> None:
        stored = self._truncate_result(result, max_result_chars)
        self.observations.append({"tool": tool, "arguments": dict(arguments), "result": stored})
        if not result.get("ok"):
            return
        if tool == "read_file" and isinstance(arguments.get("path"), str):
            path = arguments["path"]
            if path not in self.read_paths:
                self.read_paths.append(path)
        if tool in {"write_file", "append_file"} and isinstance(arguments.get("path"), str):
            path = arguments["path"]
            if path not in self.written_paths:
                self.written_paths.append(path)
        if tool == "curl_internet" and isinstance(arguments.get("url"), str):
            url = arguments["url"]
            if url not in self.fetched_urls:
                self.fetched_urls.append(url)

    def read_requirement_complete(self) -> bool:
        successful_reads = [
            obs for obs in self.observations
            if obs.get("tool") == "read_file"
            and isinstance(obs.get("result"), dict)
            and obs["result"].get("ok") is True
        ]
        if not successful_reads:
            return False
        return not bool(successful_reads[-1]["result"].get("has_more"))

    @staticmethod
    def signature(tool: str, arguments: dict[str, Any]) -> str:
        return json.dumps(
            {"tool": tool, "arguments": arguments},
            sort_keys=True,
            ensure_ascii=False,
            default=str,
            separators=(",", ":"),
        )

    def repeated(self, tool: str, arguments: dict[str, Any], limit: int = 1) -> bool:
        target = self.signature(tool, arguments)
        count = 0
        for observation in self.observations:
            if self.signature(observation.get("tool", ""), observation.get("arguments", {})) == target:
                count += 1
        return count >= limit

    def last_successful_result(self, tool: str) -> dict[str, Any] | None:
        for observation in reversed(self.observations):
            if observation.get("tool") != tool:
                continue
            result = observation.get("result")
            if isinstance(result, dict) and result.get("ok") is True:
                return result
        return None

    def observation_fingerprint(self) -> str:
        payload = json.dumps(self.observations[-6:], sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
