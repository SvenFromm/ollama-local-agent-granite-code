from __future__ import annotations

import re
from dataclasses import dataclass


FILE_EXTENSIONS = r"py|txt|md|json|yaml|yml|toml|csv|ini|cfg|conf|sh|rs|js|ts|html|xml"


@dataclass(frozen=True)
class ObjectiveRequirements:
    read: bool = False
    write: bool = False
    web: bool = False
    shell: bool = False
    output_path: str | None = None
    source_path: str | None = None
    write_mode: str | None = None  # "write" | "append"
    literal_content: str | None = None


def _clean_path(value: str) -> str:
    return value.strip().strip("\"'").rstrip(".,;:")


def extract_literal_content(objective: str) -> str | None:
    patterns = (
        r"\bwith\s+(?:the\s+)?content\s*:\s*(.+)$",
        r"\bcontaining\s*:\s*(.+)$",
        r"\bcontent\s*=\s*(.+)$",
    )
    for pattern in patterns:
        match = re.search(pattern, objective, flags=re.I | re.S)
        if match:
            value = match.group(1).strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return None


def extract_write_mode(objective: str) -> str | None:
    lower = objective.lower().strip()
    if re.search(r"\b(append|add\s+to)\b", lower):
        return "append"
    if re.search(r"\b(write|save|create|modify|update|edit|fix|change|rewrite|summari[sz]e)\b", lower):
        return "write"
    return None


def extract_output_path(objective: str) -> str | None:
    # Prefer explicit mutation targets first. This prevents an old output path
    # mentioned elsewhere in context from becoming the write target.
    patterns = (
        rf"\b(?:append|add\s+to)\s+(?:the\s+)?(?:file\s+)?[\"']?([^\s\"']+\.(?:{FILE_EXTENSIONS}))[\"']?",
        rf"\bcreate\s+(?:a\s+)?file\s+(?:called|named)\s+[\"']?([^\s\"']+\.(?:{FILE_EXTENSIONS}))[\"']?",
        rf"\b(?:new|output)\s+file\s+[\"']?([^\s\"']+\.(?:{FILE_EXTENSIONS}))[\"']?",
        rf"\b(?:write|save|create)\s+(?:to\s+)?(?:a\s+)?(?:file\s+)?[\"']?([^\s\"']+\.(?:{FILE_EXTENSIONS}))[\"']?",
        rf"\b(?:in|to)\s+(?:a\s+)?(?:new\s+)?(?:file\s+)?[\"']?([^\s\"']+\.(?:{FILE_EXTENSIONS}))[\"']?",
    )
    for pattern in patterns:
        match = re.search(pattern, objective, flags=re.I)
        if match:
            value = _clean_path(match.group(1))
            if value:
                return value
    return None


def extract_source_path(objective: str, output_path: str | None = None) -> str | None:
    candidates = re.findall(
        rf"[\"']?((?:/|\./|\.\./)?[A-Za-z0-9_./~-]+\.(?:{FILE_EXTENSIONS}))[\"']?",
        objective,
        flags=re.I,
    )
    for candidate in candidates:
        value = _clean_path(candidate)
        if output_path and value == output_path:
            continue
        return value
    return None


def extract_url(objective: str) -> str | None:
    match = re.search(r"https?://[^\s\"'<>]+", objective, flags=re.I)
    return match.group(0).rstrip(".,;:") if match else None


def analyze_objective(objective: str) -> ObjectiveRequirements:
    lower = objective.lower()
    write_mode = extract_write_mode(objective)
    output_path = extract_output_path(objective)
    source_path = extract_source_path(objective, output_path)
    literal_content = extract_literal_content(objective)

    read = bool(re.search(r"\b(read|inspect|review|summari[sz]e|analy[sz]e|analyse|examine)\b", lower))
    write = bool(write_mode and (output_path is not None or source_path is not None or re.search(r"\bfile\b", lower)))
    web = bool(re.search(r"\b(internet|web|website|online|latest|current\s+news|recent\s+news|news)\b", lower)) or "http://" in lower or "https://" in lower
    shell = bool(
        re.match(
            r"^\s*(execute|run)(?:\s+(?:the\s+)?(?:script|command|shell command))?\s+",
            objective,
            flags=re.I,
        )
    )

    # For mutation-only requests the named file is the output target, not an
    # analysis source. E.g. "append the file test.txt ...".
    if write and not read and output_path is None and source_path is not None:
        output_path, source_path = source_path, None

    return ObjectiveRequirements(
        read=read,
        write=write,
        web=web,
        shell=shell,
        output_path=output_path,
        source_path=source_path,
        write_mode=write_mode,
        literal_content=literal_content,
    )
