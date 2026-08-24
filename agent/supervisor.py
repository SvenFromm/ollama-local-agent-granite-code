# agent/supervisor.py

from __future__ import annotations

import ast
import json
import re
import select
import sys
import uuid

from pathlib import Path
from typing import Any

from agent.config import Config
from agent.logging_setup import logger
from agent.memory import MemoryStore
from agent.ollama import OllamaClient
from agent.prompts import build_prompt
from agent.state import TaskState
from agent.tool_registry import ToolRegistry


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

        self.session_id = str(uuid.uuid4())
        self.state: TaskState | None = None

        self.required_read = False
        self.required_write = False
        self.required_web = False

        self.target_write_path: str | None = None

    # ================================================================
    # MODEL RESPONSE PARSING
    # ================================================================

    @staticmethod
    def _extract_json(
        text: str,
    ) -> dict[str, Any] | None:

        text = text.strip()

        text = re.sub(
            r"^```(?:json)?\s*",
            "",
            text,
            flags=re.I,
        )

        text = re.sub(
            r"\s*```$",
            "",
            text,
        )

        try:
            value = json.loads(text)

            if isinstance(value, dict):
                return value

        except json.JSONDecodeError:
            pass

        decoder = json.JSONDecoder()

        for index, character in enumerate(text):

            if character != "{":
                continue

            try:
                value, _ = decoder.raw_decode(
                    text[index:]
                )

                if isinstance(value, dict):
                    return value

            except json.JSONDecodeError:
                continue

        return None

    def _normalize(
        self,
        raw: dict[str, Any],
    ) -> dict[str, Any] | None:

        # Granite sometimes echoes observations.
        if (
            "action" not in raw
            and "tool" in raw
            and "result" in raw
        ):
            return None

        action = (
            raw.get("action")
            or raw.get("tool")
        )

        if not isinstance(action, str):
            return None

        action = action.strip().lower()

        aliases = {
            "done": "complete",
            "finish": "complete",
            "finished": "complete",
            "final": "complete",
            "return": "complete",
            "respond": "complete",
            "response": "complete",
        }

        action = aliases.get(
            action,
            action,
        )

        if (
            action == "tool"
            and isinstance(raw.get("tool"), str)
        ):
            action = (
                raw["tool"]
                .strip()
                .lower()
            )

        if action == "complete":

            return {
                "action": "complete",
                "answer": str(
                    raw.get("answer")
                    or raw.get("result")
                    or raw.get("summary")
                    or raw.get("content")
                    or ""
                ),
                "verification": str(
                    raw.get("verification")
                    or ""
                ),
            }

        if action not in self.tools.names():
            return None

        arguments = raw.get(
            "arguments",
            {},
        )

        if not isinstance(arguments, dict):
            arguments = {}

        # Granite frequently nests arguments repeatedly.
        for _ in range(8):

            if (
                set(arguments) == {"arguments"}
                and isinstance(
                    arguments["arguments"],
                    dict,
                )
            ):
                arguments = arguments["arguments"]

            else:
                break

        if not arguments:

            arguments = {
                key: value
                for key, value in raw.items()
                if key
                not in {
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
            }

        return {
            "action": action,
            "arguments": arguments,
        }

    # ================================================================
    # OBJECTIVE ANALYSIS
    # ================================================================

    def _analyse_objective(
        self,
        objective: str,
    ) -> None:

        lower = objective.lower()

        self.required_read = any(
            token in lower
            for token in (
                "read ",
                "summar",
                "review",
                "inspect",
                "analy",
                "analyse",
                "analyze",
            )
        )

        self.required_write = any(
            token in lower
            for token in (
                "write",
                "save",
                "create file",
                "new file",
                "modify",
                "update",
                "edit",
                "fix",
                "change",
            )
        )

        self.required_web = any(
            token in lower
            for token in (
                "internet",
                "website",
                "http://",
                "https://",
                "online",
                "web ",
                "latest",
                "current news",
            )
        )

        self.target_write_path = (
            self._extract_output_path(
                objective
            )
        )

        logger.info(
            "OBJECTIVE ANALYSIS: "
            "read=%s write=%s web=%s target=%s",
            self.required_read,
            self.required_write,
            self.required_web,
            self.target_write_path,
        )

    @staticmethod
    def _extract_output_path(
        objective: str,
    ) -> str | None:

        patterns = (
            r"\b(?:new|output)\s+file\s+[\"']?([^\s\"']+\.[A-Za-z0-9]+)[\"']?",
            r"\b(?:write|save|create)\s+(?:to\s+)?(?:file\s+)?[\"']?([^\s\"']+\.[A-Za-z0-9]+)[\"']?",
            r"\bin\s+(?:a\s+)?(?:new\s+)?file\s+[\"']?([^\s\"']+\.[A-Za-z0-9]+)[\"']?",
            r"\bto\s+(?:a\s+)?(?:new\s+)?file\s+[\"']?([^\s\"']+\.[A-Za-z0-9]+)[\"']?",
        )

        for pattern in patterns:

            match = re.search(
                pattern,
                objective,
                flags=re.I,
            )

            if match:

                value = (
                    match.group(1)
                    .strip()
                    .rstrip(".,;:")
                )

                if value:
                    return value

        return None

    # ================================================================
    # TASK STATE
    # ================================================================

    def _has_successful_tool(
        self,
        name: str,
    ) -> bool:

        assert self.state is not None

        for observation in self.state.observations:

            if observation.get("tool") != name:
                continue

            result = observation.get(
                "result",
                {},
            )

            if (
                isinstance(result, dict)
                and result.get("ok") is True
            ):
                return True

        return False

    def _successful_results(
        self,
        name: str,
    ) -> list[dict[str, Any]]:

        assert self.state is not None

        results: list[dict[str, Any]] = []

        for observation in self.state.observations:

            if observation.get("tool") != name:
                continue

            result = observation.get(
                "result",
                {},
            )

            if (
                isinstance(result, dict)
                and result.get("ok") is True
            ):
                results.append(result)

        return results

    def _read_complete(
        self,
    ) -> bool:

        if not self.required_read:
            return True

        assert self.state is not None

        if not self.state.read_paths:
            return False

        # If the most recent successful read says more content exists,
        # reading is not yet complete.
        for observation in reversed(
            self.state.observations
        ):

            if (
                observation.get("tool")
                != "read_file"
            ):
                continue

            result = observation.get(
                "result",
                {},
            )

            if not isinstance(
                result,
                dict,
            ):
                continue

            if not result.get("ok"):
                continue

            return not bool(
                result.get("has_more")
            )

        return False

    def _write_complete(
        self,
    ) -> bool:

        if not self.required_write:
            return True

        assert self.state is not None

        return bool(
            self.state.written_paths
        )

    def _web_complete(
        self,
    ) -> bool:

        if not self.required_web:
            return True

        assert self.state is not None

        return bool(
            self.state.fetched_urls
        )

    def _workflow_status(
        self,
    ) -> str:

        read_status = (
            "DONE"
            if self._read_complete()
            else "MISSING"
        )

        write_status = (
            "DONE"
            if self._write_complete()
            else "MISSING"
        )

        web_status = (
            "DONE"
            if self._web_complete()
            else "MISSING"
        )

        return (
            "CONTROLLER WORKFLOW STATUS\n"
            f"READ:  {read_status}\n"
            f"WRITE: {write_status}\n"
            f"WEB:   {web_status}\n"
        )

    # ================================================================
    # DIRECT ROUTING
    # ================================================================

    @staticmethod
    def _parse_direct_call(
        task: str,
    ) -> tuple[
        str,
        dict[str, Any],
    ] | None:

        match = re.fullmatch(
            r"\s*"
            r"(list_files|read_file)"
            r"\s*\((.*)\)\s*",
            task,
            flags=re.S,
        )

        if not match:
            return None

        name, raw_args = match.groups()

        raw_args = raw_args.strip()

        if not raw_args:
            return name, {}

        try:

            expression = ast.parse(
                f"f({raw_args})",
                mode="eval",
            ).body

            if not isinstance(
                expression,
                ast.Call,
            ):
                return None

            arguments: dict[str, Any] = {}

            if expression.args:

                arguments["path"] = (
                    ast.literal_eval(
                        expression.args[0]
                    )
                )

            for keyword in expression.keywords:

                if keyword.arg:

                    arguments[
                        keyword.arg
                    ] = ast.literal_eval(
                        keyword.value
                    )

            return name, arguments

        except Exception:

            return (
                name,
                {
                    "path": (
                        raw_args
                        .strip()
                        .strip("\"'")
                    )
                },
            )

    @staticmethod
    def _natural_direct(
        task: str,
    ) -> tuple[
        str,
        dict[str, Any],
        bool,
    ] | None:

        text = re.sub(
            r"\s+",
            " ",
            task.strip(),
        )

        lower = text.lower()

        # Directory listing.
        if (
            re.fullmatch(
                r"(?:list|show)"
                r"(?: the)? "
                r"(?:files|contents|content|directory contents|files and directories)"
                r"(?: (?:of|in) (?:the )?"
                r"(?:current |working |current working )?"
                r"(?:folder|directory))?",
                lower,
            )
            or lower
            in {
                "list current folder",
                "list current directory",
                "list files of current folder",
                "list files in current folder",
                "list files of current directory",
                "list files in current directory",
            }
        ):

            return (
                "list_files",
                {
                    "path": ".",
                    "recursive": False,
                },
                True,
            )

        # Explicit shell execution.
        shell_match = re.fullmatch(
            r"(?:execute|run)"
            r"(?: (?:the )?"
            r"(?:script|command|shell command))?"
            r"\s+(.+)",
            text,
            flags=re.I,
        )

        if shell_match:

            command = (
                shell_match
                .group(1)
                .strip()
            )

            if command:

                return (
                    "run_shell",
                    {
                        "command": command
                    },
                    True,
                )

        # Simple file read.
        read_match = re.fullmatch(
            r"(?:read|show|display)"
            r"(?: file)?\s+(.+)",
            text,
            flags=re.I,
        )

        if (
            read_match
            and not re.search(
                r"\b("
                r"summar|analys|review|then|"
                r"write|save|create|modify|"
                r"update|edit|fix|change"
                r")\w*\b",
                lower,
            )
        ):

            path = (
                read_match
                .group(1)
                .strip()
                .strip("\"'")
            )

            return (
                "read_file",
                {
                    "path": path
                },
                True,
            )

        return None

    # ================================================================
    # SHELL POLICY
    # ================================================================

    @staticmethod
    def _shell_allowed(
        command: str,
        objective: str,
    ) -> tuple[
        bool,
        str,
    ]:

        lowered = command.lower()

        dangerous = (
            "sudo ",
            "apt ",
            "apt-get ",
            "dnf ",
            "yum ",
            "pacman ",
            "mkfs",
            "dd if=",
            "shutdown",
            "reboot",
            "poweroff",
            "rm -rf /",
        )

        if any(
            token in lowered
            for token in dangerous
        ):

            objective_lower = (
                objective.lower()
            )

            if not any(
                token.strip()
                in objective_lower
                for token in dangerous
            ):

                return (
                    False,
                    "privileged/package/"
                    "destructive command was "
                    "not explicitly requested",
                )

        return True, ""

    # ================================================================
    # PHASE-SPECIFIC TOOL POLICY
    # ================================================================

    def _allowed_tools(
        self,
    ) -> set[str]:

        assert self.state is not None

        available = set(
            self.tools.names()
        )

        # Network task has not yet fetched data.
        if (
            self.required_web
            and not self._web_complete()
        ):
            return (
                {"curl_internet"}
                & available
            )

        # File-reading stage.
        if (
            self.required_read
            and not self._read_complete()
        ):
            return (
                {
                    "read_file",
                    "list_files",
                }
                & available
            )

        # IMPORTANT:
        # Once reading is complete, read_file is deliberately removed.
        # Granite 3B cannot get stuck repeatedly reading the same source.
        if (
            self.required_write
            and not self._write_complete()
        ):
            return (
                {
                    "write_file",
                    "append_file",
                }
                & available
            )

        # Verification stage.
        if (
            self.required_write
            and self._write_complete()
        ):
            return (
                {"read_file"}
                & available
            )

        return available

    # ================================================================
    # COMPLETION
    # ================================================================

    def _completion_valid(
        self,
        answer: str,
    ) -> tuple[
        bool,
        str,
    ]:

        if (
            self.required_read
            and not self._read_complete()
        ):

            return (
                False,
                "Completion rejected: "
                "the required source file "
                "has not been completely read.",
            )

        if (
            self.required_write
            and not self._write_complete()
        ):

            return (
                False,
                "Completion rejected: "
                "the objective requires writing "
                "an output file but no successful "
                "write has occurred.",
            )

        if (
            self.required_web
            and not self._web_complete()
        ):

            return (
                False,
                "Completion rejected: "
                "the objective requires network "
                "retrieval but no successful "
                "network request occurred.",
            )

        if not answer.strip():

            return (
                False,
                "Completion rejected: "
                "answer is empty.",
            )

        return True, ""

    # ================================================================
    # RESULT OUTPUT
    # ================================================================

    @staticmethod
    def _simple_answer(
        tool: str,
        result: dict[str, Any],
    ) -> str:

        if tool == "list_files":

            files = result.get(
                "files",
                [],
            )

            if isinstance(files, list):

                return "\n".join(
                    str(item)
                    for item in files
                )

        if (
            tool == "read_file"
            and isinstance(
                result.get("content"),
                str,
            )
        ):
            return result["content"]

        if (
            tool == "curl_internet"
            and isinstance(
                result.get("body"),
                str,
            )
        ):
            return result["body"]

        return json.dumps(
            result,
            indent=2,
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _print_result(
        name: str,
        result: dict[str, Any],
    ) -> None:

        print(
            "\n"
            + "-" * 72
        )

        print(
            f"{name} OUTPUT"
        )

        print(
            "-" * 72
        )

        field = None

        if name == "read_file":
            field = "content"

        elif name == "curl_internet":
            field = "body"

        if (
            field
            and isinstance(
                result.get(field),
                str,
            )
        ):

            print(
                result[field]
            )

            metadata = {
                key: value
                for key, value
                in result.items()
                if key != field
            }

            print()

            print(
                json.dumps(
                    metadata,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

        else:

            print(
                json.dumps(
                    result,
                    indent=2,
                    ensure_ascii=False,
                    default=str,
                )
            )

        print(
            "-" * 72
        )

    # ================================================================
    # INTERRUPT
    # ================================================================

    def _interrupt(
        self,
    ) -> bool:

        timeout = (
            self.config.interrupt_timeout
        )

        print(
            "\n"
            "[Enter]=continue | "
            "stop | state | instruction "
            f"[auto-continue in {timeout}s]> ",
            end="",
            flush=True,
        )

        try:

            readable, _, _ = (
                select.select(
                    [sys.stdin],
                    [],
                    [],
                    timeout,
                )
            )

        except Exception:

            print()
            return True

        if not readable:

            print()

            logger.info(
                "ITERATION INTERRUPT: "
                "%ss timeout -> continue",
                timeout,
            )

            return True

        line = sys.stdin.readline()

        if not line:

            print()
            return True

        command = line.strip()

        if not command:
            return True

        if command.lower() in {
            "stop",
            "quit",
            "exit",
        }:
            return False

        if command.lower() == "state":

            state_data = (
                self.state.__dict__
                if self.state
                else {}
            )

            print(
                json.dumps(
                    state_data,
                    indent=2,
                    ensure_ascii=False,
                    default=list,
                )
            )

            print(
                self._workflow_status()
            )

            return self._interrupt()

        assert self.state is not None

        self.state.objective += (
            "\nAdditional user instruction: "
            + command
        )

        self._analyse_objective(
            self.state.objective
        )

        return True

    # ================================================================
    # READ PAGINATION
    # ================================================================

    def _next_read_page(
        self,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:

        assert self.state is not None

        if (
            tool != "read_file"
            or not isinstance(
                arguments.get("path"),
                str,
            )
        ):
            return arguments

        if "start_line" in arguments:
            return arguments

        path = arguments["path"]

        for observation in reversed(
            self.state.observations
        ):

            if (
                observation.get("tool")
                != "read_file"
            ):
                continue

            previous_args = (
                observation.get(
                    "arguments",
                    {},
                )
            )

            result = (
                observation.get(
                    "result",
                    {},
                )
            )

            if (
                previous_args.get("path")
                != path
                or not isinstance(
                    result,
                    dict,
                )
            ):
                continue

            if (
                result.get("ok")
                and result.get("has_more")
                and result.get("next_line")
            ):

                adjusted = dict(
                    arguments
                )

                start = int(
                    result["next_line"]
                )

                adjusted[
                    "start_line"
                ] = start

                adjusted[
                    "end_line"
                ] = (
                    start + 799
                )

                logger.info(
                    "AUTO-PAGINATED "
                    "read_file %s -> "
                    "lines %s-%s",
                    path,
                    start,
                    adjusted["end_line"],
                )

                return adjusted

            break

        return arguments

    # ================================================================
    # TOOL EXECUTION
    # ================================================================

    def _execute(
        self,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:

        assert self.state is not None

        arguments = (
            self._next_read_page(
                tool,
                arguments,
            )
        )

        if tool == "run_shell":

            allowed, reason = (
                self._shell_allowed(
                    str(
                        arguments.get(
                            "command",
                            "",
                        )
                    ),
                    self.state.objective,
                )
            )

            if not allowed:

                result = {
                    "ok": False,
                    "tool": tool,
                    "error": (
                        "Controller blocked "
                        f"command: {reason}"
                    ),
                }

                self.state.record(
                    tool,
                    arguments,
                    result,
                    self.config.max_result_chars,
                )

                return result

        # Duplicate reads are allowed only when automatic pagination
        # changed the arguments.
        if self.state.repeated(
            tool,
            arguments,
            limit=1,
        ):

            result = {
                "ok": False,
                "tool": tool,
                "error": (
                    "Controller blocked "
                    "identical non-progressing "
                    "action."
                ),
                "controller_blocked": True,
            }

            self.state.record(
                tool,
                arguments,
                result,
                self.config.max_result_chars,
            )

            return result

        logger.info(
            "TOOL CALL: %s %s",
            tool,
            json.dumps(
                arguments,
                ensure_ascii=False,
                default=str,
            ),
        )

        result = self.tools.execute(
            tool,
            arguments,
        )

        self.state.tool_calls += 1

        self.state.record(
            tool,
            arguments,
            result,
            self.config.max_result_chars,
        )

        logger.info(
            "TOOL RESULT: %s | ok=%s",
            tool,
            result.get("ok"),
        )

        if (
            result.get("ok")
            and tool
            in {
                "write_file",
                "append_file",
            }
            and isinstance(
                arguments.get("path"),
                str,
            )
        ):

            path = arguments["path"]

            self.memory.remember_file(
                path
            )

            # Controller performs verification itself.
            verify_args = {
                "path": path,
                "start_line": 1,
                "end_line": 160,
            }

            logger.info(
                "CONTROLLER VERIFY WRITE: %s",
                path,
            )

            verify = self.tools.execute(
                "read_file",
                verify_args,
            )

            self.state.tool_calls += 1

            self.state.record(
                "read_file",
                verify_args,
                verify,
                self.config.max_result_chars,
            )

            result[
                "controller_verification"
            ] = {
                key: value
                for key, value
                in verify.items()
                if key != "content"
            }

        return result

    # ================================================================
    # CONTROLLER HINT
    # ================================================================

    def _controller_hint(
        self,
    ) -> str:

        assert self.state is not None

        parts = [
            self._workflow_status()
        ]

        if (
            self.required_read
            and not self._read_complete()
        ):

            parts.append(
                "NEXT REQUIRED PHASE: READ\n"
                "Read the required source file. "
                "Do not write or complete yet."
            )

        elif (
            self.required_write
            and not self._write_complete()
        ):

            target = (
                self.target_write_path
                or "the output file requested "
                "by the user"
            )

            parts.append(
                "NEXT REQUIRED PHASE: WRITE\n"
                "The source has already been "
                "successfully read.\n"
                "DO NOT call read_file again.\n"
                "Use the source content already "
                "present in the observations.\n"
                f"Write the transformed result to: "
                f"{target}\n"
                "Your next action must use "
                "write_file or append_file.\n"
                "Do not claim completion until "
                "the write succeeds."
            )

        elif (
            self.required_web
            and not self._web_complete()
        ):

            parts.append(
                "NEXT REQUIRED PHASE: FETCH\n"
                "Perform the required network "
                "request."
            )

        else:

            parts.append(
                "All controller-required "
                "operations have succeeded.\n"
                "Return complete using only "
                "verified evidence."
            )

        return "\n\n".join(
            parts
        )

    # ================================================================
    # MAIN AGENT LOOP
    # ================================================================

    def run(
        self,
        objective: str,
    ) -> str:

        self.session_id = str(
            uuid.uuid4()
        )

        self.state = TaskState(
            objective=objective
        )

        self._analyse_objective(
            objective
        )

        logger.info(
            "=" * 72
        )

        logger.info(
            "GRANITE CODE AGENT TASK | "
            "session=%s",
            self.session_id,
        )

        logger.info(
            "Objective: %s",
            objective,
        )

        logger.info(
            "Workspace: %s",
            self.config.workspace,
        )

        logger.info(
            "Required workflow: "
            "read=%s write=%s web=%s",
            self.required_read,
            self.required_write,
            self.required_web,
        )

        logger.info(
            "=" * 72
        )

        # ------------------------------------------------------------
        # Exact direct tool syntax
        # ------------------------------------------------------------

        direct_call = (
            self._parse_direct_call(
                objective
            )
        )

        if direct_call:

            name, arguments = (
                direct_call
            )

            result = self._execute(
                name,
                arguments,
            )

            self._print_result(
                name,
                result,
            )

            return self._simple_answer(
                name,
                result,
            )

        # ------------------------------------------------------------
        # Deterministic trivial requests
        # ------------------------------------------------------------

        natural = (
            self._natural_direct(
                objective
            )
        )

        if natural:

            (
                name,
                arguments,
                complete_after_success,
            ) = natural

            logger.info(
                "DIRECT ROUTER: %s %s",
                name,
                json.dumps(
                    arguments,
                    ensure_ascii=False,
                ),
            )

            result = self._execute(
                name,
                arguments,
            )

            self._print_result(
                name,
                result,
            )

            if (
                result.get("ok")
                and complete_after_success
            ):

                answer = (
                    self._simple_answer(
                        name,
                        result,
                    )
                )

                self.state.completed = True
                self.state.final_answer = answer

                self.state.verification = (
                    f"{name} returned ok=true."
                )

                self.memory.remember_task(
                    objective,
                    answer[:2000],
                )

                logger.info(
                    "TASK COMPLETE: "
                    "direct route"
                )

                return answer

            self.state.phase = (
                "replanning"
            )

        # ------------------------------------------------------------
        # Autonomous loop
        # ------------------------------------------------------------

        hint = (
            self._controller_hint()
        )

        last_model_action_signature: (
            str | None
        ) = None

        repeated_model_actions = 0

        for iteration in range(
            1,
            self.config.max_iterations + 1,
        ):

            self.state.iteration = (
                iteration
            )

            if (
                self.state.tool_calls
                >= self.config.max_tool_calls
            ):

                hint = (
                    self._controller_hint()
                    + "\n\n"
                    "TOOL CALL LIMIT REACHED.\n"
                    "Do not call another tool. "
                    "Complete using verified "
                    "evidence if possible."
                )

            logger.info(
                "-" * 72
            )

            logger.info(
                "ITERATION %s/%s | "
                "PHASE=%s | "
                "TOOLS=%s/%s",
                iteration,
                self.config.max_iterations,
                self.state.phase,
                self.state.tool_calls,
                self.config.max_tool_calls,
            )

            logger.info(
                "WORKFLOW: read=%s "
                "write=%s web=%s",
                self._read_complete(),
                self._write_complete(),
                self._web_complete(),
            )

            allowed = (
                self._allowed_tools()
            )

            logger.info(
                "ALLOWED TOOLS: %s",
                sorted(allowed),
            )

            controller_hint = (
                self._controller_hint()
            )

            if hint:

                controller_hint += (
                    "\n\n"
                    "ADDITIONAL CONTROLLER "
                    "INSTRUCTION:\n"
                    + hint
                )

            prompt = build_prompt(
                self.state,
                self.tools.compact_catalog(
                    allowed
                ),
                self.memory.recent(8),
                controller_hint,
            )

            if (
                len(prompt)
                > self.config.max_context_chars
            ):

                head_size = min(
                    12000,
                    self.config.max_context_chars
                    // 2,
                )

                head = prompt[
                    :head_size
                ]

                tail_budget = (
                    self.config.max_context_chars
                    - len(head)
                    - 60
                )

                prompt = (
                    head
                    + "\n"
                    "...[CONTEXT COMPACTED "
                    "BY CONTROLLER]...\n"
                    + prompt[
                        -max(
                            0,
                            tail_budget,
                        ):
                    ]
                )

            raw_text = (
                self.ollama.generate(
                    prompt
                )
            )

            logger.debug(
                "RAW MODEL OUTPUT: %s",
                raw_text,
            )

            raw = self._extract_json(
                raw_text
            )

            action = (
                self._normalize(raw)
                if raw
                else None
            )

            # --------------------------------------------------------
            # Invalid model output
            # --------------------------------------------------------

            if action is None:

                hint = (
                    "Your previous response was "
                    "invalid. Return exactly one "
                    "fresh JSON action. "
                    "Use one of the currently "
                    "allowed tool names or "
                    "'complete'. Do not echo "
                    "tool results."
                )

                logger.warning(
                    "INVALID GRANITE ACTION: %s",
                    raw_text[:1000],
                )

                if not self._interrupt():
                    break

                continue

            # --------------------------------------------------------
            # Detect model-level loops
            # --------------------------------------------------------

            action_signature = (
                json.dumps(
                    action,
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
            )

            if (
                action_signature
                == last_model_action_signature
            ):

                repeated_model_actions += 1

            else:

                repeated_model_actions = 0

            last_model_action_signature = (
                action_signature
            )

            if (
                repeated_model_actions
                >= 2
            ):

                hint = (
                    "MODEL LOOP DETECTED.\n"
                    "The previous action has "
                    "already been attempted.\n"
                    + self._controller_hint()
                )

                logger.warning(
                    "MODEL LOOP DETECTED: %s",
                    action_signature,
                )

                if not self._interrupt():
                    break

                continue

            # --------------------------------------------------------
            # Completion request
            # --------------------------------------------------------

            if (
                action["action"]
                == "complete"
            ):

                valid, reason = (
                    self._completion_valid(
                        action["answer"]
                    )
                )

                if valid:

                    self.state.completed = True

                    self.state.final_answer = (
                        action["answer"]
                    )

                    self.state.verification = (
                        action[
                            "verification"
                        ]
                    )

                    self.memory.remember_task(
                        objective,
                        self.state.final_answer,
                    )

                    logger.info(
                        "TASK COMPLETE"
                    )

                    print(
                        "\n"
                        + self.state.final_answer
                    )

                    if (
                        self.state.verification
                    ):

                        print(
                            "\nVerification: "
                            + self.state.verification
                        )

                    return (
                        self.state.final_answer
                    )

                # Granite tried to finish before the workflow was done.
                hint = (
                    reason
                    + "\n\n"
                    + self._controller_hint()
                )

                logger.warning(
                    "%s",
                    reason,
                )

                if not self._interrupt():
                    break

                continue

            # --------------------------------------------------------
            # Tool request
            # --------------------------------------------------------

            tool = action["action"]

            arguments = action.get(
                "arguments",
                {},
            )

            # If Granite omitted the target path during the write stage,
            # insert the controller-derived output path.
            if (
                tool
                in {
                    "write_file",
                    "append_file",
                }
                and self.target_write_path
                and not arguments.get("path")
            ):

                arguments = dict(
                    arguments
                )

                arguments["path"] = (
                    self.target_write_path
                )

                logger.info(
                    "CONTROLLER INSERTED "
                    "WRITE TARGET: %s",
                    self.target_write_path,
                )

            # --------------------------------------------------------
            # Enforce phase-specific tool whitelist
            # --------------------------------------------------------

            if tool not in allowed:

                hint = (
                    f"Tool '{tool}' is forbidden "
                    "during the current workflow "
                    "phase.\n"
                    f"Allowed tools: "
                    f"{sorted(allowed)}\n\n"
                    + self._controller_hint()
                )

                logger.warning(
                    "TOOL BLOCKED BY "
                    "TASK POLICY: %s",
                    tool,
                )

                if not self._interrupt():
                    break

                continue

            # --------------------------------------------------------
            # Execute
            # --------------------------------------------------------

            result = self._execute(
                tool,
                arguments,
            )

            self._print_result(
                tool,
                result,
            )

            self.state.phase = (
                "replanning"
            )

            # --------------------------------------------------------
            # Successful action
            # --------------------------------------------------------

            if result.get("ok"):

                # Once a source read completes, immediately move the
                # controller into WRITE phase for compound tasks.
                if (
                    tool == "read_file"
                    and self.required_write
                    and self._read_complete()
                    and not self._write_complete()
                ):

                    hint = (
                        "SOURCE READ COMPLETE.\n"
                        "Do not read the source "
                        "again.\n"
                        "Generate the requested "
                        "transformation from the "
                        "source content already "
                        "present in context and "
                        "write it now.\n\n"
                        + self._controller_hint()
                    )

                elif (
                    tool
                    in {
                        "write_file",
                        "append_file",
                    }
                    and self._write_complete()
                ):

                    # Verification is controller-owned in _execute().
                    # Granite does not need another read loop.
                    verification = (
                        result.get(
                            "controller_verification",
                            {},
                        )
                    )

                    verified = (
                        isinstance(
                            verification,
                            dict,
                        )
                        and verification.get(
                            "ok"
                        )
                        is True
                    )

                    if verified:

                        target = (
                            arguments.get(
                                "path"
                            )
                            or self.target_write_path
                            or "output file"
                        )

                        answer = (
                            f"Created {target}"
                        )

                        self.state.completed = (
                            True
                        )

                        self.state.final_answer = (
                            answer
                        )

                        self.state.verification = (
                            "write succeeded and "
                            "controller read-back "
                            "verification succeeded."
                        )

                        self.memory.remember_task(
                            objective,
                            answer,
                        )

                        logger.info(
                            "TASK COMPLETE: "
                            "controller verified "
                            "write"
                        )

                        print(
                            "\n"
                            + answer
                        )

                        print(
                            "\nVerification: "
                            + self.state.verification
                        )

                        return answer

                    hint = (
                        "The write succeeded but "
                        "controller verification "
                        "did not succeed. "
                        "Inspect or repair the "
                        "output without repeating "
                        "the source read."
                    )

                elif (
                    tool
                    == "curl_internet"
                ):

                    if (
                        self.required_write
                        and not self._write_complete()
                    ):

                        hint = (
                            "NETWORK FETCH COMPLETE.\n"
                            "Use the fetched body "
                            "already present in "
                            "context and write the "
                            "requested output file.\n\n"
                            + self._controller_hint()
                        )

                    else:

                        hint = (
                            "Network fetch "
                            "succeeded. Use the "
                            "verified fetched "
                            "content and return "
                            "complete."
                        )

                else:

                    hint = (
                        "Previous operation "
                        "succeeded.\n"
                        + self._controller_hint()
                    )

            # --------------------------------------------------------
            # Failed action
            # --------------------------------------------------------

            else:

                hint = (
                    "Previous operation failed:\n"
                    + str(
                        result.get(
                            "error",
                            "unknown error",
                        )
                    )
                    + "\n\n"
                    + self._controller_hint()
                )

            # --------------------------------------------------------
            # User interrupt
            # --------------------------------------------------------

            if not self._interrupt():
                break

        # ============================================================
        # STOPPED WITHOUT COMPLETION
        # ============================================================

        logger.warning(
            "TASK STOPPED WITHOUT "
            "VERIFIED COMPLETION"
        )

        message = (
            "Task stopped without "
            "verified completion."
        )

        print(
            "\n"
            + message
        )

        return message
