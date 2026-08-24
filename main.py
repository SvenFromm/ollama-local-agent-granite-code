from __future__ import annotations

import json
import signal
import sys

from agent.config import CONFIG
from agent.logging_setup import LOG_FILE, logger
from agent.memory import MemoryStore
from agent.ollama import OllamaClient
from agent.supervisor import Supervisor
from agent.tool_registry import ToolRegistry
from tools.files import FileTools
from tools.internet import InternetTools
from tools.shell import ShellTools

STOP_REQUESTED = False


def signal_handler(signum: int, frame: object) -> None:
    del frame
    global STOP_REQUESTED
    STOP_REQUESTED = True
    logger.warning("Received signal %s", signum)


def build_tools() -> ToolRegistry:
    registry = ToolRegistry()
    files = FileTools(CONFIG.workspace)
    shell = ShellTools(CONFIG.workspace, CONFIG.shell_timeout, CONFIG.max_shell_output_chars)
    internet = InternetTools(CONFIG.max_http_bytes, CONFIG.allow_private_network)
    registry.register("list_files", files.list_files, "files", "List files/directories inside the workspace.")
    registry.register("read_file", files.read_file, "files", "Read a UTF-8 text file with optional line range.")
    registry.register("write_file", files.write_file, "files", "Create or replace a text file.")
    registry.register("append_file", files.append_file, "files", "Append text to a file; use only when append semantics are required.")
    registry.register("run_shell", shell.run_shell, "system", "Run a shell command from the workspace.")
    registry.register("curl_internet", internet.curl_internet, "network", "Fetch a public HTTP/HTTPS URL; private-network targets are blocked by default.")
    return registry


def print_help() -> None:
    print(
        "Commands:\n"
        "  tools             Show the formatted tool catalog\n"
        "  tool <name>       Show details for one tool\n"
        "  memory            Show recent persistent memory\n"
        "  help              Show this help\n"
        "  exit              Exit the agent\n\n"
        "Direct fast paths include read_file(path), list_files(path), and explicit shell requests such as 'run command whoami'."
    )


def main() -> None:
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    CONFIG.workspace.mkdir(parents=True, exist_ok=True)

    memory = MemoryStore(CONFIG.workspace)
    tools = build_tools()
    ollama = OllamaClient(CONFIG)

    logger.info("=" * 72)
    logger.info("LOCAL GRANITE CODE AUTONOMOUS AGENT STARTING")
    logger.info("Model: %s", CONFIG.model)
    logger.info("Ollama: %s", CONFIG.ollama_host)
    logger.info("Workspace: %s", CONFIG.workspace)
    logger.info("Context: %s", CONFIG.num_ctx)
    logger.info("Generation: action_predict=%s transform_predict=%s", CONFIG.action_num_predict, CONFIG.transform_num_predict)
    logger.info("Python: %s", sys.version.replace("\n", " "))
    logger.info("Log: %s", LOG_FILE)
    logger.info("=" * 72)

    try:
        logger.info("Ollama available: %s", ollama.version())
    except Exception:
        logger.exception("Ollama unavailable")
        raise SystemExit(1)
    if not ollama.model_available():
        logger.error("Model not available: %s", CONFIG.model)
        raise SystemExit(1)

    supervisor = Supervisor(CONFIG, memory, tools, ollama)

    print("\n" + "=" * 72)
    print(" GRANITE CODE LOCAL AUTONOMOUS AGENT")
    print("=" * 72)
    print(f"Model:     {CONFIG.model}")
    print(f"Ollama:    {CONFIG.ollama_host}")
    print(f"Workspace: {CONFIG.workspace}")
    print(f"Context:   {CONFIG.num_ctx}")
    print(f"Predict:   action={CONFIG.action_num_predict} transform={CONFIG.transform_num_predict}")
    print(f"Log:       {LOG_FILE}")
    print("Commands: tools | tool <name> | memory | help | exit\n")

    while not STOP_REQUESTED:
        try:
            task = input("Task> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not task:
            continue
        lowered = task.lower()
        if lowered in {"quit", "exit", "stop"}:
            break
        if lowered == "tools":
            print(tools.catalog_text())
            continue
        if lowered.startswith("tool "):
            print("\n" + tools.tool_text(task[5:].strip()) + "\n")
            continue
        if lowered == "memory":
            print(json.dumps(memory.recent(20), indent=2, ensure_ascii=False, default=str))
            continue
        if lowered == "help":
            print_help()
            continue
        try:
            supervisor.run(task)
        except KeyboardInterrupt:
            print()
            logger.warning("Current task interrupted")
        except Exception:
            logger.exception("Agent task failed")
    logger.info("Agent stopped")


if __name__ == "__main__":
    main()
