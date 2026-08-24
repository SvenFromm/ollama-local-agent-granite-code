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
    global STOP_REQUESTED
    STOP_REQUESTED = True
    logger.warning("Received signal %s", signum)

def build_tools() -> ToolRegistry:
    registry = ToolRegistry()
    files = FileTools(CONFIG.workspace)
    shell = ShellTools(CONFIG.workspace, CONFIG.shell_timeout)
    internet = InternetTools()
    registry.register("list_files", files.list_files, "files", "List files/directories inside the workspace.")
    registry.register("read_file", files.read_file, "files", "Read a UTF-8 text file with optional line range.")
    registry.register("write_file", files.write_file, "files", "Create or replace a text file.")
    registry.register("append_file", files.append_file, "files", "Append text to a file; use only when append semantics are required.")
    registry.register("run_shell", shell.run_shell, "system", "Run a shell command from the workspace.")
    registry.register("curl_internet", internet.curl_internet, "network", "Fetch an HTTP/HTTPS URL.")
    return registry

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
    print(f"Log:       {LOG_FILE}")
    print("Commands: tools | memory | help | exit\n")
    while not STOP_REQUESTED:
        try:
            task = input("Task> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not task:
            continue
        lowered = task.lower()
        if lowered in {"quit", "exit", "stop"}:
            break
        if lowered == "tools":
            print(tools.catalog_text()); continue
        if lowered == "memory":
            print(json.dumps(memory.recent(20), indent=2, ensure_ascii=False, default=str)); continue
        if lowered == "help":
            print("Enter a task in natural language.\nDirect fast paths: read_file(path), list_files(path).\nBuilt-ins: tools, memory, help, exit.")
            continue
        try:
            supervisor.run(task)
        except KeyboardInterrupt:
            print(); logger.warning("Current task interrupted")
        except Exception:
            logger.exception("Agent task failed")
    logger.info("Agent stopped")

if __name__ == "__main__":
    main()
