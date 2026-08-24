from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agent.tool_registry import ToolRegistry
from tools.files import FileTools
from tools.internet import InternetTools
from tools.shell import ShellTools


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.files = FileTools(self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_write_read_append(self) -> None:
        self.assertTrue(self.files.write_file("a.txt", "one\n")["ok"])
        self.assertTrue(self.files.append_file("a.txt", "two\n")["ok"])
        result = self.files.read_file("a.txt")
        self.assertIn("one", result["content"])
        self.assertIn("two", result["content"])

    def test_list_files_recursive(self) -> None:
        self.files.write_file("sub/a.txt", "x")
        shallow = self.files.list_files(".", recursive=False)
        deep = self.files.list_files(".", recursive=True)
        self.assertIn("sub/", shallow["files"])
        self.assertIn("sub/a.txt", deep["files"])

    def test_missing_file(self) -> None:
        self.assertFalse(self.files.read_file("missing.txt")["ok"])

    def test_invalid_line_range(self) -> None:
        self.files.write_file("a.txt", "x")
        self.assertFalse(self.files.read_file("a.txt", 2, 1)["ok"])

    def test_workspace_escape(self) -> None:
        with self.assertRaises(PermissionError):
            self.files.read_file("../escape.txt")

    def test_symlink_escape(self) -> None:
        outside = Path(self.tmp.name).parent / "outside-agent-test.txt"
        outside.write_text("secret", encoding="utf-8")
        try:
            (self.root / "link.txt").symlink_to(outside)
            with self.assertRaises(PermissionError):
                self.files.read_file("link.txt")
        finally:
            outside.unlink(missing_ok=True)

    def test_write_overwrites_existing_file(self) -> None:
        self.files.write_file("a.txt", "first")
        self.files.write_file("a.txt", "second")
        self.assertIn("second", self.files.read_file("a.txt")["content"])
        self.assertNotIn("first", self.files.read_file("a.txt")["content"])

    def test_registry_sanitizes_extra_arguments(self) -> None:
        registry = ToolRegistry()
        registry.register("read_file", self.files.read_file, "files", "read")
        result = registry.execute("read_file", {"path": "missing.txt", "description": "bad"})
        self.assertFalse(result["ok"])
        self.assertNotIn("unexpected keyword", result.get("error", ""))

    def test_shell_success(self) -> None:
        shell = ShellTools(self.root, timeout=5)
        result = shell.run_shell("printf hello")
        self.assertTrue(result["ok"])
        self.assertEqual(result["stdout"], "hello")

    def test_shell_nonzero(self) -> None:
        shell = ShellTools(self.root, timeout=5)
        result = shell.run_shell("exit 7")
        self.assertFalse(result["ok"])
        self.assertEqual(result["returncode"], 7)

    def test_shell_output_truncation(self) -> None:
        shell = ShellTools(self.root, timeout=5, max_output_chars=10)
        result = shell.run_shell("printf 123456789012345")
        self.assertIn("TRUNCATED", result["stdout"])

    def test_internet_rejects_file_scheme(self) -> None:
        internet = InternetTools(resolver=lambda *args, **kwargs: [])
        result = internet.curl_internet("file:///etc/passwd")
        self.assertFalse(result["ok"])

    def test_internet_blocks_loopback(self) -> None:
        def resolver(*args, **kwargs):
            return [(2, 1, 6, "", ("127.0.0.1", 80))]
        internet = InternetTools(resolver=resolver)
        allowed, reason = internet._validate_url("http://localhost/")
        self.assertFalse(allowed)
        self.assertIn("blocked", reason.lower())

    def test_internet_private_network_override(self) -> None:
        def resolver(*args, **kwargs):
            return [(2, 1, 6, "", ("127.0.0.1", 80))]
        internet = InternetTools(allow_private_network=True, resolver=resolver)
        allowed, _ = internet._validate_url("http://localhost/")
        self.assertTrue(allowed)

    def test_internet_allows_public_resolution(self) -> None:
        def resolver(*args, **kwargs):
            return [(2, 1, 6, "", ("93.184.216.34", 80))]
        internet = InternetTools(resolver=resolver)
        allowed, _ = internet._validate_url("http://example.com/")
        self.assertTrue(allowed)
