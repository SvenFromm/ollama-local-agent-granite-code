from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent.logging_setup import logger


class MemoryStore:
    def __init__(self, workspace: Path) -> None:
        self.directory = workspace / ".agent"
        self.path = self.directory / "memory.json"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.data = self._load()

    @staticmethod
    def _default() -> dict[str, Any]:
        return {"facts": [], "completed_tasks": [], "files_changed": []}

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            data = self._default()
            self._save(data)
            return data
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            base = self._default()
            if not isinstance(data, dict):
                return base
            for key in base:
                if isinstance(data.get(key), list):
                    base[key] = data[key]
            return base
        except Exception:
            logger.exception("Could not load memory")
            return self._default()

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)

    def save(self) -> None:
        for key, limit in (("facts", 50), ("completed_tasks", 30), ("files_changed", 100)):
            if isinstance(self.data.get(key), list):
                self.data[key] = self.data[key][-limit:]
        self._save(self.data)

    def remember_task(self, objective: str, answer: str) -> None:
        self.data.setdefault("completed_tasks", []).append({"objective": objective, "answer": answer[:2000]})
        self.save()

    def remember_file(self, path: str) -> None:
        self.data.setdefault("files_changed", []).append(path)
        self.save()

    def remember_fact(self, fact: str) -> None:
        self.data.setdefault("facts", []).append(fact[:2000])
        self.save()

    def recent(self, limit: int = 10) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in self.data.items():
            result[key] = value[-limit:] if isinstance(value, list) else value
        return result

    def prompt_context(self, fact_limit: int = 3) -> dict[str, Any]:
        """Return only durable facts to the model.

        Completed task answers and historical file paths are intentionally not
        injected into every prompt. They caused cross-task contamination on
        small Granite models and materially increased prompt-evaluation time.
        """
        facts = self.data.get("facts", [])
        if not isinstance(facts, list):
            facts = []
        return {"facts": facts[-max(0, fact_limit):]}
