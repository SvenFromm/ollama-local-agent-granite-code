from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from agent.objective import ObjectiveRequirements
from agent.state import TaskState


@dataclass(frozen=True)
class WorkflowStatus:
    read_complete: bool
    write_complete: bool
    web_complete: bool

    @property
    def all_complete(self) -> bool:
        return self.read_complete and self.write_complete and self.web_complete


class WorkflowPolicy:
    def __init__(self, requirements: ObjectiveRequirements) -> None:
        self.requirements = requirements

    def status(self, state: TaskState) -> WorkflowStatus:
        if not self.requirements.read:
            read_complete = True
        elif self.requirements.web and not self.requirements.source_path:
            read_complete = bool(state.fetched_urls)
        else:
            read_complete = state.read_requirement_complete()
        write_complete = True if not self.requirements.write else bool(state.written_paths)
        web_complete = True if not self.requirements.web else bool(state.fetched_urls)
        return WorkflowStatus(read_complete, write_complete, web_complete)

    def allowed_tools(self, state: TaskState, available: Iterable[str]) -> set[str]:
        available_set = set(available)
        status = self.status(state)
        if self.requirements.web and not status.web_complete:
            return {"curl_internet"} & available_set
        if self.requirements.read and not status.read_complete:
            return {"read_file", "list_files"} & available_set
        if self.requirements.write and not status.write_complete:
            if self.requirements.write_mode == "append":
                return {"append_file"} & available_set
            return {"write_file"} & available_set
        return available_set

    def completion_valid(self, state: TaskState, answer: str) -> tuple[bool, str]:
        status = self.status(state)
        if not status.read_complete:
            return False, "Completion rejected: the required source has not been completely read."
        if not status.write_complete:
            return False, "Completion rejected: a required output file has not been successfully written."
        if not status.web_complete:
            return False, "Completion rejected: required network retrieval has not succeeded."
        if not answer.strip():
            return False, "Completion rejected: answer is empty."
        return True, ""

    def hint(self, state: TaskState) -> str:
        status = self.status(state)
        if self.requirements.web and not status.web_complete:
            return "FETCH required external information with curl_internet. Local files are forbidden."
        if self.requirements.read and not status.read_complete:
            return "READ the required source. Do not write or complete yet."
        if self.requirements.write and not status.write_complete:
            target = self.requirements.output_path or "the requested output file"
            tool = "append_file" if self.requirements.write_mode == "append" else "write_file"
            return f"WRITE phase. Use {tool} and exact target {target!r}. Do not re-read completed source data."
        return "All required operations are complete. Return complete using verified evidence."
