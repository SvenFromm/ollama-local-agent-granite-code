from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DirectRoute:
    tool: str
    arguments: dict[str, Any]
    complete_after_success: bool = True


def parse_direct_call(task: str) -> DirectRoute | None:
    match = re.fullmatch(r"\s*(list_files|read_file|write_file|append_file)\s*\((.*)\)\s*", task, flags=re.S)
    if not match:
        return None
    name, raw_args = match.groups()
    raw_args = raw_args.strip()
    if not raw_args:
        return DirectRoute(name, {})
    try:
        expression = ast.parse(f"f({raw_args})", mode="eval").body
        if not isinstance(expression, ast.Call):
            return None
        arguments: dict[str, Any] = {}
        positional_names = {
            "list_files": ("path", "recursive"),
            "read_file": ("path", "start_line", "end_line"),
            "write_file": ("path", "content"),
            "append_file": ("path", "content"),
        }[name]
        for index, argument in enumerate(expression.args):
            if index < len(positional_names):
                arguments[positional_names[index]] = ast.literal_eval(argument)
        for keyword in expression.keywords:
            if keyword.arg:
                arguments[keyword.arg] = ast.literal_eval(keyword.value)
        return DirectRoute(name, arguments)
    except Exception:
        if name in {"list_files", "read_file"}:
            return DirectRoute(name, {"path": raw_args.strip().strip("\"'")})
        return None


def natural_direct(task: str) -> DirectRoute | None:
    text = re.sub(r"\s+", " ", task.strip())
    lower = text.lower()

    listing_patterns = {
        "list files", "show files", "list directory", "show directory",
        "list current folder", "list current directory",
        "list files of current folder", "list files in current folder",
        "list files of current directory", "list files in current directory",
        "list content of current working directory", "list contents of current working directory",
        "list files of the working directory", "list files in the working directory",
        "list files of working directory", "list files in working directory",
        "list the working directory", "show files of the working directory",
    }
    if lower in listing_patterns:
        return DirectRoute("list_files", {"path": ".", "recursive": False})

    if re.search(r"\b(recursive|recursively|including subdirectories|directory tree|all files under)\b", lower) and re.search(r"\b(list|show)\b", lower):
        return DirectRoute("list_files", {"path": ".", "recursive": True})

    shell_match = re.fullmatch(
        r"(?:execute|run)(?: (?:the )?(?:script|command|shell command))?\s+(.+)",
        text,
        flags=re.I,
    )
    if shell_match:
        command = shell_match.group(1).strip()
        if command:
            return DirectRoute("run_shell", {"command": command})

    read_match = re.fullmatch(r"(?:read|show|display)(?: file)?\s+(.+)", text, flags=re.I)
    if read_match and not re.search(
        r"\b(summari[sz]e|analy[sz]e|analyse|review|then|write|save|create|modify|update|edit|fix|change|append)\b",
        lower,
    ):
        return DirectRoute("read_file", {"path": read_match.group(1).strip().strip("\"'")})

    return None
