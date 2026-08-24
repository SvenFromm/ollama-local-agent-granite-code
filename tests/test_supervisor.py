from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.config import Config
from agent.memory import MemoryStore
from agent.supervisor import Supervisor
from agent.tool_registry import ToolRegistry
from tools.files import FileTools
from tools.shell import ShellTools


RSS = """<?xml version='1.0'?><rss><channel><item><title>Headline One</title><description>Story one.</description></item><item><title>Headline Two</title><description>Story two.</description></item></channel></rss>"""


class FakeOllama:
    def __init__(self, action_responses: list[str] | None = None, text_responses: list[str] | None = None) -> None:
        self.action_responses = list(action_responses or [])
        self.text_responses = list(text_responses or [])
        self.action_calls = 0
        self.text_calls = 0
        self.prompts: list[str] = []

    @property
    def calls(self) -> int:
        return self.action_calls + self.text_calls

    def generate(self, prompt: str, num_predict: int | None = None) -> str:
        del num_predict
        self.action_calls += 1
        self.prompts.append(prompt)
        if not self.action_responses:
            raise AssertionError("Unexpected action-model call")
        return self.action_responses.pop(0)

    def generate_text(self, prompt: str, num_predict: int | None = None) -> str:
        del num_predict
        self.text_calls += 1
        self.prompts.append(prompt)
        if not self.text_responses:
            raise AssertionError("Unexpected transform-model call")
        return self.text_responses.pop(0)


class FastSupervisor(Supervisor):
    def _interrupt(self) -> bool:
        return True


class SupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.config = Config(
            model="granite-code:3b",
            ollama_host="http://127.0.0.1:11434",
            workspace=self.root,
            num_ctx=16384,
            num_predict=256,
            temperature=0.0,
            top_p=0.85,
            top_k=20,
            keep_alive="30m",
            max_iterations=8,
            max_tool_calls=12,
            read_timeout=10,
            shell_timeout=5,
            interrupt_timeout=1,
            max_context_chars=52000,
            max_result_chars=12000,
            max_shell_output_chars=20000,
            max_http_bytes=100000,
            allow_private_network=False,
            action_num_predict=96,
            transform_num_predict=384,
            default_news_url="https://feeds.bbci.co.uk/news/rss.xml",
            max_transform_input_chars=28000,
            max_nonprogress_iterations=3,
        )
        self.memory = MemoryStore(self.root)
        files = FileTools(self.root)
        shell = ShellTools(self.root, timeout=5)
        self.registry = ToolRegistry()
        self.registry.register("list_files", files.list_files, "files", "list")
        self.registry.register("read_file", files.read_file, "files", "read")
        self.registry.register("write_file", files.write_file, "files", "write")
        self.registry.register("append_file", files.append_file, "files", "append")
        self.registry.register("run_shell", shell.run_shell, "system", "shell")
        self.registry.register("curl_internet", lambda url, timeout=30: {"ok": True, "url": url, "body": RSS}, "network", "fetch")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def make(self, actions: list[str] | None = None, texts: list[str] | None = None) -> tuple[FastSupervisor, FakeOllama]:
        ollama = FakeOllama(actions, texts)
        return FastSupervisor(self.config, self.memory, self.registry, ollama), ollama

    def test_direct_list_avoids_model(self) -> None:
        (self.root / "a.txt").write_text("x", encoding="utf-8")
        supervisor, ollama = self.make()
        result = supervisor.run("list files of the working directory")
        self.assertIn("a.txt", result)
        self.assertEqual(ollama.calls, 0)

    def test_direct_shell_avoids_model(self) -> None:
        supervisor, ollama = self.make()
        result = supervisor.run("execute script whoami")
        self.assertTrue(result.strip())
        self.assertEqual(ollama.calls, 0)

    def test_literal_create_avoids_model_and_uses_write_not_append(self) -> None:
        supervisor, ollama = self.make()
        result = supervisor.run('create a file called "test.txt" with the content: Hello World!')
        self.assertEqual(result, "Created test.txt")
        self.assertEqual((self.root / "test.txt").read_text(encoding="utf-8"), "Hello World!")
        self.assertEqual(ollama.calls, 0)

    def test_compound_summary_uses_transform_model_once_then_writes(self) -> None:
        (self.root / "source.py").write_text("def hello():\n    return 'world'\n", encoding="utf-8")
        supervisor, ollama = self.make(texts=["Summary of hello function."])
        result = supervisor.run("read source.py and summarize it in summary.txt")
        self.assertEqual(result, "Created summary.txt")
        self.assertEqual((self.root / "summary.txt").read_text(encoding="utf-8"), "Summary of hello function.")
        self.assertEqual(ollama.action_calls, 0)
        self.assertEqual(ollama.text_calls, 1)

    def test_source_pagination_is_controller_owned(self) -> None:
        content = "\n".join(f"line {i}" for i in range(1700))
        (self.root / "source.txt").write_text(content, encoding="utf-8")
        supervisor, ollama = self.make(texts=["summary"])
        result = supervisor.run("read source.txt and summarize it in summary.txt")
        self.assertEqual(result, "Created summary.txt")
        source_reads = [obs for obs in supervisor.state.observations if obs.get("tool") == "read_file" and obs.get("arguments", {}).get("path") == "source.txt"]
        self.assertEqual(len(source_reads), 3)
        self.assertEqual(ollama.calls, 1)

    def test_news_is_controller_routed_without_model(self) -> None:
        supervisor, ollama = self.make()
        result = supervisor.run("get latest news")
        self.assertIn("Headline One", result)
        self.assertEqual(ollama.calls, 0)
        self.assertFalse(any(obs.get("tool") == "read_file" for obs in supervisor.state.observations))

    def test_append_target_is_controller_owned(self) -> None:
        (self.root / "test.txt").write_text("Existing\n", encoding="utf-8")
        supervisor, ollama = self.make(texts=["Granite Code is the local model used by this agent.\n"])
        result = supervisor.run("append the file test.txt with a description about your model")
        self.assertEqual(result, "Updated test.txt")
        text = (self.root / "test.txt").read_text(encoding="utf-8")
        self.assertIn("Granite Code", text)
        self.assertFalse((self.root / "agent" / "supervisor_summary.txt").exists())
        self.assertEqual(ollama.action_calls, 0)
        self.assertEqual(ollama.text_calls, 1)

    def test_add_to_file_target_is_controller_owned(self) -> None:
        (self.root / "test.txt").write_text("Existing\n", encoding="utf-8")
        supervisor, ollama = self.make(texts=["Model information.\n"])
        supervisor.run("add to the file test.txt information about your model")
        self.assertIn("Model information", (self.root / "test.txt").read_text(encoding="utf-8"))
        self.assertEqual(ollama.calls, 1)

    def test_memory_history_is_not_in_action_prompt(self) -> None:
        self.memory.remember_task("old task", "agent/supervisor_summary.txt old result")
        supervisor, ollama = self.make(actions=['{"action":"complete","answer":"done","verification":"none"}'])
        result = supervisor.run("perform a general coding task")
        self.assertEqual(result, "done")
        self.assertNotIn("supervisor_summary.txt", ollama.prompts[0])

    def test_unrequested_dangerous_shell_is_blocked(self) -> None:
        supervisor, _ = self.make(actions=[
            '{"action":"run_shell","arguments":{"command":"sudo apt update"}}',
            '{"action":"complete","answer":"cannot proceed","verification":"blocked"}',
        ])
        result = supervisor.run("perform a general coding task")
        self.assertEqual(result, "cannot proceed")
        shell_obs = [obs for obs in supervisor.state.observations if obs.get("tool") == "run_shell"]
        self.assertTrue(shell_obs[-1]["result"].get("controller_blocked"))

    def test_nonprogress_aborts_early(self) -> None:
        supervisor, ollama = self.make(actions=[
            '{"action":"read_file","arguments":{"path":"wrong.txt"}}',
            '{"action":"read_file","arguments":{"path":"wrong.txt"}}',
            '{"action":"read_file","arguments":{"path":"wrong.txt"}}',
            '{"action":"read_file","arguments":{"path":"wrong.txt"}}',
        ])
        result = supervisor.run("perform a general coding task")
        self.assertEqual(result, "Task stopped without verified completion.")
        self.assertLessEqual(ollama.action_calls, 4)
