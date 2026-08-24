from __future__ import annotations
import tempfile
import unittest
from pathlib import Path
from tools.files import FileTools
from agent.tool_registry import ToolRegistry

class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.files = FileTools(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_write_read_list_append(self) -> None:
        self.assertTrue(self.files.write_file("a.txt", "one\n")["ok"])
        self.assertTrue(self.files.append_file("a.txt", "two\n")["ok"])
        result = self.files.read_file("a.txt")
        self.assertTrue(result["ok"])
        self.assertIn("one", result["content"])
        self.assertIn("two", result["content"])
        listed = self.files.list_files(".")
        self.assertIn("a.txt", listed["files"])

    def test_workspace_escape_blocked(self) -> None:
        with self.assertRaises(PermissionError):
            self.files.safe_path("/etc/passwd")

    def test_registry_flattens_arguments(self) -> None:
        registry = ToolRegistry()
        registry.register("read_file", self.files.read_file, "files", "read")
        self.files.write_file("x.txt", "x")
        result = registry.execute("read_file", {"arguments": {"path": "x.txt"}})
        self.assertTrue(result["ok"])

if __name__ == "__main__":
    unittest.main()
