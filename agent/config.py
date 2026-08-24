from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent


def _positive_int(name: str, default: int, minimum: int = 1) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}, got {value}")
    return value


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be in [{minimum}, {maximum}], got {value}")
    return value


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
    max_shell_output_chars: int
    max_http_bytes: int
    allow_private_network: bool
    action_num_predict: int
    transform_num_predict: int
    default_news_url: str
    max_transform_input_chars: int
    max_nonprogress_iterations: int


def load_config() -> Config:
    return Config(
        model=os.getenv("OLLAMA_MODEL", "granite-code:3b"),
        ollama_host=os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/"),
        workspace=Path(os.getenv("AGENT_WORKSPACE", str(PROJECT_DIR))).expanduser().resolve(),
        num_ctx=_positive_int("AGENT_NUM_CTX", 16384, 1024),
        num_predict=_positive_int("AGENT_NUM_PREDICT", 256, 32),
        temperature=_bounded_float("AGENT_TEMPERATURE", 0.0, 0.0, 2.0),
        top_p=_bounded_float("AGENT_TOP_P", 0.85, 0.0, 1.0),
        top_k=_positive_int("AGENT_TOP_K", 20),
        keep_alive=os.getenv("AGENT_KEEP_ALIVE", "30m"),
        max_iterations=_positive_int("AGENT_MAX_ITERATIONS", 24),
        max_tool_calls=_positive_int("AGENT_MAX_TOOL_CALLS", 24),
        read_timeout=_positive_int("OLLAMA_READ_TIMEOUT", 180),
        shell_timeout=_positive_int("AGENT_SHELL_TIMEOUT", 120),
        interrupt_timeout=_positive_int("AGENT_INTERRUPT_TIMEOUT", 3),
        max_context_chars=_positive_int("AGENT_MAX_CONTEXT_CHARS", 52000, 8000),
        max_result_chars=_positive_int("AGENT_MAX_RESULT_CHARS", 12000, 1000),
        max_shell_output_chars=_positive_int("AGENT_MAX_SHELL_OUTPUT_CHARS", 20000, 1000),
        max_http_bytes=_positive_int("AGENT_MAX_HTTP_BYTES", 1_000_000, 1024),
        allow_private_network=os.getenv("AGENT_ALLOW_PRIVATE_NETWORK", "0").strip().lower()
        in {"1", "true", "yes", "on"},
        action_num_predict=_positive_int("AGENT_ACTION_NUM_PREDICT", 96, 32),
        transform_num_predict=_positive_int("AGENT_TRANSFORM_NUM_PREDICT", 384, 64),
        default_news_url=os.getenv("AGENT_NEWS_URL", "https://feeds.bbci.co.uk/news/rss.xml"),
        max_transform_input_chars=_positive_int("AGENT_MAX_TRANSFORM_INPUT_CHARS", 28000, 4000),
        max_nonprogress_iterations=_positive_int("AGENT_MAX_NONPROGRESS_ITERATIONS", 3, 1),
    )


CONFIG = load_config()
