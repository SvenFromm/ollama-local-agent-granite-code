from __future__ import annotations

import unittest

from agent.direct_router import natural_direct, parse_direct_call
from agent.objective import analyze_objective, extract_literal_content
from agent.state import TaskState
from agent.workflow import WorkflowPolicy


class RoutingWorkflowTests(unittest.TestCase):
    def test_list_files_natural_route(self) -> None:
        route = natural_direct("list files of the working directory")
        self.assertEqual(route.tool, "list_files")
        self.assertEqual(route.arguments, {"path": ".", "recursive": False})

    def test_shell_natural_route(self) -> None:
        route = natural_direct("execute script whoami")
        self.assertEqual(route.tool, "run_shell")

    def test_simple_read_route(self) -> None:
        self.assertEqual(natural_direct("read file README.md").tool, "read_file")

    def test_compound_read_not_direct(self) -> None:
        self.assertIsNone(natural_direct("read README.md and summarize it in summary.txt"))

    def test_direct_call_parser_supports_write(self) -> None:
        route = parse_direct_call('write_file("x.txt", "hello")')
        self.assertEqual(route.arguments, {"path": "x.txt", "content": "hello"})

    def test_objective_paths(self) -> None:
        req = analyze_objective("read agent/supervisor.py and summarize it in supervisor_summary.txt")
        self.assertTrue(req.read)
        self.assertTrue(req.write)
        self.assertEqual(req.source_path, "agent/supervisor.py")
        self.assertEqual(req.output_path, "supervisor_summary.txt")
        self.assertEqual(req.write_mode, "write")

    def test_append_file_is_output_not_source(self) -> None:
        req = analyze_objective("append the file test.txt with a description about your model")
        self.assertTrue(req.write)
        self.assertFalse(req.read)
        self.assertEqual(req.output_path, "test.txt")
        self.assertIsNone(req.source_path)
        self.assertEqual(req.write_mode, "append")

    def test_literal_content(self) -> None:
        self.assertEqual(extract_literal_content('create file called x.txt with the content: Hello World!'), "Hello World!")

    def test_news_requires_web(self) -> None:
        self.assertTrue(analyze_objective("get latest news").web)

    def test_workflow_restricts_write_mode(self) -> None:
        req = analyze_objective("append the file test.txt with more information")
        policy = WorkflowPolicy(req)
        state = TaskState("x")
        available = {"write_file", "append_file", "read_file"}
        self.assertEqual(policy.allowed_tools(state, available), {"append_file"})

    def test_workflow_restricts_to_read_then_write(self) -> None:
        req = analyze_objective("read source.py and summarize it in summary.txt")
        policy = WorkflowPolicy(req)
        state = TaskState("x")
        available = {"read_file", "list_files", "write_file", "run_shell"}
        self.assertEqual(policy.allowed_tools(state, available), {"read_file", "list_files"})
        state.record("read_file", {"path": "source.py"}, {"ok": True, "has_more": False}, 1000)
        self.assertEqual(policy.allowed_tools(state, available), {"write_file"})
