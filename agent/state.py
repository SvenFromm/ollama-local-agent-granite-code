# agent/state.py

from __future__ import annotations

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

    observations: list[
        dict[str, Any]
    ] = field(
        default_factory=list
    )

    read_paths: list[str] = field(
        default_factory=list
    )

    written_paths: list[str] = field(
        default_factory=list
    )

    fetched_urls: list[str] = field(
        default_factory=list
    )

    def record(
        self,
        tool: str,
        arguments: dict[str, Any],
        result: dict[str, Any],
        max_result_chars: int,
    ) -> None:

        stored_result = dict(
            result
        )

        # Preserve useful content while preventing a single observation
        # from consuming the entire context window.
        for field_name in (
            "content",
            "body",
            "stdout",
            "stderr",
        ):

            value = stored_result.get(
                field_name
            )

            if (
                isinstance(value, str)
                and len(value)
                > max_result_chars
            ):

                stored_result[
                    field_name
                ] = (
                    value[
                        :max_result_chars
                    ]
                    + "\n"
                    "...[RESULT TRUNCATED "
                    "BY CONTROLLER]..."
                )

        observation = {
            "tool": tool,
            "arguments": dict(
                arguments
            ),
            "result": stored_result,
        }

        self.observations.append(
            observation
        )

        if not result.get("ok"):
            return

        if (
            tool == "read_file"
            and isinstance(
                arguments.get("path"),
                str,
            )
        ):

            path = arguments["path"]

            if path not in self.read_paths:
                self.read_paths.append(
                    path
                )

        if (
            tool
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

            if (
                path
                not in self.written_paths
            ):
                self.written_paths.append(
                    path
                )

        if (
            tool == "curl_internet"
            and isinstance(
                arguments.get("url"),
                str,
            )
        ):

            url = arguments["url"]

            if url not in self.fetched_urls:
                self.fetched_urls.append(
                    url
                )

    def repeated(
        self,
        tool: str,
        arguments: dict[str, Any],
        limit: int = 1,
    ) -> bool:

        signature = json.dumps(
            {
                "tool": tool,
                "arguments": arguments,
            },
            sort_keys=True,
            ensure_ascii=False,
            default=str,
        )

        count = 0

        for observation in self.observations:

            previous_signature = (
                json.dumps(
                    {
                        "tool": (
                            observation.get(
                                "tool"
                            )
                        ),
                        "arguments": (
                            observation.get(
                                "arguments",
                                {},
                            )
                        ),
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                    default=str,
                )
            )

            if (
                previous_signature
                == signature
            ):
                count += 1

        return count >= limit
