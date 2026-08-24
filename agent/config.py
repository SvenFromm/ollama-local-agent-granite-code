from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Config:
    model: str
    ollama_host: str
    workspace: Path
    num_ctx: int
    num_predict: int
    temperature: float
    top_p: float
    top_k: int
    keep_alive: str
    max_iterations: int
    max_tool_calls: int
    read_timeout: int
    shell_timeout: int
    interrupt_timeout: int
    max_context_chars: int
    max_result_chars: int


CONFIG = Config(
    model=os.getenv("OLLAMA_MODEL", "granite-code:3b"),
    ollama_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/"),
    workspace=Path(os.getenv("AGENT_WORKSPACE", str(PROJECT_DIR))).expanduser().resolve(),
    num_ctx=int(os.getenv("AGENT_NUM_CTX", "16384")),
    num_predict=int(os.getenv("AGENT_NUM_PREDICT", "256")),
    temperature=float(os.getenv("AGENT_TEMPERATURE", "0.0")),
    top_p=float(os.getenv("AGENT_TOP_P", "0.85")),
    top_k=int(os.getenv("AGENT_TOP_K", "20")),
    keep_alive=os.getenv("AGENT_KEEP_ALIVE", "30m"),
    max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "24")),
    max_tool_calls=int(os.getenv("AGENT_MAX_TOOL_CALLS", "24")),
    read_timeout=int(os.getenv("OLLAMA_READ_TIMEOUT", "180")),
    shell_timeout=int(os.getenv("AGENT_SHELL_TIMEOUT", "120")),
    interrupt_timeout=int(os.getenv("AGENT_INTERRUPT_TIMEOUT", "3")),
    max_context_chars=int(os.getenv("AGENT_MAX_CONTEXT_CHARS", "42000")),
    max_result_chars=int(os.getenv("AGENT_MAX_RESULT_CHARS", "10000")),
)
