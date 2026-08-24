from __future__ import annotations

import unittest

from agent.action_parser import GraniteActionParser


class ActionParserTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = GraniteActionParser({"read_file", "write_file", "list_files"})

    def test_direct_tool_action(self) -> None:
        action = self.parser.parse('{"action":"read_file","arguments":{"path":"a.py"}}')
        self.assertIsNotNone(action)
        self.assertEqual(action.action, "read_file")
        self.assertEqual(action.arguments, {"path": "a.py"})

    def test_legacy_tool_wrapper(self) -> None:
        action = self.parser.parse('{"action":"tool","tool":"read_file","arguments":{"path":"a.py"}}')
        self.assertIsNotNone(action)
        self.assertEqual(action.action, "read_file")

    def test_nested_arguments_flattened(self) -> None:
        action = self.parser.parse('{"action":"read_file","arguments":{"arguments":{"path":"a.py"}}}')
        self.assertEqual(action.arguments, {"path": "a.py"})

    def test_top_level_arguments_supported(self) -> None:
        action = self.parser.parse('{"action":"read_file","path":"a.py","start_line":3}')
        self.assertEqual(action.arguments, {"path": "a.py", "start_line": 3})

    def test_return_alias_is_completion(self) -> None:
        action = self.parser.parse('{"action":"return","answer":"done"}')
        self.assertTrue(action.is_complete)
        self.assertEqual(action.answer, "done")

    def test_observation_echo_rejected(self) -> None:
        action = self.parser.parse('{"tool":"read_file","arguments":{"path":"a.py"},"result":{"ok":true}}')
        self.assertIsNone(action)

    def test_json_inside_fences(self) -> None:
        action = self.parser.parse('```json\n{"action":"list_files","arguments":{"path":"."}}\n```')
        self.assertEqual(action.action, "list_files")

    def test_unknown_action_rejected(self) -> None:
        self.assertIsNone(self.parser.parse('{"action":"invent_tool"}'))
