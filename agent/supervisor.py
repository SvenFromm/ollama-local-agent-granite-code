from __future__ import annotations

import json
import re
import select
import sys
import uuid
import xml.etree.ElementTree as ET
from typing import Any

from agent.action_parser import GraniteActionParser, ParsedAction
from agent.config import Config
from agent.direct_router import DirectRoute, natural_direct, parse_direct_call
from agent.logging_setup import logger
from agent.memory import MemoryStore
from agent.objective import ObjectiveRequirements, analyze_objective, extract_url
from agent.ollama import OllamaClient
from agent.prompts import build_action_prompt, build_transform_prompt
from agent.security import shell_policy
from agent.state import TaskState
from agent.tool_registry import ToolRegistry
from agent.workflow import WorkflowPolicy


class Supervisor:
    def __init__(
        self,
        config: Config,
        memory: MemoryStore,
        tools: ToolRegistry,
        ollama: OllamaClient,
    ) -> None:
        self.config = config
        self.memory = memory
        self.tools = tools
        self.ollama = ollama
        self.session_id = ""
        self.state: TaskState | None = None
        self.requirements = ObjectiveRequirements()
        self.workflow = WorkflowPolicy(self.requirements)
        self.parser = GraniteActionParser(self.tools.names())
        # Cached Python representation used to build a stable action-prompt prefix.
        self._full_tool_catalog = self.tools.compact_catalog()

    def _reset(self, objective: str) -> None:
        self.session_id = str(uuid.uuid4())
        self.state = TaskState(objective=objective)
        self.requirements = analyze_objective(objective)
        self.workflow = WorkflowPolicy(self.requirements)
        self.parser = GraniteActionParser(self.tools.names())

    def _compact_prompt(self, prompt: str) -> str:
        if len(prompt) <= self.config.max_context_chars:
            return prompt
        head_budget = min(14000, self.config.max_context_chars // 3)
        tail_budget = self.config.max_context_chars - head_budget - 80
        return prompt[:head_budget] + "\n...[CONTEXT COMPACTED BY CONTROLLER]...\n" + prompt[-max(0, tail_budget):]

    def _interrupt(self) -> bool:
        timeout = self.config.interrupt_timeout
        print(
            f"\n[Enter]=continue | stop | state | instruction [auto-continue in {timeout}s]> ",
            end="",
            flush=True,
        )
        try:
            readable, _, _ = select.select([sys.stdin], [], [], timeout)
        except Exception:
            print()
            return True
        if not readable:
            print()
            logger.info("ITERATION INTERRUPT: %ss timeout -> continue", timeout)
            return True
        line = sys.stdin.readline()
        if not line:
            print()
            return True
        command = line.strip()
        if not command:
            return True
        if command.lower() in {"stop", "quit", "exit"}:
            return False
        if command.lower() == "state":
            assert self.state is not None
            print(json.dumps(self.state.__dict__, indent=2, ensure_ascii=False, default=list))
            return self._interrupt()
        assert self.state is not None
        self.state.objective += "\nAdditional user instruction: " + command
        self.requirements = analyze_objective(self.state.objective)
        self.workflow = WorkflowPolicy(self.requirements)
        return True

    @staticmethod
    def _simple_answer(tool: str, result: dict[str, Any]) -> str:
        if tool == "list_files" and isinstance(result.get("files"), list):
            return "\n".join(str(item) for item in result["files"])
        if tool == "read_file" and isinstance(result.get("content"), str):
            return result["content"]
        if tool == "run_shell":
            stdout = result.get("stdout")
            if isinstance(stdout, str) and stdout:
                return stdout.rstrip("\n")
        if tool == "curl_internet" and isinstance(result.get("body"), str):
            return result["body"]
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)

    @staticmethod
    def _print_result(name: str, result: dict[str, Any]) -> None:
        print("\n" + "-" * 72)
        print(f"{name} OUTPUT")
        print("-" * 72)
        field = "content" if name == "read_file" else "body" if name == "curl_internet" else None
        if field and isinstance(result.get(field), str):
            print(result[field])
            metadata = {key: value for key, value in result.items() if key != field}
            print("\n" + json.dumps(metadata, indent=2, ensure_ascii=False, default=str))
        else:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        print("-" * 72)

    def _execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self.state is not None
        if tool == "run_shell":
            decision = shell_policy(str(arguments.get("command", "")), self.state.objective)
            if not decision.allowed:
                result = {
                    "ok": False,
                    "tool": tool,
                    "error": f"Controller blocked command: {decision.reason}",
                    "controller_blocked": True,
                }
                self.state.record(tool, arguments, result, self.config.max_result_chars)
                return result
        if self.state.repeated(tool, arguments, limit=1):
            result = {
                "ok": False,
                "tool": tool,
                "error": "Controller blocked identical non-progressing action.",
                "controller_blocked": True,
            }
            self.state.record(tool, arguments, result, self.config.max_result_chars)
            return result
        if self.state.tool_calls >= self.config.max_tool_calls:
            result = {"ok": False, "tool": tool, "error": "Maximum tool-call limit reached."}
            self.state.record(tool, arguments, result, self.config.max_result_chars)
            return result
        result = self.tools.execute(tool, arguments)
        self.state.tool_calls += 1
        self.state.record(tool, arguments, result, self.config.max_result_chars)
        if result.get("ok") and tool in {"write_file", "append_file"} and isinstance(arguments.get("path"), str):
            self.memory.remember_file(arguments["path"])
        return result

    def _read_source_pages(self, path: str) -> dict[str, Any]:
        assert self.state is not None
        start = 1
        last_result: dict[str, Any] = {"ok": False, "error": "No read attempted"}
        while self.state.tool_calls < self.config.max_tool_calls:
            arguments = {"path": path, "start_line": start, "end_line": start + 799}
            last_result = self._execute("read_file", arguments)
            self._print_result("read_file", last_result)
            if not last_result.get("ok") or not last_result.get("has_more"):
                return last_result
            next_line = last_result.get("next_line")
            if not isinstance(next_line, int) or next_line <= start:
                return {"ok": False, "tool": "read_file", "error": "Invalid read pagination state"}
            start = next_line
        return last_result

    def _verified_source_text(self, tool: str, field: str) -> str:
        assert self.state is not None
        chunks: list[str] = []
        for observation in self.state.observations:
            if observation.get("tool") != tool:
                continue
            result = observation.get("result")
            if not isinstance(result, dict) or result.get("ok") is not True:
                continue
            value = result.get(field)
            if isinstance(value, str) and value:
                if tool == "read_file":
                    value = re.sub(r"(?m)^\s*\d+\s+\|\s?", "", value)
                chunks.append(value)
        return "\n".join(chunks)

    def _verify_write(self, path: str) -> dict[str, Any]:
        assert self.state is not None
        arguments = {"path": path, "start_line": 1, "end_line": 160}
        result = self.tools.execute("read_file", arguments)
        self.state.tool_calls += 1
        self.state.record("read_file", arguments, result, self.config.max_result_chars)
        logger.info("CONTROLLER WRITE VERIFICATION: %s | ok=%s", path, result.get("ok"))
        return result

    def _complete_verified_write(self, path: str) -> str | None:
        assert self.state is not None
        verification = self._verify_write(path)
        if not verification.get("ok"):
            return None
        answer = f"Created {path}" if self.requirements.write_mode != "append" else f"Updated {path}"
        self.state.completed = True
        self.state.final_answer = answer
        self.state.verification = "write succeeded and controller read-back verification succeeded"
        self.memory.remember_task(self.state.objective, answer)
        logger.info("TASK COMPLETE: controller-verified write")
        print(f"\n{answer}\n\nVerification: {self.state.verification}")
        return answer

    def _write_generated_content(self, source_text: str | None = None) -> str | None:
        assert self.state is not None
        path = self.requirements.output_path
        if not path:
            return None
        if self.requirements.literal_content is not None:
            content = self.requirements.literal_content
            logger.info("CONTROLLER LITERAL CONTENT ROUTE: %s", path)
        else:
            bounded_source = None
            if source_text is not None:
                bounded_source = source_text[: self.config.max_transform_input_chars]
                if len(source_text) > len(bounded_source):
                    bounded_source += "\n...[SOURCE TRUNCATED BY CONTROLLER]..."
            prompt = build_transform_prompt(self.state.objective, bounded_source)
            logger.info("CONTROLLER TRANSFORM ROUTE: prompt_chars=%s", len(prompt))
            content = self.ollama.generate_text(prompt, self.config.transform_num_predict).strip()
            if not content:
                logger.warning("TRANSFORMATION RETURNED EMPTY CONTENT")
                return None
        tool = "append_file" if self.requirements.write_mode == "append" else "write_file"
        result = self._execute(tool, {"path": path, "content": content})
        self._print_result(tool, result)
        if result.get("ok"):
            return self._complete_verified_write(path)
        return None

    @staticmethod
    def _rss_headlines(body: str, limit: int = 10) -> str | None:
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            return None
        items = root.findall(".//item")
        if not items:
            return None
        lines: list[str] = []
        for index, item in enumerate(items[:limit], start=1):
            title = (item.findtext("title") or "").strip()
            description = re.sub(r"<[^>]+>", "", (item.findtext("description") or "")).strip()
            if not title:
                continue
            lines.append(f"{index}. {title}")
            if description and description != title:
                lines.append(f"   {description}")
        return "\n".join(lines) if lines else None

    def _fetch_web_source(self) -> dict[str, Any]:
        assert self.state is not None
        explicit_url = extract_url(self.state.objective)
        url = explicit_url or self.config.default_news_url
        logger.info("CONTROLLER WEB ROUTE: %s", url)
        result = self._execute("curl_internet", {"url": url})
        self._print_result("curl_internet", result)
        return result

    def _run_direct(self, route: DirectRoute) -> str:
        result = self._execute(route.tool, route.arguments)
        self._print_result(route.tool, result)
        if result.get("ok") and route.complete_after_success:
            answer = self._simple_answer(route.tool, result)
            assert self.state is not None
            self.state.completed = True
            self.state.final_answer = answer
            self.state.verification = f"{route.tool} returned ok=true"
            self.memory.remember_task(self.state.objective, answer[:2000])
            logger.info("TASK COMPLETE: direct route")
            return answer
        return self._autonomous_loop(initial_hint=f"Direct action failed: {result.get('error', 'unknown error')}")

    def _model_action(self, hint: str) -> ParsedAction | None:
        assert self.state is not None
        allowed = self.workflow.allowed_tools(self.state, self.tools.names())
        prompt = build_action_prompt(
            self.state,
            self._full_tool_catalog,
            allowed,
            self.memory.prompt_context(3),
            self.workflow.hint(self.state) + (f" Additional instruction: {hint}" if hint else ""),
        )
        logger.info("ACTION PROMPT chars=%s allowed=%s", len(prompt), sorted(allowed))
        raw_text = self.ollama.generate(self._compact_prompt(prompt), self.config.action_num_predict)
        logger.debug("RAW MODEL OUTPUT: %s", raw_text)
        return self.parser.parse(raw_text)

    def _autonomous_loop(self, initial_hint: str = "") -> str:
        assert self.state is not None
        hint = initial_hint
        last_signature: str | None = None
        nonprogress = 0

        for iteration in range(1, self.config.max_iterations + 1):
            self.state.iteration = iteration
            self.state.phase = "planning" if iteration == 1 else "replanning"
            allowed = self.workflow.allowed_tools(self.state, self.tools.names())
            logger.info("-" * 72)
            logger.info(
                "ITERATION %s/%s | PHASE=%s | TOOLS=%s/%s | ALLOWED=%s",
                iteration,
                self.config.max_iterations,
                self.state.phase,
                self.state.tool_calls,
                self.config.max_tool_calls,
                sorted(allowed),
            )
            action = self._model_action(hint)
            if action is None:
                nonprogress += 1
                hint = "Previous response was invalid. Choose one allowed action."
            else:
                signature = json.dumps(action.__dict__, sort_keys=True, default=str, ensure_ascii=False)
                if signature == last_signature:
                    nonprogress += 1
                    hint = "Repeated action blocked. Choose a different action that advances the workflow."
                    logger.warning("MODEL LOOP DETECTED: %s", signature)
                else:
                    last_signature = signature
                    if action.is_complete:
                        valid, reason = self.workflow.completion_valid(self.state, action.answer)
                        if valid:
                            self.state.completed = True
                            self.state.final_answer = action.answer
                            self.state.verification = action.verification
                            self.memory.remember_task(self.state.objective, action.answer)
                            logger.info("TASK COMPLETE")
                            print("\n" + action.answer)
                            return action.answer
                        nonprogress += 1
                        hint = reason
                    elif action.action not in allowed:
                        nonprogress += 1
                        hint = f"Tool {action.action!r} is forbidden. Choose only from {sorted(allowed)}."
                        logger.warning("TOOL BLOCKED BY WORKFLOW: %s", action.action)
                    else:
                        arguments = dict(action.arguments)
                        if action.action in {"write_file", "append_file"} and self.requirements.output_path:
                            arguments["path"] = self.requirements.output_path
                        result = self._execute(action.action, arguments)
                        self._print_result(action.action, result)
                        if result.get("ok"):
                            nonprogress = 0
                            if action.action in {"write_file", "append_file"}:
                                path = str(arguments.get("path", ""))
                                if path:
                                    completed = self._complete_verified_write(path)
                                    if completed:
                                        return completed
                            hint = "Previous operation succeeded. Continue with the next required phase."
                        else:
                            nonprogress += 1
                            hint = f"Previous operation failed: {result.get('error', 'unknown error')}"

            if nonprogress >= self.config.max_nonprogress_iterations:
                logger.warning("TASK ABORTED AFTER %s NON-PROGRESS ITERATIONS", nonprogress)
                break
            if not self._interrupt():
                break

        logger.warning("TASK STOPPED WITHOUT VERIFIED COMPLETION")
        message = "Task stopped without verified completion."
        print("\n" + message)
        return message

    def run(self, objective: str) -> str:
        self._reset(objective.strip())
        assert self.state is not None
        logger.info("=" * 72)
        logger.info("GRANITE CODE AGENT TASK | session=%s", self.session_id)
        logger.info("Objective: %s", self.state.objective)
        logger.info("Workspace: %s", self.config.workspace)
        logger.info("Requirements: %s", self.requirements)
        logger.info("=" * 72)

        direct = parse_direct_call(self.state.objective) or natural_direct(self.state.objective)
        if direct is not None:
            logger.info("DIRECT ROUTER: %s %s", direct.tool, json.dumps(direct.arguments, ensure_ascii=False))
            return self._run_direct(direct)

        # Literal writes are fully deterministic: no inference is needed.
        if self.requirements.write and self.requirements.output_path and self.requirements.literal_content is not None and not self.requirements.read and not self.requirements.web:
            completed = self._write_generated_content()
            return completed or self._autonomous_loop("Deterministic literal write failed.")

        # Mutation-only tasks with a known target use Granite only for content
        # generation; Python owns the exact tool and exact path.
        if self.requirements.write and self.requirements.output_path and not self.requirements.read and not self.requirements.web:
            completed = self._write_generated_content()
            return completed or self._autonomous_loop("Content generation/write failed.")

        # Compound local transformations: Python reads; Granite transforms;
        # Python writes and verifies. Granite never decides tool sequencing.
        if self.requirements.read and self.requirements.source_path:
            logger.info("CONTROLLER SOURCE ROUTE: %s", self.requirements.source_path)
            result = self._read_source_pages(self.requirements.source_path)
            if not result.get("ok"):
                return self._autonomous_loop(initial_hint=f"Controller source read failed: {result.get('error')}")
            if self.requirements.write and self.requirements.output_path:
                source_text = self._verified_source_text("read_file", "content")
                completed = self._write_generated_content(source_text)
                return completed or self._autonomous_loop("Transform/write failed.")
            return self._verified_source_text("read_file", "content") or self._simple_answer("read_file", result)

        # Web retrieval is deterministic when the task supplies a URL or asks
        # for news. This avoids asking Granite which tool to call.
        if self.requirements.web:
            result = self._fetch_web_source()
            if not result.get("ok"):
                return self._autonomous_loop(initial_hint=f"Controller web fetch failed: {result.get('error')}")
            body = str(result.get("body", ""))
            if self.requirements.write and self.requirements.output_path:
                completed = self._write_generated_content(body)
                return completed or self._autonomous_loop("Web transform/write failed.")
            if re.search(r"\b(news|latest|recent)\b", self.state.objective, flags=re.I):
                headlines = self._rss_headlines(body)
                if headlines:
                    self.state.completed = True
                    self.state.final_answer = headlines
                    self.state.verification = f"Fetched {result.get('url')} successfully"
                    self.memory.remember_task(self.state.objective, headlines[:2000])
                    logger.info("TASK COMPLETE: deterministic RSS extraction")
                    print("\n" + headlines)
                    return headlines
            return body

        return self._autonomous_loop()
