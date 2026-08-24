from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.config import Config
from agent.memory import MemoryStore
from agent.supervisor import Supervisor
from agent.tool_registry import ToolRegistry
from tools.files import FileTools
from tools.internet import InternetTools
from tools.shell import ShellTools


class FakeOllama:
    def __init__(self, responses: list[str] | None = None) -> None:
        self.responses = responses or ['{"action":"complete","answer":"done","verification":"test"}']
        self.calls = 0

    def generate(self, prompt: str, num_predict=None) -> str:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class SupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.config = Config(
            "granite-code:3b",
            "http://127.0.0.1:11434",
            root,
            16384,
            256,
            0,
            .85,
            20,
            "5m",
            6,
            12,
            10,
            10,
            0,
            42000,
            10000,
        )
        self.memory = MemoryStore(root)
        files = FileTools(root)
        internet = InternetTools()
        self.registry = ToolRegistry()
        self.registry.register("list_files", files.list_files, "files", "list")
        self.registry.register("read_file", files.read_file, "files", "read")
        self.registry.register("write_file", files.write_file, "files", "write")
        self.registry.register("append_file", files.append_file, "files", "append")
        self.registry.register("curl_internet", internet.curl_internet, "network", "fetch")
        shell = ShellTools(root, timeout=10)
        self.registry.register("run_shell", shell.run_shell, "system", "run")
        self.ollama = FakeOllama()
        self.supervisor = Supervisor(self.config, self.memory, self.registry, self.ollama)
        self.files = files

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_normalizes_nested_arguments(self) -> None:
        result = self.supervisor._normalize(
            {"action": "read_file", "arguments": {"arguments": {"path": "a"}}}
        )
        self.assertEqual(result, {"action": "read_file", "arguments": {"path": "a"}})

    def test_return_maps_to_complete(self) -> None:
        result = self.supervisor._normalize({"action": "return", "answer": "x"})
        self.assertEqual(result["action"], "complete")

    def test_direct_read_parser(self) -> None:
        result = self.supervisor._parse_direct_call("read_file('a.txt')")
        self.assertEqual(result, ("read_file", {"path": "a.txt"}))

    def test_natural_list_is_direct(self) -> None:
        result = self.supervisor._natural_direct("list files of current folder")
        self.assertEqual(result, ("list_files", {"path": ".", "recursive": False}, True))

    def test_natural_read_is_direct(self) -> None:
        result = self.supervisor._natural_direct("read file a.txt")
        self.assertEqual(result, ("read_file", {"path": "a.txt"}, True))

    def test_execute_script_is_direct_shell(self) -> None:
        result = self.supervisor._natural_direct("execute script whoami")
        self.assertEqual(result, ("run_shell", {"command": "whoami"}, True))

    def test_run_command_is_direct_shell(self) -> None:
        result = self.supervisor._natural_direct("run command pwd")
        self.assertEqual(result, ("run_shell", {"command": "pwd"}, True))

    def test_execute_script_does_not_call_model(self) -> None:
        output = self.supervisor.run("execute script whoami")
        self.assertTrue(output.strip())
        self.assertEqual(self.ollama.calls, 0)

    def test_news_is_direct_network_fetch(self) -> None:
        result = self.supervisor._natural_direct("lookup current news in the internet")
        self.assertEqual(result[0], "curl_internet")
        self.assertTrue(result[1]["url"].startswith("https://"))

    def test_simple_list_does_not_call_model(self) -> None:
        self.files.write_file("a.txt", "x")
        output = self.supervisor.run("list files of current folder")
        self.assertIn("a.txt", output)
        self.assertEqual(self.ollama.calls, 0)

    def test_duplicate_read_auto_paginates(self) -> None:
        self.files.write_file("big.txt", "\n".join(str(i) for i in range(1200)))
        self.supervisor.state = __import__("agent.state", fromlist=["TaskState"]).TaskState("summarize big.txt")
        first = self.supervisor._execute("read_file", {"path": "big.txt"})
        self.assertTrue(first["ok"])
        second = self.supervisor._execute("read_file", {"path": "big.txt"})
        self.assertTrue(second["ok"])
        last = self.supervisor.state.observations[-1]
        self.assertEqual(last["arguments"]["start_line"], 801)


if __name__ == "__main__":
    unittest.main()
